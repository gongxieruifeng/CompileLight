"""Two-channel Header retrieval with deterministic filtering and graph expansion."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import cast

from reduce_token_agent.domain.capability import (
    CapabilityCandidate,
    RetrievalPhase,
    RetrievalProvenance,
    RetrievalQuery,
    RetrievalResult,
)
from reduce_token_agent.llm.embeddings import EmbeddingProvider
from reduce_token_agent.registry.dense import cosine_ranking
from reduce_token_agent.registry.fts import lexical_overlap
from reduce_token_agent.registry.models import AssetKind, RecallPolicy, RiskLevel
from reduce_token_agent.registry.retrieval_repository import (
    RetrievalDocument,
    RetrievalRepository,
)
from reduce_token_agent.registry.rrf import ranks_by_ref, reciprocal_rank_fusion

_RISK_ORDER = {
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
}


@dataclass(frozen=True, slots=True)
class _Scored:
    document: RetrievalDocument
    score: float
    sparse_rank: int | None
    dense_rank: int | None
    sparse_score: float | None
    dense_score: float | None
    rrf_score: float
    metadata_bonus: float
    anti_penalty: float


class CapabilityRetrievalService:
    """Return compact Headers, then add declared dependencies by one hop."""

    def __init__(
        self,
        repository: RetrievalRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        state = self.repository.current_index()
        self._validate_index(query, state.visibility_policy, state.snapshot_id)
        if self.embedding_provider.model_name != state.embedding_model:
            raise RuntimeError(
                "query embedding model differs from the built retrieval index"
            )
        documents = self.repository.header_documents()
        admissible = {
            asset_ref: document
            for asset_ref, document in documents.items()
            if _is_admissible(document, query)
        }

        sparse_hits = [
            hit
            for hit in self.repository.sparse_search(query.text)
            if hit.asset_ref in admissible
        ]
        query_vector = self.embedding_provider.embed([query.text])[0]
        dense_hits = [
            hit
            for hit in cosine_ranking(
                query_vector,
                [
                    pair
                    for pair in self.repository.dense_vectors()
                    if pair[0] in admissible
                ],
            )
        ]
        sparse_refs = [hit.asset_ref for hit in sparse_hits]
        dense_refs = [asset_ref for asset_ref, _ in dense_hits]
        fused = reciprocal_rank_fusion([sparse_refs, dense_refs])
        sparse_ranks = ranks_by_ref(sparse_refs)
        dense_ranks = ranks_by_ref(dense_refs)
        sparse_scores = {hit.asset_ref: hit.score for hit in sparse_hits}
        dense_scores = dict(dense_hits)

        scored: list[_Scored] = []
        for asset_ref, document in admissible.items():
            metadata_bonus = _metadata_bonus(query, document)
            anti_penalty = 0.03 * lexical_overlap(
                query.text,
                document.anti_triggers,
            )
            rrf_score = fused.get(asset_ref, 0.0)
            score = rrf_score + metadata_bonus - anti_penalty
            if rrf_score == 0.0 and metadata_bonus == 0.0:
                continue
            scored.append(
                _Scored(
                    document=document,
                    score=score,
                    sparse_rank=sparse_ranks.get(asset_ref),
                    dense_rank=dense_ranks.get(asset_ref),
                    sparse_score=sparse_scores.get(asset_ref),
                    dense_score=dense_scores.get(asset_ref),
                    rrf_score=rrf_score,
                    metadata_bonus=metadata_bonus,
                    anti_penalty=anti_penalty,
                )
            )
        scored.sort(key=lambda item: (-item.score, item.document.asset_ref))
        direct = scored[: query.top_k]
        candidates = [
            _direct_candidate(item, rank, query, state.index_id)
            for rank, item in enumerate(direct, start=1)
        ]

        if query.phase is not RetrievalPhase.PLANNING_PRIOR and query.graph_top_k:
            seen = {candidate.asset_ref for candidate in candidates}
            parent_refs = [candidate.asset_ref for candidate in candidates]
            graph_hits = self.repository.graph_expand(
                parent_refs,
                visibility_policy=query.visibility_policy,
                snapshot_id=query.snapshot_id,
                tenant_id=query.tenant_id,
                environment=query.environment,
                data_classification=query.data_classification,
            )
            parent_rank = {
                asset_ref: rank for rank, asset_ref in enumerate(parent_refs)
            }
            edge_rank = {
                "COMPATIBLE_VIA_ADAPTER": 0,
                "DEPENDS_ON": 1,
                "REQUIRES_VALIDATOR": 2,
            }
            graph_hits.sort(
                key=lambda hit: (
                    parent_rank[hit.parent_ref],
                    edge_rank.get(hit.edge_type, 9),
                    hit.asset_ref,
                )
            )
            parent_scores = {
                candidate.asset_ref: candidate.score for candidate in candidates
            }
            for hit in graph_hits:
                if hit.asset_ref in seen or len(candidates) >= query.top_k + query.graph_top_k:
                    continue
                row = self.repository.header_row(hit.asset_ref)
                if row is None:
                    continue
                candidates.append(
                    CapabilityCandidate(
                        asset_ref=hit.asset_ref,
                        kind=AssetKind(hit.kind),
                        domain=cast(str, row["domain"]),
                        name=cast(str, row["name"]),
                        summary=cast(str, row["summary"]),
                        recall_policy=RecallPolicy(cast(str, row["recall_policy"])),
                        input_type_summary=cast(str, row["input_type_summary"]),
                        output_type_summary=cast(str, row["output_type_summary"]),
                        risk_level=RiskLevel(cast(str, row["risk_level"])),
                        required_scopes=cast(
                            list[str], json.loads(row["required_scopes_json"])
                        ),
                        rank=len(candidates) + 1,
                        score=parent_scores.get(hit.parent_ref, 0.0),
                        provenance=RetrievalProvenance(
                            source="GRAPH_EXPANSION",
                            visibility_policy=query.visibility_policy,
                            index_id=state.index_id,
                            parent_ref=hit.parent_ref,
                            edge_type=hit.edge_type,
                            edge_evidence=hit.evidence,
                        ),
                    )
                )
                seen.add(hit.asset_ref)

        bounded, truncated = _apply_header_budget(
            candidates,
            max_chars=query.max_header_chars,
        )
        reranked = [
            candidate.model_copy(update={"rank": rank})
            for rank, candidate in enumerate(bounded, start=1)
        ]
        return RetrievalResult(
            query=query,
            index_id=state.index_id,
            asset_set_digest=state.asset_set_digest,
            embedding_model=state.embedding_model,
            candidates=reranked,
            direct_count=sum(
                candidate.provenance.source == "DIRECT" for candidate in reranked
            ),
            graph_expansion_count=sum(
                candidate.provenance.source == "GRAPH_EXPANSION"
                for candidate in reranked
            ),
            truncated_by_budget=truncated,
        )

    @staticmethod
    def _validate_index(
        query: RetrievalQuery,
        visibility_policy: str,
        snapshot_id: str | None,
    ) -> None:
        if query.visibility_policy.value != visibility_policy:
            raise RuntimeError("query visibility does not match the built index")
        if query.snapshot_id != snapshot_id:
            raise RuntimeError("query snapshot does not match the built index")


def _is_admissible(document: RetrievalDocument, query: RetrievalQuery) -> bool:
    if query.domains and document.domain not in query.domains:
        return False
    if document.tenant_scope != query.tenant_id:
        return False
    if document.environment != query.environment:
        return False
    if document.data_classification != query.data_classification:
        return False
    if AssetKind(document.kind) not in query.kinds:
        return False
    expected_policy = (
        "PLANNING_PRIOR"
        if query.phase is RetrievalPhase.PLANNING_PRIOR
        else "ORDINARY"
    )
    if document.recall_policy != expected_policy:
        return False
    if _RISK_ORDER[RiskLevel(document.risk_level)] > _RISK_ORDER[query.risk_ceiling]:
        return False
    return set(document.required_scopes).issubset(query.scopes)


def _metadata_bonus(query: RetrievalQuery, document: RetrievalDocument) -> float:
    overlap = lexical_overlap(
        query.text,
        [*document.positive_triggers, *document.keywords],
    )
    bonus = min(overlap, 5) * 0.004
    if query.domains and document.domain in query.domains:
        bonus += 0.003
    if document.kind == AssetKind.FSM_SHARD.value:
        bonus += 0.001
    return bonus


def _direct_candidate(
    item: _Scored,
    rank: int,
    query: RetrievalQuery,
    index_id: str,
) -> CapabilityCandidate:
    document = item.document
    return CapabilityCandidate(
        asset_ref=document.asset_ref,
        kind=AssetKind(document.kind),
        domain=document.domain,
        name=document.name,
        summary=document.summary,
        recall_policy=RecallPolicy(document.recall_policy),
        input_type_summary=document.input_type_summary,
        output_type_summary=document.output_type_summary,
        risk_level=RiskLevel(document.risk_level),
        required_scopes=document.required_scopes,
        rank=rank,
        score=item.score,
        provenance=RetrievalProvenance(
            source="DIRECT",
            visibility_policy=query.visibility_policy,
            index_id=index_id,
            sparse_rank=item.sparse_rank,
            dense_rank=item.dense_rank,
            sparse_score=item.sparse_score,
            dense_score=item.dense_score,
            rrf_score=item.rrf_score,
            metadata_bonus=item.metadata_bonus,
            anti_trigger_penalty=item.anti_penalty,
        ),
    )


def _apply_header_budget(
    candidates: list[CapabilityCandidate],
    *,
    max_chars: int,
) -> tuple[list[CapabilityCandidate], bool]:
    selected: list[CapabilityCandidate] = []
    used = 0
    for candidate in candidates:
        size = sum(
            len(value)
            for value in (
                candidate.asset_ref,
                candidate.name,
                candidate.summary,
                candidate.input_type_summary,
                candidate.output_type_summary,
            )
        )
        if selected and used + size > max_chars:
            return selected, True
        selected.append(candidate)
        used += size
    return selected, False
