"""Constrained Blueprint proposal; model output never becomes executable directly."""

from __future__ import annotations

import re
import secrets
from typing import Literal

from reduce_token_agent.control_plane.errors import ControlStageError
from reduce_token_agent.domain.blueprint import (
    BlueprintBudget,
    BlueprintDraft,
    BlueprintProposal,
    BlueprintStep,
    CompileError,
    RegistryViewRef,
    StepType,
)
from reduce_token_agent.domain.control import RerankResult
from reduce_token_agent.domain.task import SadAlignedSubgoal, SadAlignment, TaskContext
from reduce_token_agent.llm.base import StructuredModel, StructuredUsage
from reduce_token_agent.llm.ollama_client import StructuredModelError
from reduce_token_agent.registry.models import AssetKind, SideEffect


class PlanProposer:
    """Ask the model to select only frozen candidates and allowed step types."""

    def __init__(self, model: StructuredModel, *, budget: BlueprintBudget) -> None:
        self.model = model
        self.budget = budget

    def propose(
        self,
        *,
        context: TaskContext,
        alignment: SadAlignment,
        reranked: RerankResult,
        registry_view: RegistryViewRef,
        planning_priors: list[dict[str, object]],
        repair_errors: list[CompileError] | None = None,
    ) -> tuple[BlueprintProposal, StructuredUsage]:
        """Produce an untrusted structured proposal and attach authoritative fields."""
        if not reranked.allowed_asset_refs:
            if reranked.hard_failure_codes:
                raise ControlStageError(
                    "POLICY_DENIED",
                    "all retrieved assets were rejected by hard policy gates: "
                    + ", ".join(reranked.hard_failure_codes),
                    repairable=False,
                )
            # No candidate was retrieved at all. Keep the gap explicit and
            # bounded so routing can hand it to System2 without inventing an
            # asset-bound VALIDATOR/TOOL step.
            required_subgoals = _unique_required_subgoals(alignment)
            human_subgoal_id = _required_human_subgoal_id(context, alignment)
            steps = [
                BlueprintStep.model_validate({
                    "step_id": f"step_gap_{index}",
                    "subgoal_id": item.subgoal_id,
                    "step_type": (
                        StepType.HUMAN
                        if item.subgoal_id == human_subgoal_id
                        else StepType.REASON
                    ),
                    "goal": item.goal,
                    "expected_output_schema": {},
                    "max_iterations": (
                        None
                        if item.subgoal_id == human_subgoal_id
                        else 1
                    ),
                    "human_gate": item.subgoal_id == human_subgoal_id,
                    "side_effect": (
                        SideEffect.HUMAN_HANDOFF
                        if item.subgoal_id == human_subgoal_id
                        else SideEffect.NONE
                    ),
                    "reason_code": (
                        "HUMAN_CONFIRMATION_REQUIRED"
                        if item.subgoal_id == human_subgoal_id
                        else "NO_REUSABLE_ASSET"
                    ),
                })
                for index, item in enumerate(required_subgoals, start=1)
            ]
            if not steps:
                raise ControlStageError(
                    "PLAN_SCHEMA_INVALID",
                    "no required subgoals available for a bounded gap plan",
                    repairable=False,
                )
            return (
                BlueprintProposal(
                    blueprint_id="bp_" + secrets.token_hex(8),
                    task_id=context.task_id,
                    registry_view=registry_view,
                    required_subgoal_ids=[
                        item.subgoal_id
                        for item in required_subgoals
                    ],
                    steps=steps,
                    budget=self.budget,
                    repair_attempt=0,
                    proposal_codes=["NO_REUSABLE_ASSET", "BOUNDED_NEW_GAP"],
                ),
                StructuredUsage(
                    stage="plan_propose",
                    model="control-code",
                    input_tokens=0,
                    output_tokens=0,
                    total_duration_ns=0,
                    estimated=True,
                    attempts=0,
                ),
            )
        repair_attempt: Literal[0, 1] = 1 if repair_errors else 0
        candidates = [
            {
                "subgoal_id": candidate_set.subgoal.subgoal_id,
                "primary": [
                    {
                        "asset_ref": item.candidate.asset_ref,
                        "kind": item.candidate.kind.value,
                        "contract": item.contract.model_dump(mode="json"),
                    }
                    for item in candidate_set.primary
                ],
                "graph_closure": [
                    {
                        "asset_ref": item.candidate.asset_ref,
                        "kind": item.candidate.kind.value,
                        "contract": item.contract.model_dump(mode="json"),
                    }
                    for item in candidate_set.graph_closure
                ],
            }
            for candidate_set in reranked.candidate_sets
        ]
        try:
            result = self.model.generate_structured(
                stage="plan_repair" if repair_attempt else "plan_propose",
                system_prompt=(
                    "你只能提议 Blueprint JSON，不能批准或执行。资产步骤只能从"
                    "allowed_asset_refs 选择精确版本；不得发明工具。每个 FSM/TOOL/"
                    "ADAPTER/VALIDATOR 步骤都必须逐字填写 asset_ref；未覆盖局部用有界 "
                    "REASON、EXTRACT 或 HUMAN。仅对简单格式归一、字段默认、枚举转换"
                    "或上下文内信息确认使用 LIGHTWEIGHT_FORMAT_NORMALIZATION、"
                    "LIGHTWEIGHT_FIELD_DEFAULT、LIGHTWEIGHT_ENUM_COERCION 或 "
                    "LIGHTWEIGHT_INFO_CONFIRMATION 原因码；这些步骤不得带副作用或"
                    "人工门禁。不要输出思维链，只输出 proposal_codes。"
                ),
                user_payload={
                    "task": {
                        "task_id": context.task_id,
                        "entities": context.entities,
                        "acceptance_criteria": context.acceptance_criteria,
                        "scopes": context.scopes,
                        "risk_level": context.risk_level.value,
                    },
                    "aligned_subgoals": [
                        item.model_dump(mode="json") for item in alignment.aligned_subgoals
                    ],
                    "candidates": candidates,
                    "allowed_asset_refs": reranked.allowed_asset_refs,
                    "allowed_step_types": [item.value for item in StepType],
                    "registry_index_id": registry_view.index_id,
                    "asset_set_digest": registry_view.asset_set_digest,
                    "budget": self.budget.model_dump(mode="json"),
                    "planning_priors": planning_priors,
                    "repair_errors": (
                        [
                            {
                                "code": error.code.value,
                                "step_id": error.step_id,
                                "asset_ref": error.asset_ref,
                            }
                            for error in repair_errors
                        ]
                        if repair_errors
                        else []
                    ),
                    "repair_attempt": repair_attempt,
                },
                output_model=BlueprintDraft,
            )
        except StructuredModelError as exc:
            if exc.code != "MODEL_OUTPUT_INVALID" or not any(
                marker in str(exc)
                for marker in (
                    "requires asset_ref",
                    "cannot bind Registry asset_ref",
                )
            ):
                raise
            # The JSON shape is valid enough to identify the intended step
            # kinds, but the model produced an invalid asset binding (for
            # example EXTRACT with a Registry asset_ref). Select only the
            # frozen candidates deterministically; never invent a reference.
            return self._deterministic_repair(
                context=context,
                alignment=alignment,
                reranked=reranked,
                registry_view=registry_view,
            )
        draft = result.value
        proposal_codes = list(draft.proposal_codes)
        required_human_subgoal_id = _required_human_subgoal_id(context, alignment)
        if required_human_subgoal_id is not None and not any(
            step.step_type is StepType.HUMAN
            and step.subgoal_id == required_human_subgoal_id
            and step.human_gate
            and step.side_effect is SideEffect.HUMAN_HANDOFF
            for step in draft.steps
        ):
            return self._deterministic_repair(
                context=context,
                alignment=alignment,
                reranked=reranked,
                registry_view=registry_view,
            )
        if (
            draft.registry_index_id != registry_view.index_id
            or draft.asset_set_digest != registry_view.asset_set_digest
        ):
            # These fields are echoed by the model only for auditability. The
            # authoritative frozen view is attached below by code, so a copy
            # error cannot mutate the snapshot and need not fail the run.
            proposal_codes.append("AUTHORITATIVE_SNAPSHOT_REBOUND")
        referenced = {step.asset_ref for step in draft.steps if step.asset_ref}
        uncovered_ids = {
            item.subgoal_id
            for item in _unique_required_subgoals(alignment)
            if item.uncovered
        }
        if (
            not referenced.issubset(set(reranked.allowed_asset_refs))
            or any(
                step.subgoal_id in uncovered_ids and step.asset_ref is not None
                for step in draft.steps
            )
            or _left_reusable_primary_on_table(
                draft=draft,
                alignment=alignment,
                reranked=reranked,
            )
        ):
            return self._deterministic_repair(
                context=context,
                alignment=alignment,
                reranked=reranked,
                registry_view=registry_view,
            )
        return (
            BlueprintProposal(
                blueprint_id="bp_" + secrets.token_hex(8),
                task_id=context.task_id,
                registry_view=registry_view,
                required_subgoal_ids=[
                    item.subgoal_id
                    for item in _unique_required_subgoals(alignment)
                ],
                steps=draft.steps,
                budget=self.budget,
                repair_attempt=repair_attempt,
                proposal_codes=list(dict.fromkeys(proposal_codes)),
            ),
            result.usage,
        )

    def _deterministic_repair(
        self,
        *,
        context: TaskContext,
        alignment: SadAlignment,
        reranked: RerankResult,
        registry_view: RegistryViewRef,
    ) -> tuple[BlueprintProposal, StructuredUsage]:
        steps: list[BlueprintStep] = []
        human_subgoal_id = _required_human_subgoal_id(context, alignment)
        human_step_id: str | None = None
        previous_terminal_id: str | None = None
        for subgoal_index, subgoal in enumerate(
            _unique_required_subgoals(alignment),
            start=1,
        ):
            inherited_dependencies = (
                [human_step_id]
                if human_step_id is not None
                else []
            )
            if subgoal.subgoal_id == human_subgoal_id:
                step_id = f"step_human_{subgoal_index}"
                steps.append(
                    BlueprintStep(
                        step_id=step_id,
                        subgoal_id=subgoal.subgoal_id,
                        step_type=StepType.HUMAN,
                        goal=subgoal.goal,
                        depends_on=(
                            [previous_terminal_id]
                            if previous_terminal_id is not None
                            else []
                        ),
                        side_effect=SideEffect.HUMAN_HANDOFF,
                        human_gate=True,
                        reason_code="HUMAN_CONFIRMATION_REQUIRED",
                    )
                )
                human_step_id = step_id
                previous_terminal_id = step_id
                continue
            candidate_set = next(
                (
                    item
                    for item in reranked.candidate_sets
                    if item.subgoal.subgoal_id == subgoal.subgoal_id
                ),
                None,
            )
            primary = (
                next(
                    (
                        item
                        for item in candidate_set.primary
                        if item.candidate.kind
                        in {AssetKind.FSM_SHARD, AssetKind.PRIMITIVE_TOOL}
                    ),
                    None,
                )
                if candidate_set
                else None
            )
            if subgoal.uncovered or primary is None:
                steps.append(
                    BlueprintStep(
                        step_id=f"step_gap_{subgoal_index}",
                        subgoal_id=subgoal.subgoal_id,
                        step_type=StepType.REASON,
                        goal=subgoal.goal,
                        depends_on=inherited_dependencies,
                        max_iterations=1,
                        reason_code="NO_REUSABLE_PRIMARY",
                    )
                )
                previous_terminal_id = f"step_gap_{subgoal_index}"
                continue
            step_type = (
                StepType.FSM
                if primary.candidate.kind is AssetKind.FSM_SHARD
                else StepType.TOOL
            )
            primary_id = f"step_reuse_{subgoal_index}"
            steps.append(
                BlueprintStep(
                    step_id=primary_id,
                    subgoal_id=subgoal.subgoal_id,
                    step_type=step_type,
                    goal=subgoal.goal,
                    asset_ref=primary.candidate.asset_ref,
                    depends_on=inherited_dependencies,
                    required_scopes=primary.contract.required_scopes,
                    side_effect=SideEffect(primary.contract.side_effect),
                    reason_code="DETERMINISTIC_FORMAT_REPAIR",
                )
            )
            if candidate_set:
                for validator_index, validator in enumerate(
                    (
                        item
                        for item in candidate_set.graph_closure
                        if (
                            item.candidate.kind is AssetKind.VALIDATOR
                            and item.candidate.provenance.parent_ref
                            == primary.candidate.asset_ref
                        )
                    ),
                    start=1,
                ):
                    steps.append(
                        BlueprintStep(
                            step_id=f"step_validator_{subgoal_index}_{validator_index}",
                            subgoal_id=subgoal.subgoal_id,
                            step_type=StepType.VALIDATOR,
                            goal=f"验证：{subgoal.goal}",
                            asset_ref=validator.candidate.asset_ref,
                            depends_on=[primary_id],
                            required_scopes=validator.contract.required_scopes,
                            side_effect=SideEffect(validator.contract.side_effect),
                            reason_code="REQUIRED_VALIDATOR",
                        )
                    )
            previous_terminal_id = (
                steps[-1].step_id
                if steps[-1].subgoal_id == subgoal.subgoal_id
                else primary_id
            )
        return (
            BlueprintProposal(
                blueprint_id="bp_" + secrets.token_hex(8),
                task_id=context.task_id,
                registry_view=registry_view,
                required_subgoal_ids=[
                    item.subgoal_id
                    for item in _unique_required_subgoals(alignment)
                ],
                steps=steps,
                budget=self.budget,
                repair_attempt=1,
                proposal_codes=["DETERMINISTIC_FORMAT_REPAIR"],
            ),
            StructuredUsage(
                stage="plan_repair",
                model="control-code",
                input_tokens=0,
                output_tokens=0,
                total_duration_ns=0,
                estimated=True,
                attempts=1,
            ),
        )


