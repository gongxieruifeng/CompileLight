"""Port for the fixed LangGraph meta-executor."""

from __future__ import annotations

from typing import Protocol

from reduce_token_agent.domain.blueprint import CompiledBlueprint
from reduce_token_agent.domain.control import HandoffReceipt, LangGraphHandoff
from reduce_token_agent.domain.runtime import ExecutionRunResult
from reduce_token_agent.domain.task import TaskContext
from reduce_token_agent.system2.models import System2Resolution


class LangGraphExecutionPort(Protocol):
    def submit(
        self,
        handoff: LangGraphHandoff,
        blueprint: CompiledBlueprint,
        context: TaskContext,
        system2_resolution: System2Resolution | None = None,
        *,
        resume: bool = False,
        previous_execution: ExecutionRunResult | None = None,
    ) -> HandoffReceipt: ...


class LangGraphPlaceholder:
    """Accept no work and never claim that execution happened."""

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
        return HandoffReceipt(
            target="LANGGRAPH_EXECUTION",
            status="NOT_IMPLEMENTED",
            accepted=False,
            message=(
                f"Blueprint {handoff.compiled_blueprint_id} passed control-plane gates; "
                "fixed LangGraph meta-executor is outside this delivery."
            ),
        )
