"""Schema for real runtime traces that can feed the asset-extraction SOP."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RuntimeTraceTask(StrictModel):
    """Reviewable, redacted task facts from one real control run."""

    task_id: str | None
    tenant_id: str | None
    principal_ref: str
    query_preview: str
    requested_at: str | None
    domains: list[str]
    data_classification: str | None
    risk_level: str | None
    entities: dict[str, Any]
    acceptance_criteria: list[str]


class RuntimeTraceEvent(StrictModel):
    """One ordered, structured event; never hidden chain-of-thought."""

    event_id: str
    sequence: int = Field(ge=1)
    stage: str
    event_type: str
    status: Literal["SUCCESS", "FAILED", "INFORMATIONAL"]
    created_at: datetime
    failure_codes: list[str]
    asset_refs: list[str]
    payload: dict[str, Any]


class RuntimeExecutionStepRecord(StrictModel):
    """Executor-facing trace contract analogous to a synthetic TraceStep."""

    step_id: str = Field(pattern=r"^step_[a-z0-9_]{2,60}$")
    subgoal_id: str = Field(pattern=r"^sg_[a-z0-9_]{2,60}$")
    attempt_number: int = Field(default=1, ge=1, le=10)
    phase: Literal["STARTED", "SUCCEEDED", "FAILED", "WAITING_HUMAN"]
    executor_kind: Literal[
        "FSM",
        "TOOL",
        "EXTRACT",
        "ADAPTER",
        "VALIDATOR",
        "REASON",
        "HUMAN",
    ]
    operation_key: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,120}$")
    goal: str = Field(min_length=6, max_length=300)
    asset_ref: str | None = None
    validator_ref: str | None = None
    validated_asset_refs: list[str] = Field(default_factory=list, max_length=20)
    input_refs: list[str] = Field(default_factory=list, max_length=20)
    output_artifact_refs: list[str] = Field(default_factory=list, max_length=20)
    input_safe_summary: dict[str, Any] = Field(default_factory=dict)
    output_safe_summary: dict[str, Any] = Field(default_factory=dict)
    validation_status: Literal["NOT_RUN", "PASS", "FAIL", "NEEDS_REVIEW"]
    business_validated: bool = False
    failure_code: str | None = None
    side_effect: Literal["NONE", "READ_ONLY", "LOCAL_WRITE", "HUMAN_HANDOFF"]
    idempotency_key_ref: str | None = None
    duration_ns: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    decision_summary: str = Field(
        min_length=6,
        max_length=300,
        description="Short evidence summary, never hidden chain-of-thought.",
    )


class RuntimeTracePlan(StrictModel):
    """Frozen proposal and deterministic compile evidence."""

    registry_view: dict[str, Any] | None
    proposal: dict[str, Any] | None
    compile_result: dict[str, Any] | None
    repair_attempts: int = Field(ge=0, le=1)


class RuntimeTraceOutcome(StrictModel):
    """Observable final control/execution state."""

    status: str
    mode: str | None
    destinations: list[str]
    failure_codes: list[str]
    failed_stage: str | None
    execution_status: Literal[
        "NOT_EXECUTED",
        "PARTIAL",
        "SUCCEEDED",
        "FAILED",
        "WAITING_HUMAN",
    ]
    business_validated: bool
    summary: str


class RuntimeExtractionEvidence(StrictModel):
    """Code-owned evidence projection consumed by a future extraction worker."""

    source_run_ids: list[str]
    domains: list[str]
    observed_asset_refs: list[str]
    validated_asset_refs: list[str]
    successful_stages: list[str]
    failed_stages: list[str]
    failure_codes: list[str]
    quality_flags: list[str]
    candidate_hint_status: Literal[
        "ELIGIBLE_VALIDATED_EXECUTION",
        "INELIGIBLE_CONTROL_ONLY",
        "INELIGIBLE_FAILED_RUN",
        "INELIGIBLE_UNVALIDATED_EXECUTION",
    ]


class RuntimeTraceProvenance(StrictModel):
    """Runtime and persistence provenance."""

    recorder: Literal["reduce_token_agent.control_trace_recorder"]
    recorded_at: datetime
    source_database: str
    event_count: int = Field(ge=0)


class RuntimeTraceGovernance(StrictModel):
    """Governance boundary compatible with the extraction SOP."""

    status: Literal["DRAFT"] = "DRAFT"
    synthetic: Literal[False] = False
    redacted: Literal[True] = True
    chain_of_thought_stored: Literal[False] = False
    schema_validated: Literal[True] = True
    human_review_required: Literal[True] = True
    eligible_for_candidate_extraction: bool
    automatic_activation_allowed: Literal[False] = False
    allowed_uses: list[str]
    prohibited_uses: list[str]


class RuntimeTraceEnvelope(StrictModel):
    """Immutable review projection for one real run."""

    schema_version: Literal["runtime-trace.v1"] = "runtime-trace.v1"
    trace_id: str = Field(pattern=r"^trace_run_[a-f0-9]{16}$")
    run_id: str = Field(pattern=r"^run_[a-f0-9]{16}$")
    task: RuntimeTraceTask
    timeline: list[RuntimeTraceEvent]
    plan: RuntimeTracePlan
    outcome: RuntimeTraceOutcome
    extraction_evidence: RuntimeExtractionEvidence
    provenance: RuntimeTraceProvenance
    governance: RuntimeTraceGovernance
