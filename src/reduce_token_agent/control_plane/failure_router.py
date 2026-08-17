"""Fixed execution failure policy included in LangGraph handoffs."""

from reduce_token_agent.domain.control import FailurePolicy


def fixed_failure_policy() -> FailurePolicy:
    """Return policy data; executors may not silently mutate the compiled graph."""
    return FailurePolicy(
        retryable_error_codes=["TIMEOUT", "TEMPORARY_UNAVAILABLE", "RATE_LIMITED"],
        business_rejection_action="EXPLICIT_BRANCH",
        irreversible_failure_action="COMPENSATE_OR_HUMAN",
        graph_mutation_allowed=False,
    )
