"""Control-plane summaries, handoffs, routing, and guarded output."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from reduce_token_agent.domain.blueprint import (
    BlueprintProposal,
    CompileResult,
    Destination,
    PipelineMode,
    RegistryViewRef,
)
from reduce_token_agent.domain.capability import CapabilityCandidate
from reduce_token_agent.domain.runtime import ExecutionRunResult
from reduce_token_agent.domain.task import (
    ClarificationRequest,
    SadAlignment,
    Subgoal,
    TaskContext,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ContractSummary(StrictModel):
    asset_ref: str
    goal: str
    operation: str
    input_schema_title: str
    output_schema_title: str
    preconditions: list[str]
    effects: list[str]
    side_effect: str
    required_scopes: list[str]
    failure_modes: list[str]
    runtime_status: str
    tested_at: str | None
    artifact_schema_version: str


class RerankedCandidate(StrictModel):
    candidate: CapabilityCandidate
    contract: ContractSummary
    rerank_score: float
    hard_failures: list[str] = Field(default_factory=list)
    eligible_as_primary: bool


class SubgoalCandidateSet(StrictModel):
    subgoal: Subgoal
    primary: list[RerankedCandidate]
    graph_closure: list[RerankedCandidate]


class RerankResult(StrictModel):
    candidate_sets: list[SubgoalCandidateSet]
    allowed_asset_refs: list[str]
    # Non-empty means candidates existed but were rejected by a hard policy
    # gate. The planner must never turn this into an unrestricted NEW fallback.
    hard_failure_codes: list[str] = Field(default_factory=list, max_length=50)


class CoverageSummary(StrictModel):
    required_subgoals: int = Field(ge=0)
    deterministic_covered: int = Field(ge=0)
    lightweight_covered: int = Field(default=0, ge=0)
    gap_covered: int = Field(ge=0)
    uncovered: int = Field(ge=0)
    deterministic_ratio: float = Field(ge=0.0, le=1.0)


class FailurePolicy(StrictModel):
    retryable_error_codes: list[str]
    business_rejection_action: Literal["EXPLICIT_BRANCH"]
    irreversible_failure_action: Literal["COMPENSATE_OR_HUMAN"]
    graph_mutation_allowed: Literal[False] = False


class LangGraphHandoff(StrictModel):
    run_id: str
    compiled_blueprint_id: str
    registry_view: RegistryViewRef
    reason_step_ids: list[str]
    failure_policy: FailurePolicy
    execution_contract: Literal["FIXED_META_EXECUTOR_V1"]


class System2Handoff(StrictModel):
    run_id: str
    task_id: str
    subgoal_ids: list[str]
    reason_step_ids: list[str]
    registry_view: RegistryViewRef
    allowed_asset_refs: list[str]
    max_reason_steps: int
    max_llm_calls: int
    max_tool_calls: int
    side_effect_policy: Literal["READ_ONLY"]
    execution_contract: Literal["BOUNDED_SYSTEM2_V1"]


class HandoffReceipt(StrictModel):
    target: Literal["LANGGRAPH_EXECUTION", "SYSTEM2"]
    status: Literal["NOT_IMPLEMENTED", "SUCCEEDED", "PARTIAL", "FAILED"]
    accepted: bool = False
    message: str
    execution: ExecutionRunResult | None = None


class RoutingDecision(StrictModel):
    mode: PipelineMode
    destinations: list[Destination]
    coverage: CoverageSummary
    reason_codes: list[str]


class GuardResult(StrictModel):
    passed: bool
    codes: list[str]


class ControlPlatformResult(StrictModel):
    run_id: str
    task_context: TaskContext | None
    clarification: ClarificationRequest | None
    coarse_subgoals: list[Subgoal]
    sad_alignment: SadAlignment | None
    proposal: BlueprintProposal | None
    compile_result: CompileResult | None
    routing: RoutingDecision
    langgraph_handoff: LangGraphHandoff | None
    system2_handoff: System2Handoff | None
    langgraph_receipt: HandoffReceipt | None
    system2_receipt: HandoffReceipt | None
    guard: GuardResult
    trace_ref: str
    structured_output: dict[str, Any]