def _unique_required_subgoals(
    alignment: SadAlignment,
) -> list[SadAlignedSubgoal]:
    unique: dict[str, SadAlignedSubgoal] = {}
    for item in alignment.aligned_subgoals:
        if item.required and item.subgoal_id not in unique:
            unique[item.subgoal_id] = item
    return list(unique.values())


_HUMAN_GATE_PATTERNS = (
    re.compile(r"(?:必须|需要|要求|等待|由|让).{0,12}(?:人工|用户|本人|我|指定人员).{0,12}(?:确认|批准|审批|决定)"),
    re.compile(r"(?:人工|用户|本人|我|指定人员).{0,12}(?:确认|批准|审批|决定)"),
    re.compile(r"未经.{0,16}(?:确认|批准).{0,16}(?:不得|禁止|不能)"),
    re.compile(r"确认请求|等待.{0,12}确认"),
    re.compile(
        r"(?:must|requires?|wait(?:ing)?).{0,24}(?:human|user|my).{0,24}"
        r"(?:confirm|approval|decision)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:do not|must not|cannot).{0,24}(?:until|without).{0,24}"
        r"(?:confirm|approval)",
        re.IGNORECASE,
    ),
)
_HUMAN_GATE_NEGATION = re.compile(
    r"(?:无需|不需要|不要|禁止).{0,8}(?:人工|用户).{0,8}(?:确认|批准|审批)"
)


