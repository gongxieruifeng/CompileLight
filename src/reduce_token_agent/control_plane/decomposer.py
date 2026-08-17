"""Pass-1 decomposition into the smallest useful set of business subgoals."""

from __future__ import annotations

from reduce_token_agent.control_plane.errors import ControlStageError
from reduce_token_agent.domain.task import DecompositionDraft, Subgoal, TaskContext
from reduce_token_agent.llm.base import StructuredModel, StructuredUsage

_INTERNAL_ACTION_TERMS = (
    "http request",
    "http 请求",
    "get 请求",
    "post 请求",
    "建立连接",
    "写入磁盘",
    "序列化 json",
    "调用 sdk",
)


def _bounded_join(prefix: str, values: list[str], *, max_length: int = 300) -> str:
    """Join labels without violating the Subgoal field contract."""

    joined = prefix + "；".join(values)
    if len(joined) <= max_length:
        return joined
    return joined[: max_length - 1].rstrip("；，、 ") + "…"


def _merge_overflow_subgoals(
    draft: DecompositionDraft,
    *,
    max_subgoals: int,
) -> DecompositionDraft:
    """Compact over-decomposition without dropping business requirements."""

    if len(draft.subgoals) <= max_subgoals:
        return draft

    retained = list(draft.subgoals[: max_subgoals - 1])
    overflow = draft.subgoals[max_subgoals - 1 :]
    existing_ids = {subgoal.subgoal_id for subgoal in retained}
    merged_id = "sg_overflow_merged"
    suffix = 2
    while merged_id in existing_ids:
        merged_id = f"sg_overflow_merged_{suffix}"
        suffix += 1

    criteria: list[str] = []
    for subgoal in overflow:
        for criterion in subgoal.acceptance_criteria:
            if criterion not in criteria:
                criteria.append(criterion)

    retained.append(
        Subgoal(
            subgoal_id=merged_id,
            goal=_bounded_join(
                "合并完成其余业务目标：",
                [subgoal.goal for subgoal in overflow],
            ),
            expected_state=_bounded_join(
                "其余目标均达到可验证状态：",
                [subgoal.expected_state for subgoal in overflow],
            ),
            acceptance_criteria=criteria[:8],
            required=any(subgoal.required for subgoal in overflow),
        )
    )
    return DecompositionDraft(
        subgoals=retained,
        decomposition_codes=[
            *draft.decomposition_codes[:11],
            "DETERMINISTIC_OVERFLOW_MERGE",
        ],
    )


class TaskDecomposer:
    def __init__(self, model: StructuredModel, *, max_subgoals: int) -> None:
        self.model = model
        self.max_subgoals = max_subgoals

    def decompose(
        self,
        context: TaskContext,
    ) -> tuple[DecompositionDraft, StructuredUsage]:
        result = self.model.generate_structured(
            stage="decompose",
            system_prompt=(
                "把任务拆成最少数量的高层业务子目标和期望中间状态。"
                "不要拆解到 HTTP、SDK、文件读写或某个 Tool 的内部动作。"
                "不得遗漏用户目标；每个子目标必须有可验证 expected_state。"
            ),
            user_payload={
                "task_id": context.task_id,
                "query": context.query,
                "entities": context.entities,
                "acceptance_criteria": context.acceptance_criteria,
                "max_subgoals": self.max_subgoals,
            },
            output_model=DecompositionDraft,
        )
        draft = _merge_overflow_subgoals(
            result.value,
            max_subgoals=self.max_subgoals,
        )
        for subgoal in draft.subgoals:
            normalized = f"{subgoal.goal} {subgoal.expected_state}".lower()
            if any(term in normalized for term in _INTERNAL_ACTION_TERMS):
                raise ControlStageError(
                    "OVER_DECOMPOSED_INTERNAL_ACTION",
                    f"{subgoal.subgoal_id} contains an internal transport action",
                )
        return draft, result.usage
