"""Typed results emitted by the fixed LangGraph execution plane."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionStepResult(StrictModel):
    step_id: str
    subgoal_id: str
    step_type: str
    status: Literal["SUCCEEDED", "FAILED", "PLACEHOLDER"]
    asset_ref: str | None
    input_source: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    validation_status: Literal["NOT_RUN", "PASS", "FAIL", "NEEDS_REVIEW"]
    business_validated: bool
    failure_code: str | None = None
    placeholder_reason: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ExecutionRunResult(StrictModel):
    run_id: str
    thread_id: str
    blueprint_id: str
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    step_results: list[ExecutionStepResult]
    outputs: dict[str, dict[str, Any]]
    placeholder_step_ids: list[str]
    failed_step_id: str | None = None
    failure_code: str | None = None
    business_validated: bool
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
