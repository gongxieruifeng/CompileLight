"""Minimal checkpoint state for the fixed execution graph."""

from __future__ import annotations

from typing import Any, TypedDict


class ExecutionGraphState(TypedDict, total=False):
    run_id: str
    thread_id: str
    blueprint: dict[str, Any]
    task_context: dict[str, Any]
    step_statuses: dict[str, str]
    step_results: dict[str, dict[str, Any]]
    outputs: dict[str, dict[str, Any]]
    system2_outputs: dict[str, dict[str, Any]]
    system2_step_tokens: dict[str, tuple[int, int]]
    system2_partial_step_ids: list[str]
    input_tokens: int
    output_tokens: int
    current_step_id: str | None
    current_input: dict[str, Any]
    current_input_source: str
    current_output: dict[str, Any]
    current_validation_status: str
    current_business_validated: bool
    current_failure_code: str | None
    current_input_tokens: int
    current_output_tokens: int
    _started_ns: int
    placeholder_step_ids: list[str]
    failed_step_id: str | None
    final_status: str
