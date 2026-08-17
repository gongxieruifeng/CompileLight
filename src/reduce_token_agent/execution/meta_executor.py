"""Strict fixed-graph Meta-Executor for compiled Blueprint data."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Literal, cast

from reduce_token_agent.control_plane.trace_recorder import ControlTraceRecorder
from reduce_token_agent.domain.blueprint import (
    BlueprintStep,
    CompiledBlueprint,
    StepType,
    is_lightweight_gap_step,
)
from reduce_token_agent.domain.control import HandoffReceipt, LangGraphHandoff
from reduce_token_agent.domain.runtime import ExecutionRunResult, ExecutionStepResult
from reduce_token_agent.domain.task import TaskContext
from reduce_token_agent.execution.bindings import (
    BindingError,
    resolve_step_inputs,
    validate_schema_shape,
)
from reduce_token_agent.execution.checkpoint import ExecutionCheckpoint
from reduce_token_agent.execution.graph import build_fixed_execution_graph
from reduce_token_agent.execution.ledger import RuntimeLedger
from reduce_token_agent.execution.scheduler import (
    has_blocked_pending_steps,
    select_ready_step,
)
from reduce_token_agent.execution.state import ExecutionGraphState
from reduce_token_agent.registry.models import AssetKind, SideEffect
from reduce_token_agent.registry.service import AssetResolver
from reduce_token_agent.runtime_verification import load_runtime_for_domain
from reduce_token_agent.system2.models import System2Resolution
from reduce_token_agent.trace_data.runtime_models import RuntimeExecutionStepRecord

_ASSET_STEP_KIND = {
    StepType.FSM.value: AssetKind.FSM_SHARD,
    StepType.TOOL.value: AssetKind.PRIMITIVE_TOOL,
    StepType.ADAPTER.value: AssetKind.ADAPTER,
    StepType.VALIDATOR.value: AssetKind.VALIDATOR,
}
_PLACEHOLDER_TYPES = {
    StepType.REASON.value,
    StepType.EXTRACT.value,
    StepType.HUMAN.value,
}
_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|api[_-]?key|authorization|token$|"
    r"principal_id|user_id|customer_id|account_id|phone|address)",
    re.IGNORECASE,
)


class LangGraphMetaExecutor:
    """Execute only compiler-produced Blueprint steps on one fixed graph."""

    def __init__(
        self,
        *,
        project_root: Path,
        resolver: AssetResolver,
        trace: ControlTraceRecorder,
    ) -> None:
        self.project_root = project_root
        self.resolver = resolver
        self.trace = trace
        self.checkpoint = ExecutionCheckpoint(
            project_root / "data/db/checkpoints.sqlite3"
        )
        self.ledger = RuntimeLedger(
            project_root / "data/db/runtime.sqlite3",
            project_root / "migrations/005_execution_ledger.sql",
        )
        self.graph = build_fixed_execution_graph(self, self.checkpoint.saver)

    def submit(
        self,
        handoff: LangGraphHandoff,
        blueprint: CompiledBlueprint,
        context: TaskContext,
        system2_resolution: System2Resolution | None = None,
        *,
        resume: bool = False,
        previous_execution: ExecutionRunResult | None = None,
    ) -> HandoffReceipt:
        """Execute a frozen compiled Blueprint and return its structured result."""
        if handoff.compiled_blueprint_id != blueprint.blueprint_id:
            raise ValueError("compiled Blueprint identity does not match handoff")
        if handoff.registry_view != blueprint.registry_view:
            raise ValueError("compiled Blueprint registry view does not match handoff")

        thread_id = handoff.run_id
        if resume:
            self.ledger.resume_run(
                run_id=handoff.run_id,
                blueprint_id=blueprint.blueprint_id,
            )
        else:
            self.ledger.start_run(
                run_id=handoff.run_id,
                thread_id=thread_id,
                blueprint_id=blueprint.blueprint_id,
            )
        self.trace.event(
            run_id=handoff.run_id,
            stage="execution",
            event_type="execution_resumed" if resume else "execution_started",
            payload={
                "thread_id": thread_id,
                "blueprint_id": blueprint.blueprint_id,
                "step_count": len(blueprint.steps),
                "registry_view": blueprint.registry_view,
                "resume": resume,
            },
        )
        resume_seed = _resume_seed(previous_execution) if resume else {}
        initial: ExecutionGraphState = {
            "run_id": handoff.run_id,
            "thread_id": thread_id,
            "blueprint": blueprint.model_dump(mode="json"),
            "task_context": context.model_dump(mode="json"),
            "step_statuses": resume_seed.get("step_statuses", {}),
            "step_results": resume_seed.get("step_results", {}),
            "outputs": resume_seed.get("outputs", {}),
            "system2_outputs": (
                system2_resolution.outputs if system2_resolution is not None else {}
            ),
            "system2_step_tokens": (
                {
                    item.step_id: (item.input_tokens, item.output_tokens)
                    for item in system2_resolution.step_outcomes
                }
                if system2_resolution is not None
                else {}
            ),
            "system2_partial_step_ids": (
                [
                    item.step_id
                    for item in system2_resolution.step_outcomes
                    if item.status == "PARTIAL"
                ]
                if system2_resolution is not None
                else []
            ),
            "input_tokens": int(resume_seed.get("input_tokens", 0)),
            "output_tokens": int(resume_seed.get("output_tokens", 0)),
            "current_step_id": None,
            "placeholder_step_ids": resume_seed.get(
                "placeholder_step_ids", []
            ),
            "failed_step_id": None,
            "final_status": "RUNNING",
        }
        if system2_resolution is not None:
            for usage in system2_resolution.usages:
                self.ledger.record_token_usage(
                    run_id=handoff.run_id,
                    stage=usage.stage,
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    attempts=usage.attempts,
                    estimated=usage.estimated,
                )
        try:
            final = cast(
                ExecutionGraphState,
                self.graph.invoke(
                    initial,
                    config={"configurable": {"thread_id": thread_id}},
                ),
            )
            result = self._to_result(final)
        except Exception as exc:
            failure_code = str(getattr(exc, "code", type(exc).__name__.upper()))
            result = ExecutionRunResult(
                run_id=handoff.run_id,
                thread_id=thread_id,
                blueprint_id=blueprint.blueprint_id,
                status="FAILED",
                step_results=[],
                outputs={},
                placeholder_step_ids=[],
                failure_code=failure_code,
                business_validated=False,
            )
            self.trace.event(
                run_id=handoff.run_id,
                stage="execution",
                event_type="execution_failed",
                payload={
                    "failure_code": failure_code,
                    "message": str(exc)[:500],
                },
            )

        self.ledger.record_token_usage(
            run_id=handoff.run_id,
            stage="langgraph_execution",
            model="deterministic-runtime",
            input_tokens=0,
            output_tokens=0,
            attempts=0,
            estimated=False,
        )
        self.trace.event(
            run_id=handoff.run_id,
            stage="langgraph_execution",
            event_type="llm_usage",
            payload={
                "model": "deterministic-runtime",
                "input_tokens": 0,
                "output_tokens": 0,
                "total_duration_ns": 0,
                "estimated": False,
                "attempts": 0,
            },
        )
        self.ledger.finish_run(result)
        self.trace.event(
            run_id=handoff.run_id,
            stage="execution",
            event_type="execution_completed",
            payload=result,
        )
        return HandoffReceipt(
            target="LANGGRAPH_EXECUTION",
            status=result.status,
            accepted=True,
            message=(
                f"Blueprint {blueprint.blueprint_id} executed by the fixed "
                f"LangGraph Meta-Executor with status {result.status}."
            ),
            execution=result,
        )

    def load_compiled_blueprint(
        self,
        state: ExecutionGraphState,
    ) -> dict[str, Any]:
        steps = cast(list[dict[str, Any]], state["blueprint"]["steps"])
        statuses = {
            str(step["step_id"]): "PENDING"
            for step in steps
        }
        statuses.update(state.get("step_statuses", {}))
        return {
            "step_statuses": statuses,
            "step_results": dict(state.get("step_results", {})),
            "outputs": dict(state.get("outputs", {})),
            "placeholder_step_ids": list(
                state.get("placeholder_step_ids", [])
            ),
            "final_status": "RUNNING",
        }

    def select_ready_step(self, state: ExecutionGraphState) -> dict[str, Any]:
        steps = cast(list[dict[str, Any]], state["blueprint"]["steps"])
        statuses = state["step_statuses"]
        selected = select_ready_step(steps, statuses)
        if selected is not None:
            updated = dict(statuses)
            updated[selected] = "READY"
            return {"current_step_id": selected, "step_statuses": updated}
        if has_blocked_pending_steps(steps, statuses):
            return {
                "current_step_id": None,
                "final_status": "FAILED",
                "current_failure_code": "DEPENDENCY_FAILED",
            }
        return {"current_step_id": None}

    def after_select(
        self,
        state: ExecutionGraphState,
    ) -> Literal["dispatch", "finalize"]:
        return "dispatch" if state.get("current_step_id") else "finalize"

    def dispatch(self, state: ExecutionGraphState) -> dict[str, Any]:
        step = self._current_step(state)
        step_id = str(step["step_id"])
        statuses = dict(state["step_statuses"])
        statuses[step_id] = "RUNNING"
        started = time.monotonic_ns()
        step_type = str(step["step_type"])
        lightweight = _is_lightweight_state_step(step)
        precomputed = state.get("system2_outputs", {}).get(step_id)
        if step_type in _PLACEHOLDER_TYPES and precomputed is not None:
            input_tokens, output_tokens = state.get(
                "system2_step_tokens", {}
            ).get(step_id, (0, 0))
            return {
                "step_statuses": statuses,
                "current_input": {},
                "current_input_source": "SYSTEM2_EXECUTOR",
                "current_output": precomputed,
                "current_validation_status": (
                    "NEEDS_REVIEW"
                    if step_id in state.get("system2_partial_step_ids", [])
                    else "PASS"
                ),
                "current_business_validated": False,
                "current_failure_code": None,
                "current_input_tokens": input_tokens,
                "current_output_tokens": output_tokens,
                "placeholder_step_ids": (
                    [*state.get("placeholder_step_ids", []), step_id]
                    if step_id in state.get("system2_partial_step_ids", [])
                    else state.get("placeholder_step_ids", [])
                ),
                "_started_ns": started,
            }
        if lightweight:
            output = _lightweight_output(step, state)
            self._record(
                state,
                step,
                phase="STARTED",
                input_payload={},
                output_payload={},
                validation_status="NOT_RUN",
                business_validated=False,
                decision_summary="轻量格式/信息缺口由固定执行器零 Token 处理。",
            )
            return {
                "step_statuses": statuses,
                "current_input": {},
                "current_input_source": "LIGHTWEIGHT_DETERMINISTIC",
                "current_output": output,
                "current_validation_status": "PASS",
                "current_business_validated": True,
                "current_failure_code": None,
                "current_input_tokens": 0,
                "current_output_tokens": 0,
                "_started_ns": started,
            }
        if step_type in _PLACEHOLDER_TYPES:
            placeholder = {
                "placeholder": True,
                "status": "SKIPPED_SYSTEM2_NOT_IMPLEMENTED",
                "step_type": step_type,
                "goal": step["goal"],
                "reason_code": step["reason_code"],
            }
            self._record(
                state,
                step,
                phase="STARTED",
                input_payload={},
                output_payload={},
                validation_status="NOT_RUN",
                business_validated=False,
                decision_summary="需要 System2 的步骤已进入显式占位执行。",
            )
            return {
                "step_statuses": statuses,
                "current_input": {},
                "current_input_source": "SYSTEM2_PLACEHOLDER",
                "current_output": placeholder,
                "current_validation_status": "NEEDS_REVIEW",
                "current_business_validated": False,
                "current_failure_code": None,
                "current_input_tokens": 0,
                "current_output_tokens": 0,
                "placeholder_step_ids": [
                    *state.get("placeholder_step_ids", []),
                    step_id,
                ],
                "_started_ns": started,
            }

        asset_ref = str(step.get("asset_ref") or "")
        if not asset_ref:
            raise BindingError("ASSET_REF_MISSING", f"{step_id} has no asset_ref")
        details = self.resolver.resolve(asset_ref)
        expected_kind = _ASSET_STEP_KIND.get(step_type)
        if expected_kind is None or details.kind is not expected_kind:
            raise BindingError(
                "EXECUTOR_KIND_MISMATCH",
                f"{step_type} cannot execute {details.kind}",
            )
        if details.validation_status != "PASS" or details.call.tested_at is None:
            raise PermissionError(f"asset is not tested: {asset_ref}")
        if details.call.runtime_status != "READY":
            raise PermissionError(f"asset runtime is not ready: {asset_ref}")
        if str(step["side_effect"]) != str(details.contract["side_effect"]):
            raise PermissionError(f"side-effect contract changed: {asset_ref}")
        payload, source = resolve_step_inputs(
            step=step,
            task_context=state["task_context"],
            outputs=state.get("outputs", {}),
            sample_payload=details.call.sample_payload,
        )
        validate_schema_shape(payload, details.call.input_schema)
        self._record(
            state,
            step,
            phase="STARTED",
            input_payload=payload,
            output_payload={},
            validation_status="NOT_RUN",
            business_validated=False,
            decision_summary="固定版本资产已通过运行前门禁并开始执行。",
        )
        runtime = load_runtime_for_domain(details.domain)
        try:
            output = runtime.execute(asset_ref, payload)
            return {
                "step_statuses": statuses,
                "current_input": payload,
                "current_input_source": source,
                "current_output": output,
                "current_validation_status": "NOT_RUN",
                "current_business_validated": False,
                "current_failure_code": None,
                "current_input_tokens": 0,
                "current_output_tokens": 0,
                "_started_ns": started,
            }
        except Exception as exc:
            return {
                "step_statuses": statuses,
                "current_input": payload,
                "current_input_source": source,
                "current_output": {},
                "current_validation_status": "FAIL",
                "current_business_validated": False,
                "current_failure_code": str(
                    getattr(exc, "code", type(exc).__name__.upper())
                ),
                "current_input_tokens": 0,
                "current_output_tokens": 0,
                "_started_ns": started,
            }

    def validate_output(self, state: ExecutionGraphState) -> dict[str, Any]:
        if state.get("current_failure_code"):
            return {}
        step = self._current_step(state)
        step_type = str(step["step_type"])
        if step_type in _PLACEHOLDER_TYPES:
            return {}
        details = self.resolver.resolve(str(step["asset_ref"]))
        try:
            validate_schema_shape(state["current_output"], details.call.output_schema)
        except BindingError as exc:
            return {
                "current_validation_status": "FAIL",
                "current_failure_code": exc.code,
            }
        if step_type == StepType.VALIDATOR.value:
            valid = state["current_output"].get("valid") is True
            failure_codes = state["current_output"].get("failure_codes", [])
            return {
                "current_validation_status": "PASS" if valid else "FAIL",
                "current_business_validated": valid,
                "current_failure_code": (
                    None
                    if valid
                    else str(failure_codes[0] if failure_codes else "VALIDATOR_REJECTED")
                ),
            }
        return {"current_validation_status": "PASS"}

    def persist_ledger(self, state: ExecutionGraphState) -> dict[str, Any]:
        step = self._current_step(state)
        step_id = str(step["step_id"])
        failed = state.get("current_failure_code") is not None
        precomputed_system2 = (
            str(step["step_id"]) in state.get("system2_outputs", {})
        )
        placeholder = (
            str(step["step_type"]) in _PLACEHOLDER_TYPES
            and (
                not precomputed_system2
                or str(step["step_id"]) in state.get("system2_partial_step_ids", [])
            )
            and not _is_lightweight_state_step(step)
        )
        statuses = dict(state["step_statuses"])
        statuses[step_id] = "FAILED" if failed else "SUCCEEDED"
        result = ExecutionStepResult(
            step_id=step_id,
            subgoal_id=str(step["subgoal_id"]),
            step_type=str(step["step_type"]),
            status=(
                "FAILED"
                if failed
                else "PLACEHOLDER"
                if placeholder
                else "SUCCEEDED"
            ),
            asset_ref=cast(str | None, step.get("asset_ref")),
            input_source=state.get("current_input_source", "UNKNOWN"),
            input_summary=_safe_summary(state.get("current_input", {})),
            output_summary=_safe_summary(state.get("current_output", {})),
            validation_status=cast(
                Literal["NOT_RUN", "PASS", "FAIL", "NEEDS_REVIEW"],
                state.get("current_validation_status", "NOT_RUN"),
            ),
            business_validated=state.get("current_business_validated", False),
            failure_code=state.get("current_failure_code"),
                placeholder_reason=(
                    "WAITING_HUMAN"
                    if str(step["step_id"]) in state.get("system2_partial_step_ids", [])
                    else "SYSTEM2_NOT_IMPLEMENTED"
                    if placeholder
                    else None
                ),
            artifact_refs=[
                self._write_artifact(
                    state["run_id"],
                    step_id,
                    state.get("current_output", {}),
                )
            ],
            input_tokens=int(state.get("current_input_tokens", 0)),
            output_tokens=int(state.get("current_output_tokens", 0)),
        )
        results = dict(state.get("step_results", {}))
        results[step_id] = result.model_dump(mode="json")
        outputs = dict(state.get("outputs", {}))
        if not failed:
            outputs[step_id] = state.get("current_output", {})
        duration = max(
            time.monotonic_ns() - int(state.get("_started_ns", time.monotonic_ns())),
            0,
        )
        self._record(
            state,
            step,
            phase="FAILED" if failed else "SUCCEEDED",
            input_payload=state.get("current_input", {}),
            output_payload=state.get("current_output", {}),
            validation_status=result.validation_status,
            business_validated=result.business_validated,
            failure_code=result.failure_code,
            artifact_refs=result.artifact_refs,
            duration_ns=duration,
            decision_summary=(
                "步骤执行失败，固定执行图停止推进。"
                if failed
                else "步骤输出已完成结构和业务验证并写入账本。"
                if result.business_validated
                else "步骤输出已完成结构验证并写入账本。"
            ),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        return {
            "step_statuses": statuses,
            "step_results": results,
            "outputs": outputs,
            "failed_step_id": step_id if failed else state.get("failed_step_id"),
            "final_status": "FAILED" if failed else state.get("final_status", "RUNNING"),
            "input_tokens": state.get("input_tokens", 0)
            + result.input_tokens,
            "output_tokens": state.get("output_tokens", 0)
            + result.output_tokens,
        }

    def route_next(self, state: ExecutionGraphState) -> dict[str, Any]:
        return {}

    def after_route(
        self,
        state: ExecutionGraphState,
    ) -> Literal[
        "select_ready_step",
        "retry_wait",
        "human_interrupt",
        "compensate",
        "finalize",
    ]:
        if state.get("final_status") == "FAILED":
            return "finalize"
        current_step_id = state.get("current_step_id")
        if current_step_id in state.get("system2_partial_step_ids", []):
            return "human_interrupt"
        return "select_ready_step"

    def retry_wait(self, state: ExecutionGraphState) -> dict[str, Any]:
        return {}

    def human_interrupt(self, state: ExecutionGraphState) -> dict[str, Any]:
        return {"final_status": "PARTIAL"}

    def compensate(self, state: ExecutionGraphState) -> dict[str, Any]:
        return {"final_status": "FAILED"}

    def finalize(self, state: ExecutionGraphState) -> dict[str, Any]:
        if state.get("final_status") == "FAILED":
            return {}
        if state.get("placeholder_step_ids"):
            return {"final_status": "PARTIAL"}
        return {"final_status": "SUCCEEDED"}

    def _to_result(self, state: ExecutionGraphState) -> ExecutionRunResult:
        blueprint = state["blueprint"]
        ordered = [
            ExecutionStepResult.model_validate(
                state.get("step_results", {})[str(step["step_id"])]
            )
            for step in blueprint["steps"]
            if str(step["step_id"]) in state.get("step_results", {})
        ]
        status = cast(
            Literal["SUCCEEDED", "PARTIAL", "FAILED"],
            state.get("final_status", "FAILED"),
        )
        return ExecutionRunResult(
            run_id=state["run_id"],
            thread_id=state["thread_id"],
            blueprint_id=str(blueprint["blueprint_id"]),
            status=status,
            step_results=ordered,
            outputs=state.get("outputs", {}),
            placeholder_step_ids=state.get("placeholder_step_ids", []),
            failed_step_id=state.get("failed_step_id"),
            failure_code=state.get("current_failure_code"),
            business_validated=(
                status == "SUCCEEDED"
                and any(item.business_validated for item in ordered)
            ),
            input_tokens=state.get("input_tokens", 0),
            output_tokens=state.get("output_tokens", 0),
            total_tokens=state.get("input_tokens", 0)
            + state.get("output_tokens", 0),
        )

    def _current_step(self, state: ExecutionGraphState) -> dict[str, Any]:
        step_id = state.get("current_step_id")
        for step in state["blueprint"]["steps"]:
            if step["step_id"] == step_id:
                return cast(dict[str, Any], step)
        raise RuntimeError(f"current Blueprint step not found: {step_id}")

    def _record(
        self,
        state: ExecutionGraphState,
        step: dict[str, Any],
        *,
        phase: Literal["STARTED", "SUCCEEDED", "FAILED", "WAITING_HUMAN"],
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        validation_status: Literal["NOT_RUN", "PASS", "FAIL", "NEEDS_REVIEW"],
        business_validated: bool,
        decision_summary: str,
        failure_code: str | None = None,
        artifact_refs: list[str] | None = None,
        duration_ns: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        asset_ref = cast(str | None, step.get("asset_ref"))
        details = self.resolver.resolve(asset_ref) if asset_ref else None
        validated_asset_refs: list[str] = []
        if business_validated:
            if asset_ref:
                validated_asset_refs.append(asset_ref)
            for dependency_id in step.get("depends_on", []):
                for candidate in state["blueprint"]["steps"]:
                    if (
                        candidate["step_id"] == dependency_id
                        and candidate.get("asset_ref")
                    ):
                        validated_asset_refs.append(str(candidate["asset_ref"]))
        operation = (
            str(details.contract["operation"])
            if details is not None
            else "system2.placeholder"
        )
        record = RuntimeExecutionStepRecord(
            step_id=str(step["step_id"]),
            subgoal_id=str(step["subgoal_id"]),
            phase=phase,
            executor_kind=cast(Any, step["step_type"]),
            operation_key=operation,
            goal=str(step["goal"]),
            asset_ref=asset_ref,
            validator_ref=(
                details.call.required_validator_ref if details is not None else None
            ),
            validated_asset_refs=list(dict.fromkeys(validated_asset_refs)),
            input_refs=list(step.get("input_bindings", {}).values()),
            output_artifact_refs=artifact_refs or [],
            input_safe_summary=_safe_summary(input_payload),
            output_safe_summary=_safe_summary(output_payload),
            validation_status=validation_status,
            business_validated=business_validated,
            failure_code=failure_code,
            side_effect=cast(Any, step.get("side_effect", SideEffect.NONE.value)),
            idempotency_key_ref=cast(str | None, step.get("idempotency_key")),
            duration_ns=duration_ns,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            decision_summary=decision_summary,
        )
        self.ledger.record_step(state["run_id"], record)
        self.trace.execution_step(run_id=state["run_id"], record=record)

    def _write_artifact(
        self,
        run_id: str,
        step_id: str,
        payload: dict[str, Any],
    ) -> str:
        root = self.project_root / "data/runtime/artifacts" / run_id
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{step_id}.json"
        path.write_text(
            json.dumps(_safe_summary(payload), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return f"artifact://{run_id}/{step_id}?path={path}"


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


def _resume_seed(
    previous: ExecutionRunResult | None,
) -> dict[str, Any]:
    """Seed only completed work; the waiting HUMAN step remains pending."""
    if previous is None:
        return {}
    statuses: dict[str, str] = {}
    results: dict[str, dict[str, Any]] = {}
    outputs: dict[str, dict[str, Any]] = {}
    placeholder_step_ids: list[str] = []
    for item in previous.step_results:
        if item.placeholder_reason == "WAITING_HUMAN":
            continue
        if item.status not in {"SUCCEEDED", "PLACEHOLDER"}:
            continue
        statuses[item.step_id] = "SUCCEEDED"
        results[item.step_id] = item.model_dump(mode="json")
        if item.step_id in previous.outputs:
            outputs[item.step_id] = previous.outputs[item.step_id]
        if item.status == "PLACEHOLDER":
            placeholder_step_ids.append(item.step_id)
    return {
        "step_statuses": statuses,
        "step_results": results,
        "outputs": outputs,
        "placeholder_step_ids": placeholder_step_ids,
        "input_tokens": previous.input_tokens,
        "output_tokens": previous.output_tokens,
    }


def _is_lightweight_state_step(step: dict[str, Any]) -> bool:
    """Validate the persisted step before applying the zero-token fast path."""
    try:
        return is_lightweight_gap_step(BlueprintStep.model_validate(step))
    except Exception:
        return False


def _lightweight_output(
    step: dict[str, Any],
    state: ExecutionGraphState,
) -> dict[str, Any]:
    """Return a small deterministic result for a bounded normalization gap."""
    reason_code = str(step["reason_code"])
    context = state.get("task_context", {})
    facts: dict[str, Any] = {
        "reason_code": reason_code,
        "normalized": True,
        "source": "fixed_meta_executor",
    }
    if reason_code == "LIGHTWEIGHT_INFO_CONFIRMATION":
        facts["confirmed_from_context"] = bool(context.get("entities"))
    elif reason_code == "LIGHTWEIGHT_FIELD_DEFAULT":
        facts["default_applied"] = True
    elif reason_code == "LIGHTWEIGHT_ENUM_COERCION":
        facts["enum_coerced"] = True
    return {
        "status": "RESOLVED",
        "summary": "轻量格式或信息缺口已由固定执行器完成。",
        "facts": facts,
        "evidence_refs": [],
    }
