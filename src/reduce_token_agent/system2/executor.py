"""Bounded System2 gap executor with frozen constraints and typed artifacts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal, cast

from reduce_token_agent.control_plane.trace_recorder import ControlTraceRecorder
from reduce_token_agent.domain.blueprint import BlueprintStep, StepType
from reduce_token_agent.domain.control import HandoffReceipt, System2Handoff
from reduce_token_agent.domain.runtime import ExecutionRunResult, ExecutionStepResult
from reduce_token_agent.domain.task import TaskContext
from reduce_token_agent.execution.bindings import validate_schema_shape
from reduce_token_agent.execution.ledger import RuntimeLedger
from reduce_token_agent.llm.base import StructuredModel
from reduce_token_agent.registry.models import AssetKind, SideEffect
from reduce_token_agent.registry.service import AssetResolver
from reduce_token_agent.runtime_verification import load_runtime_for_domain
from reduce_token_agent.system2.models import (
    System2Decision,
    System2Resolution,
    System2StepOutcome,
    System2Usage,
)
from reduce_token_agent.trace_data.runtime_models import RuntimeExecutionStepRecord

_GAP_TYPES = {StepType.REASON, StepType.EXTRACT, StepType.HUMAN}
_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|api[_-]?key|authorization|token$|"
    r"principal_id|user_id|customer_id|account_id|phone|address)",
    re.IGNORECASE,
)


class BoundedSystem2Executor:
    """Resolve only explicit gap steps under code-owned limits and verification."""

    def __init__(
        self,
        *,
        project_root: Path,
        model: StructuredModel,
        resolver: AssetResolver,
        trace: ControlTraceRecorder,
    ) -> None:
        self.project_root = project_root
        self.model = model
        self.resolver = resolver
        self.trace = trace
        self.ledger = RuntimeLedger(
            project_root / "data/db/runtime.sqlite3",
            project_root / "migrations/005_execution_ledger.sql",
        )

    def resolve(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        observed_outputs: dict[str, dict[str, Any]] | None = None,
    ) -> System2Resolution:
        """Produce verified Artifact outputs for explicit gap steps."""

        if handoff.execution_contract != "BOUNDED_SYSTEM2_V1":
            raise ValueError("unsupported System2 execution contract")
        selected = [
            step
            for step in steps
            if step.step_id in handoff.reason_step_ids and step.step_type in _GAP_TYPES
        ]
        missing = set(handoff.reason_step_ids) - {step.step_id for step in selected}
        if missing:
            raise ValueError(
                f"System2 handoff contains unknown gap steps: {sorted(missing)}"
            )
        outputs = dict(observed_outputs or {})
        outcomes: list[System2StepOutcome] = []
        usages: list[System2Usage] = []
        self.trace.event(
            run_id=handoff.run_id,
            stage="system2",
            event_type="system2_started",
            payload={
                "task_id": handoff.task_id,
                "reason_step_ids": handoff.reason_step_ids,
                "allowed_asset_refs": handoff.allowed_asset_refs,
                "side_effect_policy": handoff.side_effect_policy,
                "max_reason_steps": handoff.max_reason_steps,
                "max_llm_calls": handoff.max_llm_calls,
                "max_tool_calls": handoff.max_tool_calls,
            },
        )

        llm_calls = 0
        tool_calls = 0
        for step in selected:
            if len(outcomes) >= handoff.max_reason_steps:
                outcomes.append(
                    self._budget_outcome(step, "SYSTEM2_REASON_BUDGET_EXCEEDED")
                )
                continue
            input_summary = _safe_summary(
                {
                    "goal": step.goal,
                    "task_entities": context.entities,
                    "acceptance_criteria": context.acceptance_criteria,
                    "dependency_outputs": {
                        dependency: outputs.get(dependency, {})
                        for dependency in step.depends_on
                    },
                    "allowed_asset_refs": handoff.allowed_asset_refs,
                }
            )
            self.trace.event(
                run_id=handoff.run_id,
                stage="system2",
                event_type="system2_step_started",
                payload={
                    "step_id": step.step_id,
                    "subgoal_id": step.subgoal_id,
                    "step_type": step.step_type.value,
                    "input_safe_summary": input_summary,
                },
            )

            if step.step_type is not StepType.HUMAN and step.step_id in outputs:
                prior_output = _safe_summary(outputs[step.step_id])
                outcome = System2StepOutcome(
                    step_id=step.step_id,
                    subgoal_id=step.subgoal_id,
                    step_type=_gap_step_type(step),
                    status="SUCCEEDED",
                    action="FINISH",
                    input_summary={
                        **input_summary,
                        "resume_source": "PRIOR_VERIFIED_OUTPUT",
                    },
                    output_summary=prior_output,
                    validation_status="PASS",
                    artifact_refs=[],
                )
            elif step.step_type is StepType.HUMAN and step.step_id in outputs:
                answer = _safe_summary(outputs[step.step_id])
                output = {
                    "status": "RESOLVED_BY_HUMAN",
                    "summary": "已收到人工确认，继续执行后续固定流程。",
                    "facts": {"human_answer": answer},
                    "evidence_refs": [],
                }
                artifact_ref = self._write_artifact(
                    handoff.run_id, step.step_id, output
                )
                outcome = System2StepOutcome(
                    step_id=step.step_id,
                    subgoal_id=step.subgoal_id,
                    step_type=_gap_step_type(step),
                    status="SUCCEEDED",
                    action="ASK_HUMAN",
                    input_summary=input_summary,
                    output_summary=output,
                    validation_status="PASS",
                    artifact_refs=[artifact_ref],
                )
            elif step.step_type is StepType.HUMAN:
                output = {
                    "status": "WAITING_HUMAN",
                    "summary": "该缺口需要权威人工输入，System2 已停止自动推进。",
                    "facts": {},
                    "evidence_refs": [],
                }
                artifact_ref = self._write_artifact(
                    handoff.run_id, step.step_id, output
                )
                outcome = System2StepOutcome(
                    step_id=step.step_id,
                    subgoal_id=step.subgoal_id,
                    step_type=_gap_step_type(step),
                    status="PARTIAL",
                    action="ASK_HUMAN",
                    input_summary=input_summary,
                    output_summary=output,
                    validation_status="NEEDS_REVIEW",
                    artifact_refs=[artifact_ref],
                )
            elif llm_calls >= handoff.max_llm_calls:
                outcome = self._budget_outcome(
                    step,
                    "SYSTEM2_LLM_BUDGET_EXCEEDED",
                    input_summary=input_summary,
                )
            else:
                result = self.model.generate_structured(
                    stage="system2_reason",
                    system_prompt=(
                        "你是有界 System2，只完成当前一个 gap step。不要输出思维链。"
                        "只能返回 CALL_TOOL、FINISH、ASK_HUMAN、ABORT。CALL_TOOL 必须"
                        "逐字选择 allowed_asset_refs 中的只读 Tool；没有必要调用工具时"
                        "直接 FINISH，并在 facts 中给出可审计的类型化事实。不得声称已"
                        "修改外部系统，不得把自己生成的结论标记为独立业务验证通过。"
                    ),
                    user_payload={
                        "run_id": handoff.run_id,
                        "step": step.model_dump(mode="json"),
                        "task": {
                            "entities": context.entities,
                            "acceptance_criteria": context.acceptance_criteria,
                            "risk_level": context.risk_level.value,
                            "data_classification": context.data_classification.value,
                        },
                        "dependency_outputs": {
                            dependency: outputs.get(dependency, {})
                            for dependency in step.depends_on
                        },
                        "allowed_asset_refs": handoff.allowed_asset_refs,
                        "side_effect_policy": handoff.side_effect_policy,
                    },
                    output_model=System2Decision,
                )
                llm_calls += 1
                usage = System2Usage(
                    stage=result.usage.stage,
                    model=result.usage.model,
                    input_tokens=result.usage.input_tokens or 0,
                    output_tokens=result.usage.output_tokens or 0,
                    total_duration_ns=result.usage.total_duration_ns or 0,
                    estimated=result.usage.estimated,
                    attempts=result.usage.attempts,
                )
                usages.append(usage)
                self.trace.event(
                    run_id=handoff.run_id,
                    stage="system2_reason",
                    event_type="llm_usage",
                    payload=usage,
                )
                decision = result.value
                if decision.action == "CALL_TOOL":
                    if tool_calls >= handoff.max_tool_calls:
                        outcome = self._failed_outcome(
                            step,
                            input_summary,
                            "SYSTEM2_TOOL_BUDGET_EXCEEDED",
                            decision.action,
                            usage,
                        )
                    else:
                        tool_calls += 1
                        outcome = self._call_allowed_tool(
                            handoff,
                            step,
                            input_summary,
                            decision,
                            usage,
                        )
                elif decision.action == "FINISH":
                    outcome = self._finish(
                        handoff, step, input_summary, decision, usage
                    )
                elif decision.action == "ASK_HUMAN":
                    outcome = self._partial_outcome(
                        handoff, step, input_summary, decision, usage
                    )
                else:
                    outcome = self._failed_outcome(
                        step,
                        input_summary,
                        decision.failure_code or "SYSTEM2_ABORTED",
                        decision.action,
                        usage,
                        summary=decision.summary,
                    )

            outcomes.append(outcome)
            if outcome.status != "FAILED":
                outputs[step.step_id] = outcome.output_summary
            self.trace.event(
                run_id=handoff.run_id,
                stage="system2",
                event_type=(
                    "system2_step_failed"
                    if outcome.status == "FAILED"
                    else "system2_step_waiting_human"
                    if outcome.status == "PARTIAL"
                    else "system2_step_succeeded"
                ),
                payload=outcome,
            )
            # A HUMAN gate is a hard pause point. Do not evaluate later gap
            # steps until the caller resumes this same handoff with a typed
            # answer. This keeps the pending step and its required input
            # unambiguous for an API/UI client.
            if outcome.status == "PARTIAL":
                break

        status = (
            "FAILED"
            if any(item.status == "FAILED" for item in outcomes)
            else "PARTIAL"
            if len(selected) > handoff.max_reason_steps
            or any(item.status == "PARTIAL" for item in outcomes)
            else "SUCCEEDED"
        )
        input_tokens = sum(item.input_tokens for item in outcomes)
        output_tokens = sum(item.output_tokens for item in outcomes)
        resolution = System2Resolution(
            run_id=handoff.run_id,
            status=cast(Literal["SUCCEEDED", "PARTIAL", "FAILED"], status),
            step_outcomes=outcomes,
            outputs={
                item.step_id: item.output_summary
                for item in outcomes
                if item.status != "FAILED"
            },
            usages=usages,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
        self.trace.event(
            run_id=handoff.run_id,
            stage="system2",
            event_type="system2_completed",
            payload=resolution,
        )
        return resolution

    def submit(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        observed_outputs: dict[str, dict[str, Any]] | None = None,
        resume: bool = False,
    ) -> HandoffReceipt:
        """Run a standalone NEW gap plan and persist it in the Runtime Ledger."""

        blueprint_id = "system2_gap_" + handoff.run_id.removeprefix("run_")
        if resume:
            self.ledger.resume_run(
                run_id=handoff.run_id,
                blueprint_id=blueprint_id,
            )
        else:
            self.ledger.start_run(
                run_id=handoff.run_id,
                thread_id=handoff.run_id,
                blueprint_id=blueprint_id,
            )
        resolution = self.resolve(
            handoff,
            steps,
            context,
            observed_outputs=observed_outputs,
        )
        for usage in resolution.usages:
            self.ledger.record_token_usage(
                run_id=handoff.run_id,
                stage=usage.stage,
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                attempts=usage.attempts,
                estimated=usage.estimated,
            )
        step_by_id = {step.step_id: step for step in steps}
        step_results: list[ExecutionStepResult] = []
        for outcome in resolution.step_outcomes:
            step = step_by_id[outcome.step_id]
            self._record_standalone_step(handoff.run_id, step, outcome)
            step_results.append(_execution_step_result(outcome))
        execution = ExecutionRunResult(
            run_id=handoff.run_id,
            thread_id=handoff.run_id,
            blueprint_id=blueprint_id,
            status=resolution.status,
            step_results=step_results,
            outputs=resolution.outputs,
            placeholder_step_ids=[
                item.step_id
                for item in resolution.step_outcomes
                if item.status == "PARTIAL"
            ],
            failed_step_id=next(
                (
                    item.step_id
                    for item in resolution.step_outcomes
                    if item.status == "FAILED"
                ),
                None,
            ),
            failure_code=next(
                (
                    item.failure_code
                    for item in resolution.step_outcomes
                    if item.failure_code
                ),
                None,
            ),
            business_validated=False,
            input_tokens=resolution.input_tokens,
            output_tokens=resolution.output_tokens,
            total_tokens=resolution.total_tokens,
        )
        self.ledger.finish_run(execution)
        self.trace.event(
            run_id=handoff.run_id,
            stage="execution",
            event_type="execution_completed",
            payload=execution,
        )
        return HandoffReceipt(
            target="SYSTEM2",
            status=execution.status,
            accepted=True,
            message=(
                f"Task {handoff.task_id} completed by bounded System2 "
                f"with status {execution.status}."
            ),
            execution=execution,
        )

    def resume(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        human_answers: dict[str, dict[str, Any]],
        prior_outputs: dict[str, dict[str, Any]] | None = None,
    ) -> System2Resolution:
        """Continue an interrupted HUMAN gap with a typed user answer."""
        if not human_answers:
            raise ValueError("human_answers cannot be empty")
        observed = dict(prior_outputs or {})
        observed.update(human_answers)
        return self.resolve(
            handoff,
            steps,
            context,
            observed_outputs=observed,
        )

    def _finish(
        self,
        handoff: System2Handoff,
        step: BlueprintStep,
        input_summary: dict[str, Any],
        decision: System2Decision,
        usage: System2Usage,
    ) -> System2StepOutcome:
        invalid_evidence = [
            ref
            for ref in decision.evidence_refs
            if not (
                ref.startswith(f"artifact://{handoff.run_id}/")
                or ref.startswith(
                    f"trace://trace_{handoff.run_id.removeprefix('run_')}"
                )
            )
        ]
        if invalid_evidence:
            return self._failed_outcome(
                step,
                input_summary,
                "EVIDENCE_SCOPE_DENIED",
                decision.action,
                usage,
                summary="System2 输出引用了当前 Run 之外的证据。",
            )
        output = {
            "status": "RESOLVED",
            "summary": decision.summary,
            "facts": _safe_summary(decision.facts),
            "evidence_refs": list(decision.evidence_refs),
        }
        artifact_ref = self._write_artifact(handoff.run_id, step.step_id, output)
        if not output["evidence_refs"]:
            output["evidence_refs"] = [artifact_ref]
            self._write_artifact(handoff.run_id, step.step_id, output)
        return System2StepOutcome(
            step_id=step.step_id,
            subgoal_id=step.subgoal_id,
            step_type=_gap_step_type(step),
            status="SUCCEEDED",
            action=decision.action,
            input_summary=input_summary,
            output_summary=output,
            validation_status="PASS",
            artifact_refs=[artifact_ref],
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    def _call_allowed_tool(
        self,
        handoff: System2Handoff,
        step: BlueprintStep,
        input_summary: dict[str, Any],
        decision: System2Decision,
        usage: System2Usage,
    ) -> System2StepOutcome:
        tool_ref = cast(str, decision.tool_ref)
        if tool_ref not in handoff.allowed_asset_refs:
            return self._failed_outcome(
                step, input_summary, "TOOL_NOT_ALLOWED", decision.action, usage
            )
        details = self.resolver.resolve(tool_ref)
        if details.kind is not AssetKind.PRIMITIVE_TOOL:
            return self._failed_outcome(
                step,
                input_summary,
                "SYSTEM2_TOOL_KIND_DENIED",
                decision.action,
                usage,
            )
        if details.contract["side_effect"] not in {
            SideEffect.NONE.value,
            SideEffect.READ_ONLY.value,
        }:
            return self._failed_outcome(
                step,
                input_summary,
                "SYSTEM2_SIDE_EFFECT_DENIED",
                decision.action,
                usage,
            )
        try:
            validate_schema_shape(decision.tool_input, details.call.input_schema)
            runtime = load_runtime_for_domain(details.domain)
            observation = runtime.execute(tool_ref, decision.tool_input)
            validate_schema_shape(observation, details.call.output_schema)
        except Exception as exc:
            return self._failed_outcome(
                step,
                input_summary,
                str(getattr(exc, "code", type(exc).__name__.upper())),
                decision.action,
                usage,
            )
        output = {
            "status": "RESOLVED_WITH_TOOL",
            "summary": decision.summary,
            "facts": _safe_summary(decision.facts),
            "tool_ref": tool_ref,
            "tool_observation": _safe_summary(observation),
            "evidence_refs": [],
        }
        artifact_ref = self._write_artifact(handoff.run_id, step.step_id, output)
        output["evidence_refs"] = [artifact_ref]
        self._write_artifact(handoff.run_id, step.step_id, output)
        return System2StepOutcome(
            step_id=step.step_id,
            subgoal_id=step.subgoal_id,
            step_type=_gap_step_type(step),
            status="SUCCEEDED",
            action=decision.action,
            input_summary=input_summary,
            output_summary=output,
            validation_status="PASS",
            artifact_refs=[artifact_ref],
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    def _partial_outcome(
        self,
        handoff: System2Handoff,
        step: BlueprintStep,
        input_summary: dict[str, Any],
        decision: System2Decision,
        usage: System2Usage,
    ) -> System2StepOutcome:
        output = {
            "status": "WAITING_HUMAN",
            "summary": decision.summary,
            "facts": _safe_summary(decision.facts),
            "evidence_refs": list(decision.evidence_refs),
        }
        artifact_ref = self._write_artifact(handoff.run_id, step.step_id, output)
        return System2StepOutcome(
            step_id=step.step_id,
            subgoal_id=step.subgoal_id,
            step_type=_gap_step_type(step),
            status="PARTIAL",
            action=decision.action,
            input_summary=input_summary,
            output_summary=output,
            validation_status="NEEDS_REVIEW",
            artifact_refs=[artifact_ref],
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    def _failed_outcome(
        self,
        step: BlueprintStep,
        input_summary: dict[str, Any],
        failure_code: str,
        action: str,
        usage: System2Usage,
        *,
        summary: str = "System2 输出未通过代码侧约束或验证。",
    ) -> System2StepOutcome:
        return System2StepOutcome(
            step_id=step.step_id,
            subgoal_id=step.subgoal_id,
            step_type=_gap_step_type(step),
            status="FAILED",
            action=cast(Any, action),
            input_summary=input_summary,
            output_summary={"status": "FAILED", "summary": summary},
            validation_status="FAIL",
            failure_code=failure_code,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    def _budget_outcome(
        self,
        step: BlueprintStep,
        failure_code: str,
        *,
        input_summary: dict[str, Any] | None = None,
    ) -> System2StepOutcome:
        return System2StepOutcome(
            step_id=step.step_id,
            subgoal_id=step.subgoal_id,
            step_type=_gap_step_type(step),
            status="PARTIAL",
            action="ASK_HUMAN",
            input_summary=input_summary or {},
            output_summary={
                "status": "WAITING_HUMAN",
                "summary": "System2 预算已耗尽，停止自动推进并转人工。",
            },
            validation_status="NEEDS_REVIEW",
            failure_code=failure_code,
        )

    def _record_standalone_step(
        self,
        run_id: str,
        step: BlueprintStep,
        outcome: System2StepOutcome,
    ) -> None:
        for phase in (
            "STARTED",
            "FAILED" if outcome.status == "FAILED" else "SUCCEEDED",
        ):
            record = RuntimeExecutionStepRecord(
                step_id=step.step_id,
                subgoal_id=step.subgoal_id,
                phase=cast(Any, phase),
                executor_kind=step.step_type.value,
                operation_key="system2.gap.resolve",
                goal=step.goal,
                asset_ref=None,
                input_safe_summary=outcome.input_summary,
                output_safe_summary=(
                    {} if phase == "STARTED" else outcome.output_summary
                ),
                output_artifact_refs=(
                    [] if phase == "STARTED" else outcome.artifact_refs
                ),
                validation_status=(
                    "NOT_RUN" if phase == "STARTED" else outcome.validation_status
                ),
                business_validated=False,
                failure_code=(
                    outcome.failure_code if phase != "STARTED" else None
                ),
                side_effect=SideEffect.NONE.value,
                duration_ns=0,
                input_tokens=outcome.input_tokens if phase != "STARTED" else 0,
                output_tokens=outcome.output_tokens if phase != "STARTED" else 0,
                decision_summary=(
                    "有界 System2 已冻结上下文和约束，开始处理当前缺口。"
                    if phase == "STARTED"
                    else "System2 缺口输出已完成结构、证据和策略验证。"
                ),
            )
            self.ledger.record_step(run_id, record)
            self.trace.execution_step(run_id=run_id, record=record)

    def _write_artifact(
        self,
        run_id: str,
        step_id: str,
        payload: dict[str, Any],
    ) -> str:
        root = self.project_root / "data/runtime/artifacts" / run_id
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{step_id}.system2.json"
        path.write_text(
            json.dumps(_safe_summary(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return f"artifact://{run_id}/{step_id}.system2?path={path}"


def _execution_step_result(outcome: System2StepOutcome) -> ExecutionStepResult:
    return ExecutionStepResult(
        step_id=outcome.step_id,
        subgoal_id=outcome.subgoal_id,
        step_type=outcome.step_type,
        status=(
            "FAILED"
            if outcome.status == "FAILED"
            else "PLACEHOLDER"
            if outcome.status == "PARTIAL"
            else "SUCCEEDED"
        ),
        asset_ref=None,
        input_source="SYSTEM2_FROZEN_CONTEXT",
        input_summary=outcome.input_summary,
        output_summary=outcome.output_summary,
        validation_status=outcome.validation_status,
        business_validated=False,
        failure_code=outcome.failure_code,
        placeholder_reason="WAITING_HUMAN" if outcome.status == "PARTIAL" else None,
        artifact_refs=outcome.artifact_refs,
        input_tokens=outcome.input_tokens,
        output_tokens=outcome.output_tokens,
    )


def _gap_step_type(
    step: BlueprintStep,
) -> Literal["REASON", "EXTRACT", "HUMAN"]:
    return cast(Literal["REASON", "EXTRACT", "HUMAN"], step.step_type.value)


def _safe_summary(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if _SENSITIVE_KEY.search(str(key))
                else _safe_summary(item, depth=depth + 1)
            )
            for key, item in list(value.items())[:30]
        }
    if isinstance(value, list):
        return [_safe_summary(item, depth=depth + 1) for item in value[:20]]
    if isinstance(value, str):
        return value[:500]
    return value
