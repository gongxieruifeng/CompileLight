"""Typed control-plane failures used for deterministic routing."""

from __future__ import annotations


class ControlStageError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        repairable: bool = False,
    ) -> None:
        self.code = code
        self.repairable = repairable
        super().__init__(f"{code}: {message}")

