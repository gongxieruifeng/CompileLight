"""Final safety guard for control-plane structured output."""

from __future__ import annotations

from reduce_token_agent.domain.blueprint import Destination, PipelineMode
from reduce_token_agent.domain.control import GuardResult, RoutingDecision


class OutputGuard:
    """Reject inconsistent routing or any false execution-success claim."""

    def validate(
        self,
        *,
        routing: RoutingDecision,
        has_compiled_blueprint: bool,
        has_langgraph_handoff: bool,
        has_system2_handoff: bool,
        receipt_statuses: list[str],
    ) -> GuardResult:
        codes: list[str] = []
        expected = {
            PipelineMode.REUSE: [{Destination.LANGGRAPH_EXECUTION}],
            PipelineMode.HYBRID: [
                {
                    Destination.LANGGRAPH_EXECUTION,
                    Destination.SYSTEM2,
                }
            ],
            # A low-coverage NEW plan may still execute the deterministic
            # assets it found, while the overall route remains NEW.
            PipelineMode.NEW: [
                {Destination.SYSTEM2},
                {
                    Destination.LANGGRAPH_EXECUTION,
                    Destination.SYSTEM2,
                },
            ],
            PipelineMode.CLARIFY: [{Destination.HUMAN}],
            PipelineMode.REJECT: [{Destination.SAFE_STOP}],
        }[routing.mode]
        if set(routing.destinations) not in expected:
            codes.append("DESTINATION_MODE_MISMATCH")
        if routing.mode in {PipelineMode.REUSE, PipelineMode.HYBRID} and not (
            has_compiled_blueprint and has_langgraph_handoff
        ):
            codes.append("COMPILED_HANDOFF_REQUIRED")
        if (
            routing.mode is PipelineMode.NEW
            and Destination.LANGGRAPH_EXECUTION in routing.destinations
            and not (has_compiled_blueprint and has_langgraph_handoff)
        ):
            codes.append("COMPILED_HANDOFF_REQUIRED")
        if routing.mode in {PipelineMode.HYBRID, PipelineMode.NEW} and not has_system2_handoff:
            codes.append("SYSTEM2_HANDOFF_REQUIRED")
        if routing.mode in {PipelineMode.CLARIFY, PipelineMode.REJECT} and (
            has_langgraph_handoff or has_system2_handoff
        ):
            codes.append("SAFE_MODE_HAS_EXECUTION_HANDOFF")
        allowed_receipt_statuses = {
            "NOT_IMPLEMENTED",
            "SUCCEEDED",
            "PARTIAL",
            "FAILED",
        }
        if any(status not in allowed_receipt_statuses for status in receipt_statuses):
            codes.append("EXECUTION_RECEIPT_INVALID")
        if codes:
            return GuardResult(passed=False, codes=codes)
        return GuardResult(passed=True, codes=["STRUCTURED_OUTPUT_SAFE"])
