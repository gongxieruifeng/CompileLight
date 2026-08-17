"""Task normalization, decomposition, and one-pass SAD contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reduce_token_agent.registry.models import RiskLevel


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataClassification(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    SYNTHETIC = "SYNTHETIC"


class TaskRequest(StrictModel):
    """External request plus authoritative caller metadata."""

    query: str = Field(min_length=2, max_length=4000)
    tenant_id: str | None = Field(default=None, min_length=2, max_length=80)
    principal_id: str | None = Field(default=None, min_length=2, max_length=120)
    scopes: list[str] = Field(default_factory=list, max_length=32)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    timezone: str = Field(default="Asia/Shanghai", min_length=3, max_length=80)
    locale: str = Field(default="zh-CN", min_length=2, max_length=20)
    environment: Literal["local"] = "local"
    declared_data_classification: DataClassification | None = None
    declared_risk_level: RiskLevel | None = None
    acceptance_criteria: list[str] = Field(default_factory=list, max_length=12)


class NormalizedTaskFacts(StrictModel):
    """Structured model output; identity is deliberately excluded."""

    entities: dict[str, Any] = Field(default_factory=dict, max_length=30)
    domain_hints: list[
        Literal[
            "corporate_operations",
            "customer_service",
            "financial_report",
            "internal_communication",
            "loan_contract",
            "risk_compliance",
        ]
    ] = Field(default_factory=list, max_length=3)
    data_classification: DataClassification
    risk_level: RiskLevel
    acceptance_criteria: list[str] = Field(min_length=1, max_length=12)
    time_expressions: list[str] = Field(default_factory=list, max_length=10)
    irreversible_action_requested: bool = False
    normalization_codes: list[str] = Field(default_factory=list, max_length=12)


class TaskContext(StrictModel):
    """Frozen normalized context used by every later control stage."""

    task_id: str = Field(pattern=r"^task_[a-f0-9]{16}$")
    query: str = Field(min_length=2, max_length=4000)
    tenant_id: str
    principal_id: str
    scopes: list[str]
    requested_at: datetime
    timezone: str
    locale: str
    environment: Literal["local"]
    entities: dict[str, Any]
    domain_hints: list[str]
    data_classification: DataClassification
    risk_level: RiskLevel
    acceptance_criteria: list[str]
    time_expressions: list[str]
    irreversible_action_requested: bool
    normalization_codes: list[str]


class ClarificationRequest(StrictModel):
    """A safe, structured request for missing authoritative information."""

    reason_code: Literal[
        "MISSING_TENANT_ID",
        "MISSING_PRINCIPAL_ID",
        "MISSING_IDENTITY",
        "INPUT_AMBIGUOUS",
    ]
    missing_fields: list[str] = Field(min_length=1, max_length=8)
    message: str = Field(min_length=8, max_length=300)


class Subgoal(StrictModel):
    """One high-level business goal, never an internal HTTP action."""

    subgoal_id: str = Field(pattern=r"^sg_[a-z0-9_]{2,60}$")
    goal: str = Field(min_length=6, max_length=300)
    expected_state: str = Field(min_length=6, max_length=300)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=8)
    required: bool = True


class DecompositionDraft(StrictModel):
    """Pass-1 minimal business decomposition produced by a structured model."""

    subgoals: list[Subgoal] = Field(min_length=1, max_length=8)
    decomposition_codes: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def subgoal_ids_are_unique(self) -> DecompositionDraft:
        ids = [subgoal.subgoal_id for subgoal in self.subgoals]
        if len(ids) != len(set(ids)):
            raise ValueError("subgoal IDs must be unique")
        return self


class SadAlignedSubgoal(Subgoal):
    """One SAD-adjusted boundary with coverage hints."""

    source_subgoal_ids: list[str] = Field(min_length=1, max_length=8)
    covered_hint_refs: list[str] = Field(default_factory=list, max_length=12)
    uncovered: bool
    alignment_code: Literal[
        "UNCHANGED",
        "MERGED_TO_ASSET_BOUNDARY",
        "SPLIT_BY_CONTRACT_BOUNDARY",
        "UNSUPPORTED_PRESERVED",
    ]


class SadAlignment(StrictModel):
    """Exactly one feedback alignment result."""

    aligned_subgoals: list[SadAlignedSubgoal] = Field(min_length=1, max_length=8)
    alignment_iteration: Literal[1] = 1
    alignment_codes: list[str] = Field(default_factory=list, max_length=16)

