"""Typed Retrieval Layer contracts.

The first retrieval step exposes only compact Route Headers.  The caller must
explicitly resolve an exact ``asset_ref`` before it receives the Contract and
runtime call descriptor.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from reduce_token_agent.registry.models import AssetKind, RecallPolicy, RiskLevel


class StrictModel(BaseModel):
    """Reject fields that are not part of the retrieval contract."""

    model_config = ConfigDict(extra="forbid")


class VisibilityPolicy(StrEnum):
    """Registry visibility used while building or querying an index."""

    VALIDATED_DRAFT = "VALIDATED_DRAFT"
    ACTIVE_SNAPSHOT = "ACTIVE_SNAPSHOT"


class RetrievalPhase(StrEnum):
    """The two normal retrieval passes plus the separate planning-prior pass."""

    INITIAL = "INITIAL"
    PER_SUBGOAL = "PER_SUBGOAL"
    PLANNING_PRIOR = "PLANNING_PRIOR"


class RetrievalQuery(StrictModel):
    """A bounded query over Route Headers."""

    text: str = Field(min_length=2, max_length=1000)
    phase: RetrievalPhase = RetrievalPhase.INITIAL
    domains: list[str] = Field(default_factory=list, max_length=6)
    kinds: list[AssetKind] = Field(
        default_factory=lambda: [
            AssetKind.FSM_SHARD,
            AssetKind.PRIMITIVE_TOOL,
        ],
        max_length=5,
    )
    scopes: list[str] = Field(default_factory=list, max_length=16)
    tenant_id: str = Field(default="local", min_length=2, max_length=80)
    environment: Literal["local"] = "local"
    data_classification: str = Field(default="SYNTHETIC", min_length=3, max_length=30)
    risk_ceiling: RiskLevel = RiskLevel.HIGH
    top_k: int = Field(default=5, ge=1, le=20)
    graph_top_k: int = Field(default=4, ge=0, le=20)
    max_header_chars: int = Field(default=6000, ge=500, le=20000)
    visibility_policy: VisibilityPolicy = VisibilityPolicy.VALIDATED_DRAFT
    snapshot_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def phase_and_visibility_are_consistent(self) -> RetrievalQuery:
        """Keep ordinary, planning, and governance modes explicit."""
        if self.phase is RetrievalPhase.PLANNING_PRIOR:
            self.kinds = [AssetKind.WORKFLOW_SKELETON]
        elif AssetKind.WORKFLOW_SKELETON in self.kinds:
            raise ValueError("WORKFLOW_SKELETON must use the PLANNING_PRIOR phase")
        if (
            self.visibility_policy is VisibilityPolicy.ACTIVE_SNAPSHOT
            and not self.snapshot_id
        ):
            raise ValueError("ACTIVE_SNAPSHOT retrieval requires snapshot_id")
        if (
            self.visibility_policy is VisibilityPolicy.VALIDATED_DRAFT
            and self.snapshot_id is not None
        ):
            raise ValueError("VALIDATED_DRAFT retrieval cannot claim a snapshot_id")
        return self


class RetrievalProvenance(StrictModel):
    """Why and through which channels a candidate entered the result."""

    source: Literal["DIRECT", "GRAPH_EXPANSION"]
    visibility_policy: VisibilityPolicy
    index_id: str
    sparse_rank: int | None = None
    dense_rank: int | None = None
    sparse_score: float | None = None
    dense_score: float | None = None
    rrf_score: float = 0.0
    metadata_bonus: float = 0.0
    anti_trigger_penalty: float = 0.0
    parent_ref: str | None = None
    edge_type: str | None = None
    edge_evidence: str | None = None


class CapabilityCandidate(StrictModel):
    """Compact Header returned to the control plane."""

    asset_ref: str
    kind: AssetKind
    domain: str
    name: str
    summary: str
    recall_policy: RecallPolicy
    input_type_summary: str
    output_type_summary: str
    risk_level: RiskLevel
    required_scopes: list[str]
    rank: int = Field(ge=1)
    score: float
    provenance: RetrievalProvenance


class RetrievalResult(StrictModel):
    """One bounded retrieval response."""

    query: RetrievalQuery
    index_id: str
    asset_set_digest: str
    embedding_model: str
    candidates: list[CapabilityCandidate]
    direct_count: int = Field(ge=0)
    graph_expansion_count: int = Field(ge=0)
    truncated_by_budget: bool


class AssetCallDescriptor(StrictModel):
    """Safe call information resolved for one exact asset version."""

    implementation_ref: str
    execution_mode: Literal["EXECUTABLE", "PLANNING_ONLY"]
    runtime_status: Literal["READY", "PLANNING_ONLY", "UNAVAILABLE"]
    policy_version: str
    tested_at: str | None
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    sample_payload: dict[str, Any]
    required_validator_ref: str | None


class RelatedAsset(StrictModel):
    """One explicit one-hop capability relation."""

    asset_ref: str
    kind: AssetKind
    edge_type: str
    evidence: str


class AssetDetails(StrictModel):
    """Contract and call metadata loaded only after exact-ref selection."""

    asset_ref: str
    asset_id: str
    version: str
    kind: AssetKind
    domain: str
    release_status: str
    validation_status: str
    name: str
    summary: str
    positive_triggers: list[str]
    anti_triggers: list[str]
    keywords: list[str]
    contract: dict[str, Any]
    call: AssetCallDescriptor
    related_assets: list[RelatedAsset]
    artifact_schema_version: str
    artifact_path: str
    artifact_digest: str
    runtime_metadata_path: str
    runtime_metadata_digest: str