def _required_human_subgoal_id(
    context: TaskContext,
    alignment: SadAlignment,
) -> str | None:
    """Choose one authoritative pause point from explicit user requirements."""
    required = _unique_required_subgoals(alignment)
    for item in required:
        local_text = " ".join(
            [
                item.goal,
                item.expected_state,
                *item.acceptance_criteria,
            ]
        )
        if _HUMAN_GATE_NEGATION.search(local_text):
            continue
        if any(pattern.search(local_text) for pattern in _HUMAN_GATE_PATTERNS):
            return item.subgoal_id

    task_text = " ".join([context.query, *context.acceptance_criteria])
    if _HUMAN_GATE_NEGATION.search(task_text):
        return None
    if any(pattern.search(task_text) for pattern in _HUMAN_GATE_PATTERNS):
        # If the model failed to isolate the gate, use the final required
        # subgoal as the safest hard pause before completion.
        return required[-1].subgoal_id if required else None
    return None


def _left_reusable_primary_on_table(
    *,
    draft: BlueprintDraft,
    alignment: SadAlignment,
    reranked: RerankResult,
) -> bool:
    """Repair model proposals that demote available deterministic assets to REASON.

    The model is allowed to preserve true gaps, but a required, covered subgoal
    with an eligible FSM/TOOL primary should not become a pure reasoning step.
    This is the local PoC's main token-saving invariant: seen capabilities must
    be reused unless the SAD boundary explicitly marks the subgoal uncovered.
    """

    deterministic_step_types = {StepType.FSM, StepType.TOOL}
    draft_primary_by_subgoal = {
        step.subgoal_id
        for step in draft.steps
        if step.step_type in deterministic_step_types and step.asset_ref
    }
    candidate_sets = {
        candidate_set.subgoal.subgoal_id: candidate_set
        for candidate_set in reranked.candidate_sets
    }
    for subgoal in _unique_required_subgoals(alignment):
        if subgoal.uncovered or subgoal.subgoal_id in draft_primary_by_subgoal:
            continue
        candidate_set = candidate_sets.get(subgoal.subgoal_id)
        if candidate_set is None:
            continue
        if any(
            item.candidate.kind in {AssetKind.FSM_SHARD, AssetKind.PRIMITIVE_TOOL}
            for item in candidate_set.primary
        ):
            return True
    return False
