"""Port for bounded System2 gap resolution."""

from __future__ import annotations

from typing import Protocol

from reduce_token_agent.domain.blueprint import BlueprintStep
from reduce_token_agent.domain.control import HandoffReceipt, System2Handoff
from reduce_token_agent.domain.task import TaskContext
from reduce_token_agent.system2.models import System2Resolution


class System2Port(Protocol):
    def resolve(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        observed_outputs: dict[str, dict[str, object]] | None = None,
    ) -> System2Resolution | None: ...

    def submit(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        observed_outputs: dict[str, dict[str, object]] | None = None,
        resume: bool = False,
    ) -> HandoffReceipt: ...

    def resume(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        human_answers: dict[str, dict[str, object]],
        prior_outputs: dict[str, dict[str, object]] | None = None,
    ) -> System2Resolution: ...


class System2Placeholder:
    """Accept no work and never bypass compile or policy failures."""

    def resolve(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        observed_outputs: dict[str, dict[str, object]] | None = None,
    ) -> None:
        return None

    def submit(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        observed_outputs: dict[str, dict[str, object]] | None = None,
        resume: bool = False,
    ) -> HandoffReceipt:
        return HandoffReceipt(
            target="SYSTEM2",
            status="NOT_IMPLEMENTED",
            accepted=False,
            message=(
                f"Task {handoff.task_id} requires bounded gap handling; "
                "System2 is outside this delivery."
            ),
        )

    def resume(
        self,
        handoff: System2Handoff,
        steps: list[BlueprintStep],
        context: TaskContext,
        *,
        human_answers: dict[str, dict[str, object]],
        prior_outputs: dict[str, dict[str, object]] | None = None,
    ) -> System2Resolution:
        raise RuntimeError("System2 placeholder cannot resume HUMAN work")
