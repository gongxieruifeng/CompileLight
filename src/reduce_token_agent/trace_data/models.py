"""Pydantic contracts for validated synthetic traces."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects model-generated fields outside the contract."""

    model_config = ConfigDict(extra="forbid")


class AssetKind(StrEnum):
    """Candidate asset kinds supported by the future extraction pipeline."""

    TOOL = "TOOL"
    FSM = "FSM"
    EXTRACTOR = "EXTRACTOR"
    ADAPTER = "ADAPTER"
    VALIDATOR = "VALIDATOR"
    CONTRACT = "CONTRACT"
    POLICY = "POLICY"
    SKELETON = "SKELETON"
    HUMAN = "HUMAN"


class RiskLevel(StrEnum):
    """Coarse risk level used to route validation and human review."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExecutionMode(StrEnum):
    """Expected execution mode label for later experiments."""

    REUSE = "REUSE"
    HYBRID = "HYBRID"
    NEW = "NEW"
    CLARIFY = "CLARIFY"


class SideEffectClass(StrEnum):
    """Side-effect classification used by future gateways."""

    NONE = "NONE"
    READ_ONLY = "READ_ONLY"
    LOCAL_WRITE = "LOCAL_WRITE"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class ContractField(StrictModel):
    """One typed field at an operation boundary."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    data_type: Literal[
        "string",
        "integer",
        "number",
        "boolean",
        "date",
        "datetime",
        "object",
        "array",
    ]
    required: bool
    description: str = Field(min_length=4, max_length=180)


class ContextRecord(StrictModel):
    """A fully synthetic input record carried by the trace."""

    record_id: str = Field(pattern=r"^ctx_[a-z0-9_]{2,80}$")
    record_type: Literal[
        "contract_excerpt",
        "financial_table",
        "customer_dialogue",
        "internal_message",
        "policy_excerpt",
        "application_form",
        "transaction_summary",
        "structured_record",
    ]
    title: str = Field(min_length=3, max_length=120)
    content: str = Field(min_length=30, max_length=4000)
    data_classification: Literal["PUBLIC_SYNTHETIC", "INTERNAL_SYNTHETIC"]


class PolicyConstraint(StrictModel):
    """A constraint that later Compiler/Gateway/Validator logic can enforce."""

    constraint_id: str = Field(pattern=r"^constraint_[a-z0-9_]{2,80}$")
    rule: str = Field(min_length=8, max_length=240)
    enforcement_point: Literal["COMPILER", "GATEWAY", "VALIDATOR", "HUMAN"]
    violation_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{3,63}$")


class TraceArtifact(StrictModel):
    """A typed, synthetic artifact emitted by one trace step."""

    artifact_id: str = Field(pattern=r"^artifact_[a-z0-9_]{2,80}$")
    artifact_type: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    schema_name: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{2,80}$")
    summary: str = Field(min_length=8, max_length=300)
    payload: dict[str, Any]
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class ValidationEvidence(StrictModel):
    """A validation assertion and its evidence, without free-form reasoning."""

    check_id: str = Field(pattern=r"^check_[a-z0-9_]{2,80}$")
    rule: str = Field(min_length=6, max_length=200)
    status: Literal["PASS", "FAIL", "NEEDS_REVIEW"]
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    failure_code: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{3,63}$")


class TraceStep(StrictModel):
    """One observable execution step with explicit reusable boundaries."""

    step_id: str = Field(pattern=r"^step_[0-9]{2}$")
    ordinal: int = Field(ge=1, le=20)
    name: str = Field(min_length=3, max_length=100)
    stage: Literal[
        "INTAKE",
        "EXTRACT",
        "NORMALIZE",
        "DECIDE",
        "ACT",
        "VALIDATE",
        "REPORT",
        "HUMAN",
    ]
    executor_kind_hint: AssetKind
    operation_key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,80}$")
    goal: str = Field(min_length=8, max_length=240)
    reason_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{3,63}$")
    decision_summary: str = Field(
        min_length=8,
        max_length=240,
        description="Concise evidence-based decision summary, never hidden chain-of-thought.",
    )
    input_refs: list[str] = Field(min_length=1, max_length=12)
    action_name: str = Field(pattern=r"^[a-z][a-z0-9_.]{2,100}$")
    action_arguments: dict[str, Any]
    output_artifact: TraceArtifact
    validation: ValidationEvidence
    allowed_tools: list[str] = Field(default_factory=list, max_length=8)
    side_effect_class: SideEffectClass
    idempotency_key_template: str | None = Field(default=None, max_length=160)
    possible_failure_codes: list[str] = Field(min_length=1, max_length=8)
    on_success: str = Field(max_length=40)
    on_failure: str = Field(max_length=40)


