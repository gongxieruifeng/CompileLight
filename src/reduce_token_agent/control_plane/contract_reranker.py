"""Deterministic Contract-aware reranking after hybrid Header retrieval."""

from __future__ import annotations

import re

from reduce_token_agent.domain.capability import CapabilityCandidate, RetrievalResult
from reduce_token_agent.domain.control import (
    ContractSummary,
    RerankedCandidate,
    RerankResult,
    SubgoalCandidateSet,
)
from reduce_token_agent.domain.task import DataClassification, Subgoal, TaskContext
from reduce_token_agent.registry.models import AssetKind, RiskLevel
from reduce_token_agent.registry.service import AssetResolver

_RISK_ORDER = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
}
_PRIMARY_KINDS = {AssetKind.FSM_SHARD, AssetKind.PRIMITIVE_TOOL}


class ContractReranker:
    """Load only retrieved Contracts and reject hard policy mismatches first."""

    def __init__(
        self,
        resolver: AssetResolver,
        *,
        top_n: int,
        supported_asset_schema_version: str,
    ) -> None:
        self.resolver = resolver
        self.top_n = top_n
        self.supported_asset_schema_version = supported_asset_schema_version

    def rerank(
        self,
        *,
        context: TaskContext,
        subgoal_results: list[tuple[Subgoal, RetrievalResult]],
    ) -> RerankResult:
        candidate_sets: list[SubgoalCandidateSet] = []
        all_allowed: list[str] = []
        hard_failure_codes: set[str] = set()
        for subgoal, retrieval in subgoal_results:
            reranked = [
                self._score(context, subgoal, candidate)
                for candidate in retrieval.candidates
            ]
            eligible_primary = [
                item
                for item in reranked
                if item.eligible_as_primary and not item.hard_failures
            ]
            eligible_primary.sort(
                key=lambda item: (
                    -item.rerank_score,
                    item.candidate.asset_ref,
                )
            )
            primary = eligible_primary[: self.top_n]
            primary_refs = {item.candidate.asset_ref for item in primary}
            graph_closure = [
                item
                for item in reranked
                if (
                    item.candidate.provenance.source == "GRAPH_EXPANSION"
                    and item.candidate.provenance.parent_ref in primary_refs
                    and not item.hard_failures
                )
            ]
            graph_closure.sort(
                key=lambda item: (
                    item.candidate.provenance.parent_ref or "",
                    item.candidate.asset_ref,
                )
            )
            allowed = [*primary, *graph_closure]
            all_allowed.extend(item.candidate.asset_ref for item in allowed)
            hard_failure_codes.update(
                failure for item in reranked for failure in item.hard_failures
            )
            candidate_sets.append(
                SubgoalCandidateSet(
                    subgoal=subgoal,
                    primary=primary,
                    graph_closure=graph_closure,
                )
            )
        return RerankResult(
            candidate_sets=candidate_sets,
            allowed_asset_refs=list(dict.fromkeys(all_allowed)),
            hard_failure_codes=sorted(hard_failure_codes),
        )

    def _score(
        self,
        context: TaskContext,
        subgoal: Subgoal,
        candidate: CapabilityCandidate,
    ) -> RerankedCandidate:
        details = self.resolver.resolve(candidate.asset_ref)
        contract = details.contract
        failures: list[str] = []
        if contract["tenant_scope"] != context.tenant_id:
            failures.append("TENANT_DENIED")
        if contract["environment"] != context.environment:
            failures.append("ENVIRONMENT_DENIED")
        if not set(details.call.input_schema).issuperset({"type", "title"}):
            failures.append("INPUT_SCHEMA_INVALID")
        if details.artifact_schema_version != self.supported_asset_schema_version:
            failures.append("SCHEMA_VERSION_UNSUPPORTED")
        if not set(contract["required_scopes"]).issubset(context.scopes):
            failures.append("SCOPE_DENIED")
        if _RISK_ORDER[candidate.risk_level] > _RISK_ORDER[context.risk_level]:
            failures.append("RISK_DENIED")
        if details.validation_status != "PASS" or details.call.tested_at is None:
            failures.append("ASSET_NOT_TESTED")
        if details.call.runtime_status not in {"READY", "PLANNING_ONLY"}:
            failures.append("RUNTIME_UNAVAILABLE")
        if (
            context.data_classification is not DataClassification.SYNTHETIC
            and contract["data_classification"] == "SYNTHETIC"
        ):
            failures.append("DATA_CLASSIFICATION_DENIED")

        rank_signal = 1.0 / max(candidate.rank, 1)
        semantic_signal = min(max(candidate.score, 0.0) * 10.0, 1.0)
        text_signal = _text_overlap(
            f"{subgoal.goal} {subgoal.expected_state}",
            " ".join(
                [
                    candidate.name,
                    candidate.summary,
                    str(contract["goal"]),
                    " ".join(contract["effects"]),
                ]
            ),
        )
        domain_signal = 1.0 if candidate.domain in context.domain_hints else 0.5
        reliability_signal = 1.0 if details.call.tested_at else 0.0
        rerank_score = (
            0.30 * semantic_signal
            + 0.25 * rank_signal
            + 0.20 * text_signal
            + 0.15 * domain_signal
            + 0.10 * reliability_signal
        )
        if failures:
            rerank_score = 0.0
        summary = ContractSummary(
            asset_ref=details.asset_ref,
            goal=str(contract["goal"]),
            operation=str(contract["operation"]),
            input_schema_title=str(contract["input_schema"]["title"]),
            output_schema_title=str(contract["output_schema"]["title"]),
            preconditions=list(contract["preconditions"]),
            effects=list(contract["effects"]),
            side_effect=str(contract["side_effect"]),
            required_scopes=list(contract["required_scopes"]),
            failure_modes=list(contract["failure_modes"]),
            runtime_status=details.call.runtime_status,
            tested_at=details.call.tested_at,
            artifact_schema_version=details.artifact_schema_version,
        )
        return RerankedCandidate(
            candidate=candidate,
            contract=summary,
            rerank_score=rerank_score,
            hard_failures=failures,
            eligible_as_primary=(
                candidate.provenance.source == "DIRECT"
                and candidate.kind in _PRIMARY_KINDS
            ),
        )


def _text_overlap(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens:
        return 0.0
    return min(len(left_tokens & right_tokens) / len(left_tokens), 1.0)


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = set(re.findall(r"[a-z0-9_]+", lowered))
    for sequence in re.findall(r"[\u3400-\u9fff]+", lowered):
        tokens.update(
            sequence[index : index + 2]
            for index in range(max(len(sequence) - 1, 0))
        )
    return tokens
