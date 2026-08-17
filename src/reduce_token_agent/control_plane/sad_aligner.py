"""Single feedback alignment against available Header and Contract summaries."""

from __future__ import annotations

from reduce_token_agent.control_plane.errors import ControlStageError
from reduce_token_agent.domain.control import ContractSummary
from reduce_token_agent.domain.task import (
    DecompositionDraft,
    SadAlignedSubgoal,
    SadAlignment,
    TaskContext,
)
from reduce_token_agent.llm.base import StructuredModel, StructuredUsage


class SadAligner:
    def __init__(self, model: StructuredModel) -> None:
        self.model = model

    def align_once(
        self,
        *,
        context: TaskContext,
        decomposition: DecompositionDraft,
        candidate_summaries: list[tuple[dict[str, object], ContractSummary]],
    ) -> tuple[SadAlignment, StructuredUsage]:
        allowed_refs = {
            summary.asset_ref for _, summary in candidate_summaries
        }
        result = self.model.generate_structured(
            stage="sad_align",
            system_prompt=(
                "执行且只执行一次 SAD 对齐。候选只表示可用能力边界，不得为了匹配"
                "候选而删除用户目标。一个 FSM 能完成整个子目标时不要拆其内部动作；"
                "两个独立 Contract 才保留两个边界。未覆盖目标必须显式保留。"
            ),
            user_payload={
                "task": {
                    "task_id": context.task_id,
                    "query": context.query,
                    "acceptance_criteria": context.acceptance_criteria,
                },
                "pass1_subgoals": [
                    subgoal.model_dump(mode="json")
                    for subgoal in decomposition.subgoals
                ],
                "candidate_headers_and_contract_summaries": [
                    {
                        "header": header,
                        "contract": summary.model_dump(mode="json"),
                    }
                    for header, summary in candidate_summaries
                ],
                "rules": {
                    "max_iterations": 1,
                    "allowed_asset_refs": sorted(allowed_refs),
                    "preserve_every_source_subgoal": True,
                },
            },
            output_model=SadAlignment,
        )
        alignment = result.value
        source_ids = {
            subgoal.subgoal_id for subgoal in decomposition.subgoals
        }
        represented = {
            source_id
            for aligned in alignment.aligned_subgoals
            for source_id in aligned.source_subgoal_ids
        }
        if not represented.issubset(source_ids):
            raise ControlStageError(
                "SAD_UNKNOWN_SOURCE",
                "SAD referenced a source subgoal that was not present in pass-1 decomposition",
                repairable=False,
            )
        # Models occasionally omit a low-salience acceptance criterion even
        # when the prompt explicitly requires preservation. Restore it as a
        # bounded unsupported boundary so the goal cannot disappear and later
        # routing can send it to System2/HUMAN.
        missing = [
            subgoal
            for subgoal in decomposition.subgoals
            if subgoal.subgoal_id not in represented
        ]
        if missing:
            alignment.aligned_subgoals.extend(
                SadAlignedSubgoal(
                    **subgoal.model_dump(),
                    source_subgoal_ids=[subgoal.subgoal_id],
                    covered_hint_refs=[],
                    uncovered=True,
                    alignment_code="UNSUPPORTED_PRESERVED",
                )
                for subgoal in missing
            )
            alignment.alignment_codes = list(
                dict.fromkeys(
                    [*alignment.alignment_codes, "SAD_MISSING_SOURCE_RESTORED"]
                )
            )
        hinted = {
            asset_ref
            for aligned in alignment.aligned_subgoals
            for asset_ref in aligned.covered_hint_refs
        }
        if not hinted.issubset(allowed_refs):
            raise ControlStageError(
                "SAD_ASSET_OUTSIDE_CANDIDATES",
                "SAD referenced an asset outside the supplied candidates",
            )
        return alignment, result.usage
