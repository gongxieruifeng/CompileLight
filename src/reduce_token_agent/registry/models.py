"""Typed contracts for versioned capability assets stored in the Registry."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject fields outside the Registry contract."""

    model_config = ConfigDict(extra="forbid")


class AssetKind(StrEnum):
    """Only concrete database kinds; Skill is deliberately not a kind."""

    PRIMITIVE_TOOL = "PRIMITIVE_TOOL"
    FSM_SHARD = "FSM_SHARD"
    WORKFLOW_SKELETON = "WORKFLOW_SKELETON"
    ADAPTER = "ADAPTER"
    VALIDATOR = "VALIDATOR"


class RecallPolicy(StrEnum):
    """How an asset enters planning context."""

    ORDINARY = "ORDINARY"
    PLANNING_PRIOR = "PLANNING_PRIOR"
    GRAPH_ONLY = "GRAPH_ONLY"


class SideEffect(StrEnum):
    """Controlled side-effect class used by contracts."""

    NONE = "NONE"
    READ_ONLY = "READ_ONLY"
    LOCAL_WRITE = "LOCAL_WRITE"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"


class RiskLevel(StrEnum):
    """Coarse risk attached to one immutable asset version."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ReleaseStatus(StrEnum):
    """PoC release lifecycle."""

    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class EdgeType(StrEnum):
    """Allowed one-hop capability graph relationships."""

    DEPENDS_ON = "DEPENDS_ON"
    REQUIRES_VALIDATOR = "REQUIRES_VALIDATOR"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"
    COMPATIBLE_VIA_ADAPTER = "COMPATIBLE_VIA_ADAPTER"


class JsonObjectSchema(StrictModel):
    """Small JSON Schema subset sufficient for current asset contracts."""

    type: Literal["object"] = "object"
    title: str = Field(min_length=3, max_length=100)
    properties: dict[str, dict[str, Any]] = Field(min_length=1, max_length=20)
    required: list[str] = Field(default_factory=list, max_length=20)
    additionalProperties: bool = False

    @model_validator(mode="after")
    def required_fields_exist(self) -> JsonObjectSchema:
        """Ensure required names are declared properties."""
        missing = set(self.required) - set(self.properties)
        if missing:
            raise ValueError(f"required fields missing from properties: {sorted(missing)}")
        return self


class AssetContract(StrictModel):
    """Compiler-facing contract for one executable or planning asset."""

    goal: str = Field(min_length=12, max_length=240)
    operation: str = Field(pattern=r"^[a-z][a-z0-9_.]{3,120}$")
    input_schema: JsonObjectSchema
    output_schema: JsonObjectSchema
    preconditions: list[str] = Field(min_length=1, max_length=8)
    effects: list[str] = Field(min_length=1, max_length=8)
    side_effect: SideEffect
    failure_modes: list[str] = Field(min_length=1, max_length=8)
    timeout_seconds: int = Field(ge=1, le=300)
    max_retries: int = Field(ge=0, le=3)
    idempotency_required: bool
    compensation: str | None = Field(default=None, max_length=200)
    required_scopes: list[str] = Field(default_factory=list, max_length=8)
    tenant_scope: Literal["local"] = "local"
    environment: Literal["local"] = "local"
    data_classification: Literal["SYNTHETIC"] = "SYNTHETIC"

    @model_validator(mode="after")
    def writes_require_idempotency(self) -> AssetContract:
        """Require an idempotency boundary for deterministic writes."""
        if self.side_effect is SideEffect.LOCAL_WRITE and not self.idempotency_required:
            raise ValueError("LOCAL_WRITE assets must require idempotency")
        return self


class PrimitiveToolBody(StrictModel):
    """Body for one controlled function or API operation."""

    kind: Literal[AssetKind.PRIMITIVE_TOOL]
    handler_ref: str = Field(pattern=r"^python://[a-z][a-z0-9_.:]{5,180}$")
    invocation: Literal["FUNCTION"]
    operation_count: Literal[1] = 1
    directly_executable: Literal[True] = True


class FsmState(StrictModel):
    """One semantic state in an FSM Shard."""

    state_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,60}$")
    invariant: str = Field(min_length=8, max_length=180)


class FsmTransition(StrictModel):
    """One controlled transition in an FSM Shard."""

    from_state: str
    event: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")
    to_state: str
    guard: str = Field(min_length=4, max_length=180)


class FsmShardBody(StrictModel):
    """Body for a small state graph completing one stable subgoal."""

    kind: Literal[AssetKind.FSM_SHARD]
    subgoal: str = Field(min_length=12, max_length=220)
    states: list[FsmState] = Field(min_length=2, max_length=7)
    transitions: list[FsmTransition] = Field(min_length=1, max_length=12)
    start_state: str
    terminal_states: list[str] = Field(min_length=1, max_length=3)
    directly_executable: Literal[True] = True

    @model_validator(mode="after")
    def state_graph_is_closed(self) -> FsmShardBody:
        """Require unique, closed references and reachable terminal states."""
        state_ids = [state.state_id for state in self.states]
        known = set(state_ids)
        if len(known) != len(state_ids):
            raise ValueError("FSM state IDs must be unique")
        if self.start_state not in known:
            raise ValueError("FSM start state is unknown")
        if not set(self.terminal_states).issubset(known):
            raise ValueError("FSM terminal state is unknown")
        for transition in self.transitions:
            if transition.from_state not in known or transition.to_state not in known:
                raise ValueError("FSM transition references an unknown state")

        reachable = {self.start_state}
        changed = True
        while changed:
            changed = False
            for transition in self.transitions:
                if transition.from_state in reachable and transition.to_state not in reachable:
                    reachable.add(transition.to_state)
                    changed = True
        if not set(self.terminal_states).intersection(reachable):
            raise ValueError("FSM has no reachable terminal state")
        return self


class DaefStage(StrictModel):
    """One domain-independent macro stage."""

    stage: Literal["INFORMATION", "TRANSFORM", "DECISION", "ACTION", "VALIDATION"]
    expected_state: str = Field(min_length=8, max_length=180)
    required_invariants: list[str] = Field(min_length=1, max_length=5)


class WorkflowSkeletonBody(StrictModel):
    """DAEF planning prior; never a concrete Blueprint or executable graph."""

    kind: Literal[AssetKind.WORKFLOW_SKELETON]
    stages: list[DaefStage] = Field(min_length=4, max_length=6)
    directly_executable: Literal[False] = False
    binds_asset_refs: Literal[False] = False

    @model_validator(mode="after")
    def stages_are_unique_and_ordered(self) -> WorkflowSkeletonBody:
        """Keep one ordered macro topology without repeated stages."""
        names = [stage.stage for stage in self.stages]
        if len(names) != len(set(names)):
            raise ValueError("DAEF stages must be unique")
        if names[0] != "INFORMATION" or names[-1] != "VALIDATION":
            raise ValueError("DAEF must start with INFORMATION and end with VALIDATION")
        return self


class FieldMapping(StrictModel):
    """Deterministic field rename/default mapping."""

    source: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,100}$")
    target: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,100}$")
    transform: Literal["COPY", "NORMALIZE_ENUM", "DEFAULT"]


class AdapterBody(StrictModel):
    """Body for a side-effect-free contract conversion."""

    kind: Literal[AssetKind.ADAPTER]
    from_schema: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{2,80}$")
    to_schema: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{2,80}$")
    mappings: list[FieldMapping] = Field(min_length=1, max_length=12)
    deterministic: Literal[True] = True
    side_effect: Literal[SideEffect.NONE] = SideEffect.NONE
    directly_executable: Literal[True] = True

    @model_validator(mode="after")
    def schemas_differ(self) -> AdapterBody:
        """An Adapter must bridge two distinct contracts."""
        if self.from_schema == self.to_schema:
            raise ValueError("Adapter source and target schemas must differ")
        return self


class ValidatorRule(StrictModel):
    """One declarative validator rule with a typed failure code."""

    field: str = Field(pattern=r"^[a-z][a-z0-9_.]{1,100}$")
    operator: Literal[
        "EXISTS",
        "EQ",
        "GTE",
        "LTE",
        "NON_NEGATIVE",
        "IN",
        "ALL_TRUE",
    ]
    expected: Any | None = None
    failure_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{3,63}$")


class ValidatorBody(StrictModel):
    """Body for an independent completion-state validator."""

    kind: Literal[AssetKind.VALIDATOR]
    validates_schema: str = Field(pattern=r"^[A-Z][A-Za-z0-9]{2,80}$")
    rules: list[ValidatorRule] = Field(min_length=1, max_length=12)
    executor: Literal["DECLARATIVE_RULESET"]
    directly_executable: Literal[True] = True


AssetBody = Annotated[
    PrimitiveToolBody
    | FsmShardBody
    | WorkflowSkeletonBody
    | AdapterBody
    | ValidatorBody,
    Field(discriminator="kind"),
]


class RouteHeader(StrictModel):
    """Small retrieval projection separated from the execution Body."""

    name: str = Field(min_length=4, max_length=120)
    summary: str = Field(min_length=12, max_length=300)
    positive_triggers: list[str] = Field(min_length=1, max_length=8)
    anti_triggers: list[str] = Field(min_length=1, max_length=8)
    input_type_summary: str = Field(min_length=3, max_length=160)
    output_type_summary: str = Field(min_length=3, max_length=160)
    keywords: list[str] = Field(min_length=1, max_length=16)


class SourceEvidence(StrictModel):
    """Minimal provenance back to one synthetic Trace boundary."""

    trace_id: str = Field(
        pattern=r"^trace_(?:syn_[a-z0-9_]{3,140}|run_[a-f0-9]{16})$"
    )
    scenario_id: str = Field(pattern=r"^[a-z][a-z0-9_]{3,120}$")
    step_ids: list[str] = Field(default_factory=list, max_length=6)
    candidate_ids: list[str] = Field(default_factory=list, max_length=6)


class AssetDefinition(StrictModel):
    """One immutable, trace-derived Registry asset version."""

    asset_id: str = Field(pattern=r"^(tool|fsm|skeleton|adapter|validator)\.[a-z0-9_.]+$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    kind: AssetKind
    owner: str = Field(pattern=r"^[a-z][a-z0-9_]{2,80}$")
    domain: str = Field(pattern=r"^[a-z][a-z0-9_]{2,80}$")
    recall_policy: RecallPolicy
    risk_level: RiskLevel
    release_status: Literal[ReleaseStatus.DRAFT] = ReleaseStatus.DRAFT
    route_header: RouteHeader
    contract: AssetContract
    body: AssetBody
    source_evidence: list[SourceEvidence] = Field(min_length=1, max_length=4)
    test_suite_ref: str = Field(
        pattern=r"^suite\.[a-z][a-z0-9_.]{2,120}@[0-9]+\.[0-9]+\.[0-9]+$"
    )

    @property
    def asset_ref(self) -> str:
        """Return immutable identity used by Blueprint and graph edges."""
        return f"{self.asset_id}@{self.version}"

    @model_validator(mode="after")
    def kind_boundaries_are_consistent(self) -> AssetDefinition:
        """Enforce ID, Body, recall, and executability boundaries per Kind."""
        expected_prefix = {
            AssetKind.PRIMITIVE_TOOL: "tool.",
            AssetKind.FSM_SHARD: "fsm.",
            AssetKind.WORKFLOW_SKELETON: "skeleton.",
            AssetKind.ADAPTER: "adapter.",
            AssetKind.VALIDATOR: "validator.",
        }[self.kind]
        if not self.asset_id.startswith(expected_prefix):
            raise ValueError(f"{self.kind} asset_id must start with {expected_prefix}")
        if self.body.kind is not self.kind:
            raise ValueError("Body kind must match asset kind")

        expected_recall = {
            AssetKind.PRIMITIVE_TOOL: RecallPolicy.ORDINARY,
            AssetKind.FSM_SHARD: RecallPolicy.ORDINARY,
            AssetKind.WORKFLOW_SKELETON: RecallPolicy.PLANNING_PRIOR,
            AssetKind.ADAPTER: RecallPolicy.GRAPH_ONLY,
            AssetKind.VALIDATOR: RecallPolicy.GRAPH_ONLY,
        }[self.kind]
        if self.recall_policy is not expected_recall:
            raise ValueError(f"{self.kind} must use {expected_recall} recall")

        if self.kind is AssetKind.WORKFLOW_SKELETON:
            if self.contract.side_effect is not SideEffect.NONE:
                raise ValueError("WORKFLOW_SKELETON cannot have side effects")
            if re.search(r"(tool|fsm|adapter|validator)\.[a-z0-9_.]+@", str(self.body)):
                raise ValueError("WORKFLOW_SKELETON cannot bind concrete asset versions")
        return self


class CapabilityEdge(StrictModel):
    """One explicit one-hop relationship between versioned assets."""

    from_ref: str
    to_ref: str
    edge_type: EdgeType
    adapter_ref: str | None = None
    evidence: str = Field(min_length=8, max_length=240)

    @model_validator(mode="after")
    def adapter_edge_has_adapter(self) -> CapabilityEdge:
        """Require an Adapter ref only for compatibility edges."""
        if self.edge_type is EdgeType.COMPATIBLE_VIA_ADAPTER and not self.adapter_ref:
            raise ValueError("COMPATIBLE_VIA_ADAPTER requires adapter_ref")
        if self.edge_type is not EdgeType.COMPATIBLE_VIA_ADAPTER and self.adapter_ref:
            raise ValueError("adapter_ref is only valid for COMPATIBLE_VIA_ADAPTER")
        return self
