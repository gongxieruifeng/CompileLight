"""SQLite persistence boundary for Route Header retrieval."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np

from reduce_token_agent.domain.capability import VisibilityPolicy
from reduce_token_agent.registry.dense import decode_vector, encode_vector
from reduce_token_agent.registry.fts import build_match_query
from reduce_token_agent.registry.repository import RegistryRepository, utc_now


@dataclass(frozen=True, slots=True)
class RetrievalDocument:
    """One semantic index document projected from a Route Header."""

    asset_ref: str
    kind: str
    domain: str
    name: str
    summary: str
    recall_policy: str
    positive_triggers: list[str]
    anti_triggers: list[str]
    input_type_summary: str
    output_type_summary: str
    keywords: list[str]
    risk_level: str
    required_scopes: list[str]
    tenant_scope: str
    environment: str
    data_classification: str
    search_text: str
    embedding_text: str
    content_digest: str


@dataclass(frozen=True, slots=True)
class IndexState:
    """Current immutable description of the rebuilt local index."""

    index_id: str
    visibility_policy: str
    snapshot_id: str | None
    embedding_model: str
    asset_set_digest: str
    document_count: int
    built_at: str


@dataclass(frozen=True, slots=True)
class SparseHit:
    asset_ref: str
    score: float


@dataclass(frozen=True, slots=True)
class GraphHit:
    parent_ref: str
    asset_ref: str
    kind: str
    edge_type: str
    evidence: str


class RetrievalRepository:
    """Repository dedicated to retrieval indexes and detail resolution."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.database_path = project_root / "data/db/registry.sqlite3"
        self._registry = RegistryRepository(
            self.database_path,
            project_root / "migrations",
        )

    def migrate(self) -> None:
        self._registry.migrate(include_retrieval=True)

    def eligible_documents(
        self,
        *,
        visibility_policy: VisibilityPolicy,
        snapshot_id: str | None,
    ) -> list[RetrievalDocument]:
        """Return only visible ordinary or planning-prior Headers."""
        where, parameters = _visibility_clause(visibility_policy, snapshot_id)
        query = f"""
            SELECT
                av.asset_ref,
                a.kind,
                a.domain,
                rh.name,
                rh.summary,
                rh.recall_policy,
                rh.positive_triggers_json,
                rh.anti_triggers_json,
                rh.input_type_summary,
                rh.output_type_summary,
                rh.keywords_json,
                ar.risk_level,
                ar.required_scopes_json,
                av.contract_json
            FROM asset_version AS av
            JOIN asset AS a ON a.asset_id = av.asset_id
            JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
            JOIN route_header AS rh ON rh.asset_ref = av.asset_ref
            JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
            {where}
              AND rh.recall_policy IN ('ORDINARY', 'PLANNING_PRIOR')
            ORDER BY av.asset_ref
        """
        with self._registry.connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        documents: list[RetrievalDocument] = []
        for row in rows:
            positive = cast(list[str], json.loads(row["positive_triggers_json"]))
            anti = cast(list[str], json.loads(row["anti_triggers_json"]))
            keywords = cast(list[str], json.loads(row["keywords_json"]))
            contract = cast(dict[str, object], json.loads(row["contract_json"]))
            embedding_text = "\n".join(
                [
                    f"名称：{row['name']}",
                    f"说明：{row['summary']}",
                    f"适用任务：{'；'.join(positive)}",
                    f"关键词：{'；'.join(keywords)}",
                    f"输入：{row['input_type_summary']}",
                    f"输出：{row['output_type_summary']}",
                    f"领域：{row['domain']}",
                    f"类型：{row['kind']}",
                ]
            )
            content_digest = "sha256:" + hashlib.sha256(
                embedding_text.encode("utf-8")
            ).hexdigest()
            documents.append(
                RetrievalDocument(
                    asset_ref=cast(str, row["asset_ref"]),
                    kind=cast(str, row["kind"]),
                    domain=cast(str, row["domain"]),
                    name=cast(str, row["name"]),
                    summary=cast(str, row["summary"]),
                    recall_policy=cast(str, row["recall_policy"]),
                    positive_triggers=positive,
                    anti_triggers=anti,
                    input_type_summary=cast(str, row["input_type_summary"]),
                    output_type_summary=cast(str, row["output_type_summary"]),
                    keywords=keywords,
                    risk_level=cast(str, row["risk_level"]),
                    required_scopes=cast(
                        list[str], json.loads(row["required_scopes_json"])
                    ),
                    tenant_scope=str(contract["tenant_scope"]),
                    environment=str(contract["environment"]),
                    data_classification=str(contract["data_classification"]),
                    search_text="",
                    embedding_text=embedding_text,
                    content_digest=content_digest,
                )
            )
        return documents

    def cached_embeddings(
        self,
        documents: list[RetrievalDocument],
        *,
        model: str,
    ) -> dict[str, np.ndarray]:
        """Reuse vectors only when model and indexed content are unchanged."""
        expected = {document.asset_ref: document.content_digest for document in documents}
        if not expected:
            return {}
        placeholders = ",".join("?" for _ in expected)
        with self._registry.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT asset_ref, embedding_dim, embedding_blob, content_digest
                FROM retrieval_embedding
                WHERE embedding_model = ?
                  AND asset_ref IN ({placeholders})
                """,
                (model, *expected),
            ).fetchall()
        return {
            cast(str, row["asset_ref"]): decode_vector(
                cast(bytes, row["embedding_blob"]),
                cast(int, row["embedding_dim"]),
            )
            for row in rows
            if expected[cast(str, row["asset_ref"])]
            == cast(str, row["content_digest"])
        }

    def replace_index(
        self,
        documents: list[RetrievalDocument],
        embeddings: dict[str, np.ndarray],
        *,
        visibility_policy: VisibilityPolicy,
        snapshot_id: str | None,
        embedding_model: str,
    ) -> IndexState:
        """Atomically replace the current FTS/vector projection."""
        refs = [document.asset_ref for document in documents]
        asset_set_digest = "sha256:" + hashlib.sha256(
            "\n".join(refs).encode("utf-8")
        ).hexdigest()
        index_material = (
            f"{visibility_policy.value}|{snapshot_id or '-'}|"
            f"{embedding_model}|{asset_set_digest}"
        )
        index_id = "retrieval_" + hashlib.sha256(
            index_material.encode("utf-8")
        ).hexdigest()[:20]
        built_at = utc_now()
        with self._registry.connect() as connection:
            connection.execute("DELETE FROM route_header_fts")
            for document in documents:
                connection.execute(
                    """
                    INSERT INTO route_header_fts(asset_ref, search_text)
                    VALUES (?, ?)
                    """,
                    (document.asset_ref, document.search_text),
                )
                vector = embeddings[document.asset_ref]
                connection.execute(
                    """
                    INSERT INTO retrieval_embedding(
                        asset_ref,
                        embedding_model,
                        embedding_dim,
                        embedding_blob,
                        content_digest,
                        indexed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_ref) DO UPDATE SET
                        embedding_model = excluded.embedding_model,
                        embedding_dim = excluded.embedding_dim,
                        embedding_blob = excluded.embedding_blob,
                        content_digest = excluded.content_digest,
                        indexed_at = excluded.indexed_at
                    """,
                    (
                        document.asset_ref,
                        embedding_model,
                        int(vector.shape[0]),
                        encode_vector(vector),
                        document.content_digest,
                        built_at,
                    ),
                )
            if refs:
                placeholders = ",".join("?" for _ in refs)
                connection.execute(
                    f"DELETE FROM retrieval_embedding WHERE asset_ref NOT IN ({placeholders})",
                    refs,
                )
            else:
                connection.execute("DELETE FROM retrieval_embedding")
            connection.execute(
                """
                INSERT INTO retrieval_index_state(
                    index_id,
                    visibility_policy,
                    snapshot_id,
                    embedding_model,
                    asset_set_digest,
                    document_count,
                    built_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(index_id) DO UPDATE SET
                    document_count = excluded.document_count,
                    built_at = excluded.built_at
                """,
                (
                    index_id,
                    visibility_policy.value,
                    snapshot_id,
                    embedding_model,
                    asset_set_digest,
                    len(documents),
                    built_at,
                ),
            )
        return IndexState(
            index_id=index_id,
            visibility_policy=visibility_policy.value,
            snapshot_id=snapshot_id,
            embedding_model=embedding_model,
            asset_set_digest=asset_set_digest,
            document_count=len(documents),
            built_at=built_at,
        )

    def current_index(self) -> IndexState:
        """Load the most recently built retrieval index."""
        with self._registry.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM retrieval_index_state
                ORDER BY built_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("retrieval index is not built")
        return IndexState(**dict(row))

    def header_documents(self) -> dict[str, RetrievalDocument]:
        """Load current visible Headers using the index visibility declaration."""
        state = self.current_index()
        return {
            document.asset_ref: document
            for document in self.eligible_documents(
                visibility_policy=VisibilityPolicy(state.visibility_policy),
                snapshot_id=state.snapshot_id,
            )
        }

    def sparse_search(self, query_text: str, *, limit: int = 50) -> list[SparseHit]:
        """Search the current FTS5 projection."""
        match_query = build_match_query(query_text)
        if match_query is None:
            return []
        with self._registry.connect() as connection:
            rows = connection.execute(
                """
                SELECT asset_ref, bm25(route_header_fts) AS distance
                FROM route_header_fts
                WHERE route_header_fts MATCH ?
                ORDER BY distance, asset_ref
                LIMIT ?
                """,
                (match_query, limit),
            ).fetchall()
        return [
            SparseHit(
                asset_ref=cast(str, row["asset_ref"]),
                score=-cast(float, row["distance"]),
            )
            for row in rows
        ]

    def dense_vectors(self) -> list[tuple[str, np.ndarray]]:
        """Load the small current vector set for NumPy cosine ranking."""
        state = self.current_index()
        with self._registry.connect() as connection:
            rows = connection.execute(
                """
                SELECT asset_ref, embedding_dim, embedding_blob
                FROM retrieval_embedding
                WHERE embedding_model = ?
                ORDER BY asset_ref
                """,
                (state.embedding_model,),
            ).fetchall()
        return [
            (
                cast(str, row["asset_ref"]),
                decode_vector(
                    cast(bytes, row["embedding_blob"]),
                    cast(int, row["embedding_dim"]),
                ),
            )
            for row in rows
        ]

    def graph_expand(
        self,
        parent_refs: list[str],
        *,
        visibility_policy: VisibilityPolicy,
        snapshot_id: str | None,
        tenant_id: str = "local",
        environment: str = "local",
        data_classification: str = "SYNTHETIC",
    ) -> list[GraphHit]:
        """Expand explicit dependencies and validators by exactly one hop."""
        if not parent_refs:
            return []
        placeholders = ",".join("?" for _ in parent_refs)
        if visibility_policy is VisibilityPolicy.VALIDATED_DRAFT:
            visibility_join = ""
            visibility_predicate = "AND ar.status = 'DRAFT'"
            parameters: tuple[str, ...] = (
                *parent_refs,
                tenant_id,
                environment,
                data_classification,
            )
        else:
            if snapshot_id is None:
                raise ValueError("ACTIVE_SNAPSHOT graph expansion requires snapshot_id")
            visibility_join = (
                "JOIN snapshot_member AS sm ON sm.asset_ref = av.asset_ref"
            )
            visibility_predicate = (
                "AND ar.status = 'ACTIVE' AND sm.snapshot_id = ?"
            )
            parameters = (
                *parent_refs,
                tenant_id,
                environment,
                data_classification,
                snapshot_id,
            )
        with self._registry.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT
                    ce.from_ref,
                    ce.to_ref,
                    ce.edge_type,
                    ce.evidence,
                    a.kind
                FROM capability_edge AS ce
                JOIN asset_version AS av ON av.asset_ref = ce.to_ref
                JOIN asset AS a ON a.asset_id = av.asset_id
                JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
                {visibility_join}
                WHERE ce.from_ref IN ({placeholders})
                  AND ce.edge_type IN (
                      'DEPENDS_ON',
                      'REQUIRES_VALIDATOR',
                      'COMPATIBLE_VIA_ADAPTER'
                  )
                  AND ar.validation_status = 'PASS'
                  AND rb.tested_at IS NOT NULL
                  AND rb.runtime_status IN ('READY', 'PLANNING_ONLY')
                  AND json_extract(av.contract_json, '$.tenant_scope') = ?
                  AND json_extract(av.contract_json, '$.environment') = ?
                  AND json_extract(av.contract_json, '$.data_classification') = ?
                  {visibility_predicate}
                ORDER BY ce.from_ref, ce.edge_type, ce.to_ref
                """,
                parameters,
            ).fetchall()
        return [
            GraphHit(
                parent_ref=cast(str, row["from_ref"]),
                asset_ref=cast(str, row["to_ref"]),
                kind=cast(str, row["kind"]),
                edge_type=cast(str, row["edge_type"]),
                evidence=cast(str, row["evidence"]),
            )
            for row in rows
        ]

    def detail_row(self, asset_ref: str) -> sqlite3.Row | None:
        """Load the second-layer Contract and runtime call data."""
        with self._registry.connect() as connection:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    """
                    SELECT
                        av.asset_ref,
                        av.asset_id,
                        av.version,
                        av.contract_json,
                        av.artifact_path,
                        av.artifact_digest,
                        a.kind,
                        a.domain,
                        ar.status,
                        ar.validation_status,
                        rh.name,
                        rh.summary,
                        rh.positive_triggers_json,
                        rh.anti_triggers_json,
                        rh.keywords_json,
                        rb.implementation_ref,
                        rb.execution_mode,
                        rb.policy_version,
                        rb.runtime_status,
                        rb.tested_at,
                        rb.metadata_path,
                        rb.metadata_digest
                    FROM asset_version AS av
                    JOIN asset AS a ON a.asset_id = av.asset_id
                    JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                    JOIN route_header AS rh ON rh.asset_ref = av.asset_ref
                    JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
                    WHERE av.asset_ref = ?
                    """,
                    (asset_ref,),
                ).fetchone(),
            )

    def header_row(self, asset_ref: str) -> sqlite3.Row | None:
        """Load one compact Header, including graph-only assets."""
        with self._registry.connect() as connection:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    """
                    SELECT
                        av.asset_ref,
                        a.kind,
                        a.domain,
                        rh.name,
                        rh.summary,
                        rh.recall_policy,
                        rh.input_type_summary,
                        rh.output_type_summary,
                        rh.positive_triggers_json,
                        rh.anti_triggers_json,
                        rh.keywords_json,
                        ar.risk_level,
                        ar.required_scopes_json
                    FROM asset_version AS av
                    JOIN asset AS a ON a.asset_id = av.asset_id
                    JOIN route_header AS rh ON rh.asset_ref = av.asset_ref
                    JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                    WHERE av.asset_ref = ?
                    """,
                    (asset_ref,),
                ).fetchone(),
            )

    def related_rows(self, asset_ref: str) -> list[sqlite3.Row]:
        with self._registry.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT ce.to_ref, ce.edge_type, ce.evidence, a.kind
                    FROM capability_edge AS ce
                    JOIN asset_version AS av ON av.asset_ref = ce.to_ref
                    JOIN asset AS a ON a.asset_id = av.asset_id
                    WHERE ce.from_ref = ?
                    ORDER BY ce.edge_type, ce.to_ref
                    """,
                    (asset_ref,),
                )
            )

    @property
    def registry(self) -> RegistryRepository:
        return self._registry


def _visibility_clause(
    policy: VisibilityPolicy,
    snapshot_id: str | None,
) -> tuple[str, tuple[str, ...]]:
    if policy is VisibilityPolicy.VALIDATED_DRAFT:
        return (
            """
            WHERE ar.status = 'DRAFT'
              AND ar.validation_status = 'PASS'
              AND rb.tested_at IS NOT NULL
              AND rb.runtime_status IN ('READY', 'PLANNING_ONLY')
            """,
            (),
        )
    if snapshot_id is None:
        raise ValueError("ACTIVE_SNAPSHOT visibility requires snapshot_id")
    return (
        """
        JOIN snapshot_member AS sm ON sm.asset_ref = av.asset_ref
        WHERE sm.snapshot_id = ?
          AND ar.status = 'ACTIVE'
          AND ar.validation_status = 'PASS'
          AND rb.tested_at IS NOT NULL
          AND rb.runtime_status IN ('READY', 'PLANNING_ONLY')
        """,
        (snapshot_id,),
    )
