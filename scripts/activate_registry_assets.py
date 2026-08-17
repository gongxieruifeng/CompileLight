#!/usr/bin/env python3
"""Promote all validated local Registry assets to ACTIVE and rebuild retrieval."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from reduce_token_agent.domain.capability import VisibilityPolicy
from reduce_token_agent.llm.embeddings import (
    HashingEmbeddingProvider,
    OllamaEmbeddingProvider,
)
from reduce_token_agent.registry.repository import RegistryRepository, utc_now
from reduce_token_agent.registry.retrieval_index import RetrievalIndexBuilder
from reduce_token_agent.registry.retrieval_repository import RetrievalRepository


def main() -> int:
    args = parse_args()
    project_root = args.project_root.resolve()
    registry = RegistryRepository(
        project_root / "data/db/registry.sqlite3",
        project_root / "migrations",
    )
    registry.migrate(include_retrieval=True)

    assets = _load_asset_health(registry)
    blocked = [
        asset
        for asset in assets
        if asset["validation_status"] != "PASS"
        or asset["runtime_status"] not in {"READY", "PLANNING_ONLY"}
        or asset["tested_at"] is None
    ]
    if blocked and not args.force:
        print(
            json.dumps(
                {
                    "event": "registry_activation_blocked",
                    "blocked_count": len(blocked),
                    "blocked_assets": blocked[:20],
                    "hint": "run scripts/verify_asset_runtime.py --domain <domain> --all --mark-tested first, or pass --force for a local-only override",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    asset_refs = [asset["asset_ref"] for asset in assets]
    snapshot_id, digest = _activate_snapshot(registry, asset_refs)
    index_result = _rebuild_index(
        project_root,
        snapshot_id=snapshot_id,
        embedding_provider=args.embedding_provider,
        model=args.model,
        host=args.host,
        batch_size=args.batch_size,
    )
    summary = registry.summary()
    print(
        json.dumps(
            {
                "event": "registry_assets_activated",
                "asset_count": summary["asset_count"],
                "status_counts": summary["status_counts"],
                "runtime_ready_count": summary["runtime_ready_count"],
                "planning_only_count": summary["planning_only_count"],
                "runtime_tested_count": summary["runtime_tested_count"],
                "snapshot_id": snapshot_id,
                "active_set_digest": digest,
                "retrieval_index": {
                    "index_id": index_result.state.index_id,
                    "visibility_policy": index_result.state.visibility_policy,
                    "snapshot_id": index_result.state.snapshot_id,
                    "embedding_model": index_result.state.embedding_model,
                    "document_count": index_result.state.document_count,
                    "embedded_count": index_result.embedded_count,
                    "cached_count": index_result.cached_count,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--model", default="qwen3-embedding:0.6b")
    parser.add_argument("--host", default="http://127.0.0.1:11434")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument(
        "--embedding-provider",
        choices=["ollama", "hashing"],
        default="ollama",
        help="ollama keeps the index compatible with the normal control plane; hashing is for isolated tests only",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="local-only override: activate even if an asset has not recorded tested_at",
    )
    return parser.parse_args()


def _load_asset_health(registry: RegistryRepository) -> list[dict[str, Any]]:
    with registry.connect() as connection:
        rows = connection.execute(
            """
            SELECT
                av.asset_ref,
                a.domain,
                a.kind,
                ar.status,
                ar.validation_status,
                rb.runtime_status,
                rb.tested_at
            FROM asset_version AS av
            JOIN asset AS a ON a.asset_id = av.asset_id
            JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
            JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
            ORDER BY a.domain, a.kind, av.asset_ref
            """
        ).fetchall()
    if not rows:
        raise RuntimeError("no Registry assets found; seed the Registry first")
    return [dict(row) for row in rows]


def _activate_snapshot(
    registry: RegistryRepository,
    asset_refs: list[str],
) -> tuple[str, str]:
    ordered = sorted(dict.fromkeys(asset_refs))
    digest = "sha256:" + hashlib.sha256(
        ("\n".join(ordered) + "\n").encode("utf-8")
    ).hexdigest()
    snapshot_id = "snapshot_active_" + digest.removeprefix("sha256:")[:16]
    timestamp = utc_now()
    placeholders = ",".join("?" for _ in ordered)
    with registry.connect() as connection:
        connection.execute(
            f"""
            UPDATE asset_release
            SET status = 'ACTIVE', updated_at = ?
            WHERE asset_ref IN ({placeholders})
            """,
            (timestamp, *ordered),
        )
        connection.execute(
            """
            INSERT INTO registry_snapshot(snapshot_id, active_set_digest, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(snapshot_id) DO UPDATE SET
                active_set_digest = excluded.active_set_digest
            """,
            (snapshot_id, digest, timestamp),
        )
        connection.execute(
            "DELETE FROM snapshot_member WHERE snapshot_id = ?",
            (snapshot_id,),
        )
        connection.executemany(
            """
            INSERT INTO snapshot_member(snapshot_id, asset_ref)
            VALUES (?, ?)
            """,
            [(snapshot_id, asset_ref) for asset_ref in ordered],
        )
    return snapshot_id, digest


def _rebuild_index(
    project_root: Path,
    *,
    snapshot_id: str,
    embedding_provider: str,
    model: str,
    host: str,
    batch_size: int,
):
    repository = RetrievalRepository(project_root)
    provider = (
        HashingEmbeddingProvider()
        if embedding_provider == "hashing"
        else OllamaEmbeddingProvider(model=model, host=host)
    )
    try:
        return RetrievalIndexBuilder(repository, provider).build(
            visibility_policy=VisibilityPolicy.ACTIVE_SNAPSHOT,
            snapshot_id=snapshot_id,
            batch_size=batch_size,
        )
    except sqlite3.Error:
        raise
    except Exception as exc:
        raise RuntimeError(
            "failed to rebuild ACTIVE_SNAPSHOT retrieval index; if the Ollama "
            "embedding model is unavailable, start Ollama or rerun with the "
            "same embedding model used by the control plane"
        ) from exc


if __name__ == "__main__":
    raise SystemExit(main())
