"""Deterministic single-ready-step scheduler."""

from __future__ import annotations

from typing import Any


def select_ready_step(
    steps: list[dict[str, Any]],
    statuses: dict[str, str],
) -> str | None:
    """Return the first pending step whose dependencies all succeeded."""
    for step in steps:
        step_id = str(step["step_id"])
        if statuses.get(step_id) != "PENDING":
            continue
        dependencies = [str(item) for item in step.get("depends_on", [])]
        if all(statuses.get(dependency) == "SUCCEEDED" for dependency in dependencies):
            return step_id
    return None


def has_blocked_pending_steps(
    steps: list[dict[str, Any]],
    statuses: dict[str, str],
) -> bool:
    """A pending step is blocked when a dependency has failed."""
    for step in steps:
        if statuses.get(str(step["step_id"])) != "PENDING":
            continue
        if any(
            statuses.get(str(dependency)) == "FAILED"
            for dependency in step.get("depends_on", [])
        ):
            return True
    return False
