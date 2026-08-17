"""Build the current sparse and dense Route Header projection."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from reduce_token_agent.domain.capability import VisibilityPolicy
from reduce_token_agent.llm.embeddings import EmbeddingProvider
from reduce_token_agent.registry.fts import build_search_text
from reduce_token_agent.registry.retrieval_repository import (
    IndexState,
    RetrievalDocument,
    RetrievalRepository,
)


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Traceable result of an idempotent local index build."""

    state: IndexState
    embedded_count: int
    cached_count: int


class RetrievalIndexBuilder:
    """Build FTS5 and Dense indexes from visible, tested Route Headers."""

    def __init__(
        self,
        repository: RetrievalRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self.repository = repository
        self.embedding_provider = embedding_provider

    def build(
        self,
        *,
        visibility_policy: VisibilityPolicy = VisibilityPolicy.VALIDATED_DRAFT,
        snapshot_id: str | None = None,
        batch_size: int = 16,
    ) -> BuildResult:
        """Build one consistent index view without changing release status."""
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.repository.migrate()
        raw_documents = self.repository.eligible_documents(
            visibility_policy=visibility_policy,
            snapshot_id=snapshot_id,
        )
        documents = [_prepare_document(document) for document in raw_documents]
        cached = self.repository.cached_embeddings(
            documents,
            model=self.embedding_provider.model_name,
        )
        missing = [
            document for document in documents if document.asset_ref not in cached
        ]
        embeddings = dict(cached)
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            matrix = self.embedding_provider.embed(
                [document.embedding_text for document in batch]
            )
            if matrix.shape[0] != len(batch):
                raise RuntimeError("embedding provider returned an invalid batch size")
            for document, vector in zip(batch, matrix, strict=True):
                embeddings[document.asset_ref] = np.asarray(
                    vector,
                    dtype=np.float32,
                )
        if len(embeddings) != len(documents):
            raise RuntimeError("not every retrieval document has an embedding")
        dimensions = {vector.shape for vector in embeddings.values()}
        if len(dimensions) > 1:
            raise RuntimeError("embedding dimensions differ within one index")
        state = self.repository.replace_index(
            documents,
            embeddings,
            visibility_policy=visibility_policy,
            snapshot_id=snapshot_id,
            embedding_model=self.embedding_provider.model_name,
        )
        return BuildResult(
            state=state,
            embedded_count=len(missing),
            cached_count=len(cached),
        )


def _prepare_document(document: RetrievalDocument) -> RetrievalDocument:
    return replace(
        document,
        search_text=build_search_text(
            [
                document.name,
                document.summary,
                *document.positive_triggers,
                *document.keywords,
                document.input_type_summary,
                document.output_type_summary,
                document.domain,
                document.kind,
            ]
        ),
    )
