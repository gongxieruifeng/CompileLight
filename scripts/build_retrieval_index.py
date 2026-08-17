#!/usr/bin/env python3
"""Build the current FTS5 + Ollama Dense Route Header index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reduce_token_agent.domain.capability import VisibilityPolicy
from reduce_token_agent.llm.embeddings import OllamaEmbeddingProvider
from reduce_token_agent.registry.retrieval_index import RetrievalIndexBuilder
from reduce_token_agent.registry.retrieval_repository import RetrievalRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--visibility",
        choices=["active", "validated-draft"],
        default="active",
        help="active uses the latest ACTIVE snapshot; validated-draft is only for extraction-time debugging",
    )
    parser.add_argument("--snapshot-id")
    arguments = parser.parse_args()

    project_root = arguments.project_root.resolve()
    repository = RetrievalRepository(project_root)
    provider = OllamaEmbeddingProvider(model=arguments.model, host=arguments.host)
    visibility, snapshot_id = _resolve_visibility(repository, arguments)
    result = RetrievalIndexBuilder(repository, provider).build(
        visibility_policy=visibility,
        snapshot_id=snapshot_id,
        batch_size=arguments.batch_size,
    )
    print(
        json.dumps(
            {
                "event": "retrieval_index_built",
                "index_id": result.state.index_id,
                "visibility_policy": result.state.visibility_policy,
                "snapshot_id": result.state.snapshot_id,
                "embedding_model": result.state.embedding_model,
                "asset_set_digest": result.state.asset_set_digest,
                "document_count": result.state.document_count,
                "embedded_count": result.embedded_count,
                "cached_count": result.cached_count,
                "built_at": result.state.built_at,
            },
            ensure_ascii=False,
        )
    )


def _resolve_visibility(
    repository: RetrievalRepository,
    arguments: argparse.Namespace,
) -> tuple[VisibilityPolicy, str | None]:
    if arguments.visibility == "validated-draft":
        return VisibilityPolicy.VALIDATED_DRAFT, None
    if arguments.snapshot_id:
        return VisibilityPolicy.ACTIVE_SNAPSHOT, arguments.snapshot_id
    repository.migrate()
    with repository.registry.connect() as connection:
        row = connection.execute(
            """
            SELECT snapshot_id
            FROM registry_snapshot
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        raise RuntimeError(
            "no ACTIVE snapshot found; run scripts/activate_registry_assets.py first"
        )
    return VisibilityPolicy.ACTIVE_SNAPSHOT, str(row["snapshot_id"])


if __name__ == "__main__":
    main()
