"""Small application façade used by the future API and UI."""

from pathlib import Path
from typing import Any

from reduce_token_agent.application.container import build_control_plane
from reduce_token_agent.control_plane.config import ControlPlaneSettings
from reduce_token_agent.domain.control import ControlPlatformResult
from reduce_token_agent.domain.task import TaskRequest


class ApplicationFacade:
    """Expose one safe plan-and-execute use case."""

    def __init__(
        self,
        project_root: Path,
        *,
        settings: ControlPlaneSettings | None = None,
    ) -> None:
        self.control_plane = build_control_plane(project_root, settings=settings)

    def plan_task(self, request: TaskRequest) -> ControlPlatformResult:
        """Plan and execute one task through the local three-plane runtime."""
        return self.control_plane.plan(request)

    def resume_human(
        self,
        previous: ControlPlatformResult,
        *,
        human_answers: dict[str, dict[str, Any]],
    ) -> ControlPlatformResult:
        """Resume a PARTIAL task with authoritative typed human input."""
        return self.control_plane.resume_human(
            previous,
            human_answers=human_answers,
        )
