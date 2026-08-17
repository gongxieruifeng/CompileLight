"""Deterministic mode routing based on compiled subgoal coverage."""

from __future__ import annotations

from reduce_token_agent.domain.blueprint import (
    CompileErrorCode,
    CompileResult,
    Destination,
    PipelineMode,
    StepType,
    is_lightweight_gap_step,
)
from reduce_token_agent.domain.control import CoverageSummary, RoutingDecision

_DETERMINISTIC = {StepType.FSM, StepType.TOOL}
_GAP = {StepType.REASON, StepType.EXTRACT, StepType.HUMAN}
HYBRID_MIN_COVERAGE = 0.40
_POLICY_ERRORS = {
    CompileErrorCode.POLICY_DENIED,
    CompileErrorCode.SCOPE_DENIED,
    CompileErrorCode.RISK_GATE_REQUIRED,
    CompileErrorCode.TOOL_NOT_ALLOWED,
    CompileErrorCode.SNAPSHOT_MISMATCH,
}


class ModeRouter:
    """Route only from compiler facts; System2 never overrides policy failures."""

    def route(
        self,
        *,
        compile_result: CompileResult,
        required_subgoal_ids: list[str],
    ) -> RoutingDecision:
        required = set(required_subgoal_ids)
        total = len(required)
        if not compile_result.success:
            codes = {error.code for error in compile_result.errors}
            if codes & _POLICY_ERRORS:
                return RoutingDecision(
                    mode=PipelineMode.REJECT,
                    destinations=[Destination.SAFE_STOP],
                coverage=_coverage(total, 0, 0),
                    reason_codes=[
                        "HARD_POLICY_GATE_FAILED",
                        *sorted(code.value for code in codes),
                    ],
                )
            return RoutingDecision(
                mode=PipelineMode.NEW,
                destinations=[Destination.SYSTEM2],
                coverage=_coverage(total, 0, total),
                reason_codes=["COMPILE_UNRESOLVED_AFTER_REPAIR"],
            )

        assert compile_result.compiled_blueprint is not None
        deterministic = {
            step.subgoal_id
            for step in compile_result.compiled_blueprint.steps
            if step.step_type in _DETERMINISTIC
        }
        lightweight = {
            step.subgoal_id
            for step in compile_result.compiled_blueprint.steps
            if is_lightweight_gap_step(step)
        }
        gaps = {
            step.subgoal_id
            for step in compile_result.compiled_blueprint.steps
            if step.step_type in _GAP
        }
        lightweight_only = lightweight - deterministic
        effective = deterministic | lightweight
        deterministic_count = len(required & effective)
        lightweight_count = len(required & lightweight_only)
        gap_count = len((required - effective) & gaps)
        uncovered = total - deterministic_count - gap_count
        coverage = _coverage(
            total,
            deterministic_count,
            gap_count,
            uncovered,
            lightweight_count,
        )
        lightweight_reason = (
            ["LIGHTWEIGHT_GAPS_INLINED"] if lightweight_count else []
        )
        if total and deterministic_count == total:
            return RoutingDecision(
                mode=PipelineMode.REUSE,
                destinations=[Destination.LANGGRAPH_EXECUTION],
                coverage=coverage,
                reason_codes=[
                    "ALL_SUBGOALS_DETERMINISTICALLY_COVERED",
                    *lightweight_reason,
                ],
            )
        ratio = deterministic_count / total if total else 0.0
        if ratio > HYBRID_MIN_COVERAGE:
            return RoutingDecision(
                mode=PipelineMode.HYBRID,
                destinations=[
                    Destination.LANGGRAPH_EXECUTION,
                    Destination.SYSTEM2,
                ],
                coverage=coverage,
                reason_codes=[
                    "PARTIAL_DETERMINISTIC_COVERAGE",
                    "COVERAGE_ABOVE_HYBRID_THRESHOLD",
                    "GAPS_BOUNDED_TO_SYSTEM2",
                    *lightweight_reason,
                ],
            )
        if deterministic_count:
            return RoutingDecision(
                mode=PipelineMode.NEW,
                destinations=[
                    Destination.LANGGRAPH_EXECUTION,
                    Destination.SYSTEM2,
                ],
                coverage=coverage,
                reason_codes=[
                    "COVERAGE_BELOW_HYBRID_THRESHOLD",
                    "NEW_WITH_REUSE_ASSIST",
                    "GAPS_BOUNDED_TO_SYSTEM2",
                    *lightweight_reason,
                ],
            )
        return RoutingDecision(
            mode=PipelineMode.NEW,
            destinations=[Destination.SYSTEM2],
            coverage=coverage,
            reason_codes=[
                "NO_REUSABLE_PRIMARY_CAPABILITY",
                "COVERAGE_BELOW_HYBRID_THRESHOLD",
            ],
        )


def _coverage(
    total: int,
    deterministic: int,
    gaps: int,
    uncovered: int = 0,
    lightweight: int = 0,
) -> CoverageSummary:
    return CoverageSummary(
        required_subgoals=total,
        deterministic_covered=deterministic,
        lightweight_covered=lightweight,
        gap_covered=gaps,
        uncovered=uncovered,
        deterministic_ratio=(deterministic / total if total else 0.0),
    )
