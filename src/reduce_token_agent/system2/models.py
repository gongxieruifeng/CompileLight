"""Typed contracts for bounded System2 decisions and verified artifacts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class System2Decision(StrictModel):
    """One observable action proposal; never a hidden reasoning transcript."""

    action: Literal["CALL_TOOL", "FINISH", "ASK_HUMAN", "ABORT"]
    summary: str = Field(min_length=6, max_length=300)
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list, max_length=12)
    tool_ref: str | None = Field(default=None, max_length=200)
    tool_input: dict[str, Any] = Field(default_factory=dict)
    failure_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def tool_action_requires_exact_ref(self) -> System2Decision:
        if self.action == "CALL_TOOL" and not self.tool_ref:
            raise ValueError("CALL_TOOL requires an exact tool_ref")
        if self.action != "CALL_TOOL" and self.tool_ref is not None:
            raise ValueError("tool_ref is only allowed for CALL_TOOL")
        return self


class System2Usage(StrictModel):
    stage: str
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_duration_ns: int = Field(ge=0)
    estimated: bool
    attempts: int = Field(ge=0)


class System2StepOutcome(StrictModel):
    step_id: str
    subgoal_id: str
    step_type: Literal["REASON", "EXTRACT", "HUMAN"]
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    action: Literal["CALL_TOOL", "FINISH", "ASK_HUMAN", "ABORT"]
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    validation_status: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    failure_code: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class System2Resolution(StrictModel):
    """Verified gap outputs exchanged with the fixed LangGraph executor."""

    run_id: str
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    step_outcomes: list[System2StepOutcome]
    outputs: dict[str, dict[str, Any]]
    usages: list[System2Usage]
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