class AssetCandidateHint(StrictModel):
    """A DRAFT extraction hint; it is not an executable or active asset."""

    candidate_id: str = Field(pattern=r"^candidate_[a-z0-9_]{2,100}$")
    kind: AssetKind
    proposed_name: str = Field(pattern=r"^[a-z][a-z0-9_.]{3,120}$")
    derived_from_step_ids: list[str] = Field(min_length=1, max_length=8)
    purpose: str = Field(min_length=8, max_length=240)
    input_contract: list[ContractField] = Field(min_length=1, max_length=12)
    output_contract: list[ContractField] = Field(min_length=1, max_length=12)
    preconditions: list[str] = Field(min_length=1, max_length=8)
    postconditions: list[str] = Field(min_length=1, max_length=8)
    invariants: list[str] = Field(min_length=1, max_length=8)
    failure_codes: list[str] = Field(min_length=1, max_length=8)
    side_effect_class: SideEffectClass
    deterministic: bool
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    extraction_notes: str = Field(min_length=8, max_length=300)
    status: Literal["DRAFT"]


class TaskDefinition(StrictModel):
    """Synthetic task request and labels."""

    title: str = Field(min_length=3, max_length=120)
    user_request: str = Field(min_length=15, max_length=600)
    objective: str = Field(min_length=10, max_length=300)
    expected_mode: ExecutionMode
    risk_level: RiskLevel
    primary_language: Literal["zh-CN"]


class TraceOutcome(StrictModel):
    """Observable final state of the synthetic trace."""

    status: Literal["SUCCEEDED", "PARTIAL", "WAITING_HUMAN", "REJECTED"]
    summary: str = Field(min_length=10, max_length=400)
    final_artifact_refs: list[str] = Field(min_length=1, max_length=12)
    unresolved_items: list[str] = Field(default_factory=list, max_length=8)
    validator_status: Literal["PASS", "FAIL", "NEEDS_REVIEW"]


class GeneratedTrace(StrictModel):
    """Model-generated portion of a synthetic trace."""

    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_]{5,120}$")
    domain: Literal[
        "loan_contract",
        "financial_report",
        "customer_service",
        "internal_communication",
        "risk_compliance",
        "corporate_operations",
    ]
    task_family: str = Field(pattern=r"^[a-z][a-z0-9_]{2,80}$")
    task: TaskDefinition
    context_records: list[ContextRecord] = Field(min_length=1, max_length=4)
    constraints: list[PolicyConstraint] = Field(min_length=1, max_length=8)
    steps: list[TraceStep] = Field(min_length=2, max_length=6)
    outcome: TraceOutcome
    candidate_assets: list[AssetCandidateHint] = Field(min_length=1, max_length=6)
    extraction_tags: list[str] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def validate_references(self) -> GeneratedTrace:
        """Check stable ordering and all cross-record candidate references."""
        step_ids = [step.step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step_id values must be unique")
        if [step.ordinal for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("step ordinals must be contiguous and start at 1")

        step_id_set = set(step_ids)
        artifact_ids = [step.output_artifact.artifact_id for step in self.steps]
        if len(artifact_ids) != len(set(artifact_ids)):
            raise ValueError("artifact_id values must be unique")
        if not set(self.outcome.final_artifact_refs).issubset(set(artifact_ids)):
            raise ValueError("outcome final_artifact_refs must reference emitted artifacts")

        for candidate in self.candidate_assets:
            if not set(candidate.derived_from_step_ids).issubset(step_id_set):
                raise ValueError("candidate references an unknown step")
            if candidate.status != "DRAFT":
                raise ValueError("synthetic candidates must remain DRAFT")

        if not any(
            candidate.kind is not AssetKind.HUMAN for candidate in self.candidate_assets
        ):
            raise ValueError("trace must expose at least one reusable candidate")
        return self


class GenerationProvenance(StrictModel):
    """Exact model-call metadata retained for reproducibility and cost analysis."""

    generator: Literal["ollama_structured_trace_collector"]
    model: str
    generated_at: datetime
    seed: int
    temperature: float
    num_ctx: int
    num_predict: int | None = None
    prompt_sha256: str
    response_sha256: str
    attempts: int
    prompt_tokens: int | None
    output_tokens: int | None
    total_duration_ns: int | None
    load_duration_ns: int | None
    prompt_eval_duration_ns: int | None
    eval_duration_ns: int | None


class TraceGovernance(StrictModel):
    """Fixed governance metadata added by code, never delegated to the model."""

    status: Literal["DRAFT"]
    synthetic: Literal[True]
    contains_real_pii: Literal[False]
    chain_of_thought_stored: Literal[False]
    schema_validated: Literal[True]
    human_review_required: Literal[True]
    eligible_for_candidate_extraction: Literal[True]
    allowed_uses: list[str]
    prohibited_uses: list[str]


class ScenarioRequirements(StrictModel):
    """Code-owned comparison between requested and generated capability boundaries."""

    required_operations: list[str]
    actual_operations: list[str]
    missing_operations: list[str]
    operation_coverage: float = Field(ge=0.0, le=1.0)
    required_candidate_kinds: list[AssetKind]
    actual_candidate_kinds: list[AssetKind]
    normalizations_applied: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    quality_score: float = Field(default=1.0, ge=0.0, le=1.0)


class SyntheticTraceEnvelope(StrictModel):
    """Persisted trace record with model output, provenance, and governance."""

    schema_version: Literal["synthetic-trace.v1"]
    trace_id: str = Field(pattern=r"^trace_syn_[a-z0-9_]{5,150}$")
    trace: GeneratedTrace
    scenario_requirements: ScenarioRequirements
    provenance: GenerationProvenance
    governance: TraceGovernance
