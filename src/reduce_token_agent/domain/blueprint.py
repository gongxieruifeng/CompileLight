"""Structured Blueprint proposal and deterministic compiler contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reduce_token_agent.domain.capability import VisibilityPolicy
from reduce_token_agent.registry.models import SideEffect


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StepType(StrEnum):
    FSM = "FSM"
    TOOL = "TOOL"
    EXTRACT = "EXTRACT"
    ADAPTER = "ADAPTER"
    VALIDATOR = "VALIDATOR"
    REASON = "REASON"
    HUMAN = "HUMAN"


LIGHTWEIGHT_GAP_REASON_CODES = frozenset(
    {
        "LIGHTWEIGHT_FORMAT_NORMALIZATION",
        "LIGHTWEIGHT_INFO_CONFIRMATION",
        "LIGHTWEIGHT_FIELD_DEFAULT",
        "LIGHTWEIGHT_ENUM_COERCION",
    }
)


class PipelineMode(StrEnum):
    REUSE = "REUSE"
    HYBRID = "HYBRID"
    NEW = "NEW"
    CLARIFY = "CLARIFY"
    REJECT = "REJECT"


class Destination(StrEnum):
    LANGGRAPH_EXECUTION = "LANGGRAPH_EXECUTION"
    SYSTEM2 = "SYSTEM2"
    HUMAN = "HUMAN"
    SAFE_STOP = "SAFE_STOP"


class RegistryViewRef(StrictModel):
    """Frozen Registry/Retrieval view for one planning run."""

    index_id: str = Field(min_length=8, max_length=120)
    asset_set_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    visibility_policy: VisibilityPolicy
    snapshot_id: str | None = None

    @model_validator(mode="after")
    def active_view_requires_snapshot(self) -> RegistryViewRef:
        if (
            self.visibility_policy is VisibilityPolicy.ACTIVE_SNAPSHOT
            and not self.snapshot_id
        ):
            raise ValueError("ACTIVE_SNAPSHOT view requires snapshot_id")
        if (
            self.visibility_policy is VisibilityPolicy.VALIDATED_DRAFT
            and self.snapshot_id is not None
        ):
            raise ValueError("VALIDATED_DRAFT cannot claim a snapshot_id")
        return self


class BlueprintBudget(StrictModel):
    max_steps: int = Field(default=12, ge=1, le=50)
    max_reason_steps: int = Field(default=6, ge=0, le=10)
    max_llm_calls: int = Field(default=6, ge=0, le=10)
    max_tool_calls: int = Field(default=8, ge=0, le=20)
    max_wall_time_seconds: int = Field(default=180, ge=1, le=3600)
    max_token_budget: int = Field(default=24000, ge=0, le=200000)


_ASSET_STEPS = {
    StepType.FSM,
    StepType.TOOL,
    StepType.ADAPTER,
    StepType.VALIDATOR,
}


class BlueprintStep(StrictModel):
    step_id: str = Field(pattern=r"^step_[a-z0-9_]{2,60}$")
    subgoal_id: str = Field(pattern=r"^sg_[a-z0-9_]{2,60}$")
    step_type: StepType
    goal: str = Field(min_length=6, max_length=300)
    asset_ref: str | None = Field(default=None, max_length=200)
    depends_on: list[str] = Field(default_factory=list, max_length=16)
    input_bindings: dict[str, str] = Field(default_factory=dict, max_length=20)
    expected_output_schema: dict[str, Any] = Field(default_factory=dict)
    required_scopes: list[str] = Field(default_factory=list, max_length=16)
    side_effect: SideEffect = SideEffect.NONE
    idempotency_key: str | None = Field(default=None, max_length=160)
    compensation_ref: str | None = Field(default=None, max_length=200)
    human_gate: bool = False
    max_iterations: int | None = Field(default=None, ge=1, le=10)
    reason_code: str = Field(min_length=3, max_length=100)

    @model_validator(mode="after")
    def step_kind_is_consistent(self) -> BlueprintStep:
        if self.step_type in _ASSET_STEPS and self.asset_ref is None:
            raise ValueError(f"{self.step_type} requires asset_ref")
        if self.step_type not in _ASSET_STEPS and self.asset_ref is not None:
            raise ValueError(f"{self.step_type} cannot bind Registry asset_ref")
        if self.step_type is StepType.REASON and self.max_iterations is None:
            raise ValueError("REASON requires explicit max_iterations")
        if self.step_type is not StepType.REASON and self.max_iterations is not None:
            raise ValueError("max_iterations is only valid for REASON")
        for pointer in self.input_bindings.values():
            if not pointer.startswith(("/task/", "/context/", "/steps/")):
                raise ValueError("input bindings must use an allowed JSON pointer")
        return self


def is_lightweight_gap_step(step: BlueprintStep) -> bool:
    """Return whether a gap can be completed deterministically at near-zero cost.

    Lightweight gaps are limited to non-human, no-side-effect format or small
    information normalization.  Anything requiring an LLM decision, evidence
    gathering, or an authoritative human answer remains a System2 gap.
    """
    return (
        step.step_type in {StepType.REASON, StepType.EXTRACT}
        and step.reason_code in LIGHTWEIGHT_GAP_REASON_CODES
        and step.side_effect is SideEffect.NONE
        and not step.human_gate
        and (step.max_iterations is None or step.max_iterations <= 1)
    )


class BlueprintDraft(StrictModel):
    """Model-produced JSON before authoritative fields are attached."""

    registry_index_id: str
    asset_set_digest: str
    steps: list[BlueprintStep] = Field(min_length=1, max_length=30)
    proposal_codes: list[str] = Field(min_length=1, max_length=16)


class BlueprintProposal(StrictModel):
    blueprint_id: str = Field(pattern=r"^bp_[a-f0-9]{16}$")
    task_id: str = Field(pattern=r"^task_[a-f0-9]{16}$")
    registry_view: RegistryViewRef
    required_subgoal_ids: list[str] = Field(min_length=1, max_length=16)
    steps: list[BlueprintStep] = Field(min_length=1, max_length=30)
    budget: BlueprintBudget
    repair_attempt: Literal[0, 1] = 0
    proposal_codes: list[str] = Field(min_length=1, max_length=16)


class CompileErrorCode(StrEnum):
    PLAN_SCHEMA_INVALID = "PLAN_SCHEMA_INVALID"
    SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
    ASSET_NOT_AVAILABLE = "ASSET_NOT_AVAILABLE"
    DEPENDENCY_INVALID = "DEPENDENCY_INVALID"
    DAG_CYCLE = "DAG_CYCLE"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    POLICY_DENIED = "POLICY_DENIED"
    SCOPE_DENIED = "SCOPE_DENIED"
    RISK_GATE_REQUIRED = "RISK_GATE_REQUIRED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    SIDE_EFFECT_UNKNOWN = "SIDE_EFFECT_UNKNOWN"
    VALIDATOR_MISSING = "VALIDATOR_MISSING"
    INPUT_BINDING_INVALID = "INPUT_BINDING_INVALID"
    SUBGOAL_UNCOVERED = "SUBGOAL_UNCOVERED"
    TOOL_NOT_ALLOWED = "TOOL_NOT_ALLOWED"
    SCHEMA_VERSION_UNSUPPORTED = "SCHEMA_VERSION_UNSUPPORTED"


class CompileError(StrictModel):
    code: CompileErrorCode
    gate: str = Field(min_length=3, max_length=80)
    message: str = Field(min_length=4, max_length=300)
    step_id: str | None = None
    asset_ref: str | None = None
    repairable: bool


class CompiledBlueprint(StrictModel):
    blueprint_id: str
    task_id: str
    registry_view: RegistryViewRef
    steps: list[BlueprintStep]
    budget: BlueprintBudget
    proposal_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    compiled_at: datetime
    compiler_version: Literal["control-compiler.v1"] = "control-compiler.v1"


class CompileResult(StrictModel):
    success: bool
    compiled_blueprint: CompiledBlueprint | None = None
    errors: list[CompileError] = Field(default_factory=list, max_length=50)
    repair_attempts_used: int = Field(default=0, ge=0, le=1)

    @model_validator(mode="after")
    def success_matches_payload(self) -> CompileResult:
        if self.success and (self.compiled_blueprint is None or self.errors):
            raise ValueError("successful compile requires blueprint and no errors")
        if not self.success and (self.compiled_blueprint is not None or not self.errors):
            raise ValueError("failed compile requires errors and no blueprint")
        return self
