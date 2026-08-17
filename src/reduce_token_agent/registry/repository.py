"""SQLite repository for immutable assets, headers, graph edges, and evaluations."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from reduce_token_agent.registry.models import AssetDefinition, CapabilityEdge


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


class RegistryRepository:
    """Small synchronous repository used by seed scripts and tests."""

    def __init__(self, database_path: Path, migration_path: Path) -> None:
        self.database_path = database_path
        self.migration_path = migration_path

    def connect(self) -> sqlite3.Connection:
        """Open a configured SQLite connection."""
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migrate(self, *, include_retrieval: bool = False) -> None:
        """Apply Registry/Runtime migrations, optionally adding Retrieval schema."""
        migration_dir = (
            self.migration_path.parent
            if self.migration_path.is_file()
            else self.migration_path
        )
        migrations = sorted(migration_dir.glob("*.sql"))
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migration (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL
                )
                """
            )
            for migration in migrations:
                match = re.match(r"^(\d+)_.*\.sql$", migration.name)
                if match is None:
                    continue
                version = int(match.group(1))
                # Control trace storage has its own runtime database and must
                # never be applied to the Registry connection.
                if version >= 4 or (not include_retrieval and version >= 3):
                    continue
                already_applied = connection.execute(
                    "SELECT 1 FROM schema_migration WHERE version = ?",
                    (version,),
                ).fetchone()
                if already_applied is not None:
                    continue
                connection.executescript(migration.read_text(encoding="utf-8"))
                connection.execute(
                    """
                    INSERT INTO schema_migration(version, name, applied_at)
                    VALUES (?, ?, ?)
                    """,
                    (version, migration.name, utc_now()),
                )

    def register_asset(
        self,
        asset: AssetDefinition,
        *,
        artifact_path: Path,
        artifact_digest: str,
    ) -> None:
        """Insert one immutable DRAFT asset and its retrieval projection."""
        timestamp = utc_now()
        artifact_path_value = str(artifact_path)
        source_trace_ids = [evidence.trace_id for evidence in asset.source_evidence]
        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT artifact_digest, artifact_path
                FROM asset_version
                WHERE asset_ref = ?
                """,
                (asset.asset_ref,),
            ).fetchone()
            if existing is not None and (
                existing["artifact_digest"] != artifact_digest
                or existing["artifact_path"] != artifact_path_value
            ):
                raise ValueError(
                    f"immutable asset version conflict for {asset.asset_ref}"
                )

            connection.execute(
                """
                INSERT OR IGNORE INTO asset(asset_id, kind, owner, domain, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    asset.asset_id,
                    asset.kind.value,
                    asset.owner,
                    asset.domain,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO asset_version(
                    asset_ref,
                    asset_id,
                    version,
                    contract_json,
                    artifact_path,
                    artifact_digest,
                    source_trace_ids_json,
                    test_suite_ref,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.asset_ref,
                    asset.asset_id,
                    asset.version,
                    _json(asset.contract.model_dump(mode="json")),
                    artifact_path_value,
                    artifact_digest,
                    _json(source_trace_ids),
                    asset.test_suite_ref,
                    timestamp,
                ),
            )
            connection.execute(
                """
                INSERT INTO asset_release(
                    asset_ref,
                    status,
                    risk_level,
                    required_scopes_json,
                    validation_status,
                    updated_at
                )
                VALUES (?, ?, ?, ?, 'PASS', ?)
                ON CONFLICT(asset_ref) DO UPDATE SET
                    risk_level = excluded.risk_level,
                    required_scopes_json = excluded.required_scopes_json,
                    validation_status = 'PASS',
                    updated_at = excluded.updated_at
                """,
                (
                    asset.asset_ref,
                    asset.release_status.value,
                    asset.risk_level.value,
                    _json(asset.contract.required_scopes),
                    timestamp,
                ),
            )
            header = asset.route_header
            connection.execute(
                """
                INSERT INTO route_header(
                    asset_ref,
                    name,
                    summary,
                    recall_policy,
                    positive_triggers_json,
                    anti_triggers_json,
                    input_type_summary,
                    output_type_summary,
                    keywords_json,
                    metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_ref) DO UPDATE SET
                    name = excluded.name,
                    summary = excluded.summary,
                    recall_policy = excluded.recall_policy,
                    positive_triggers_json = excluded.positive_triggers_json,
                    anti_triggers_json = excluded.anti_triggers_json,
                    input_type_summary = excluded.input_type_summary,
                    output_type_summary = excluded.output_type_summary,
                    keywords_json = excluded.keywords_json,
                    metadata_json = excluded.metadata_json
                """,
                (
                    asset.asset_ref,
                    header.name,
                    header.summary,
                    asset.recall_policy.value,
                    _json(header.positive_triggers),
                    _json(header.anti_triggers),
                    header.input_type_summary,
                    header.output_type_summary,
                    _json(header.keywords),
                    _json(
                        {
                            "domain": asset.domain,
                            "kind": asset.kind.value,
                            "risk_level": asset.risk_level.value,
                        }
                    ),
                ),
            )
            evaluation_id = (
                "eval_" + asset.asset_id.replace(".", "_") + "_" + asset.version.replace(".", "_")
            )
            connection.execute(
                """
                INSERT INTO evaluation_run(
                    evaluation_id,
                    asset_ref,
                    suite_ref,
                    metrics_json,
                    verdict,
                    evaluated_at
                )
                VALUES (?, ?, ?, ?, 'PASS', ?)
                ON CONFLICT(evaluation_id) DO UPDATE SET
                    metrics_json = excluded.metrics_json,
                    verdict = 'PASS',
                    evaluated_at = excluded.evaluated_at
                """,
                (
                    evaluation_id,
                    asset.asset_ref,
                    asset.test_suite_ref,
                    _json(
                        {
                            "schema_valid": True,
                            "kind_boundary_valid": True,
                            "source_evidence_valid": True,
                            "artifact_digest_valid": True,
                            "runtime_behavior_tested": False,
                        }
                    ),
                    timestamp,
                ),
            )

    def register_runtime_binding(
        self,
        *,
        asset_ref: str,
        implementation_ref: str,
        execution_mode: str,
        policy_version: str,
        metadata_path: Path,
        metadata_digest: str,
        runtime_status: str,
        tested_at: str | None,
    ) -> None:
        """Persist the executable body binding separately from the asset Contract."""
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_binding(
                    asset_ref,
                    implementation_ref,
                    execution_mode,
                    policy_version,
                    metadata_path,
                    metadata_digest,
                    runtime_status,
                    tested_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_ref) DO UPDATE SET
                    implementation_ref = excluded.implementation_ref,
                    execution_mode = excluded.execution_mode,
                    policy_version = excluded.policy_version,
                    metadata_path = excluded.metadata_path,
                    metadata_digest = excluded.metadata_digest,
                    runtime_status = excluded.runtime_status,
                    tested_at = COALESCE(excluded.tested_at, runtime_binding.tested_at)
                """,
                (
                    asset_ref,
                    implementation_ref,
                    execution_mode,
                    policy_version,
                    str(metadata_path),
                    metadata_digest,
                    runtime_status,
                    tested_at,
                ),
            )

    def execution_record(self, asset_ref: str) -> sqlite3.Row | None:
        """Load one exact asset and its runtime binding without retrieval."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    av.asset_ref,
                    a.kind,
                    ar.status,
                    ar.validation_status,
                    rb.implementation_ref,
                    rb.execution_mode,
                    rb.policy_version,
                    rb.runtime_status,
                    rb.tested_at
                FROM asset_version AS av
                JOIN asset AS a ON a.asset_id = av.asset_id
                JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
                WHERE av.asset_ref = ?
                """,
                (asset_ref,),
            ).fetchone()
            return cast(sqlite3.Row | None, row)

    def asset_context(self, asset_ref: str) -> sqlite3.Row | None:
        """Load the Registry, release, and runtime context for one asset ref."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    av.asset_ref,
                    av.asset_id,
                    av.version,
                    a.kind,
                    a.domain,
                    ar.status,
                    ar.validation_status,
                    ar.risk_level,
                    rb.runtime_status,
                    rb.execution_mode,
                    rb.tested_at,
                    rh.name,
                    rh.summary
                FROM asset_version AS av
                JOIN asset AS a ON a.asset_id = av.asset_id
                JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                LEFT JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
                JOIN route_header AS rh ON rh.asset_ref = av.asset_ref
                WHERE av.asset_ref = ?
                """,
                (asset_ref,),
            ).fetchone()
            return cast(sqlite3.Row | None, row)

    def required_validator_ref(self, asset_ref: str) -> str | None:
        """Return the first validator required by one asset, if present."""
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT to_ref
                FROM capability_edge
                WHERE from_ref = ? AND edge_type = 'REQUIRES_VALIDATOR'
                ORDER BY to_ref
                LIMIT 1
                """,
                (asset_ref,),
            ).fetchone()
            if row is None:
                return None
            return cast(str, row[0])

    def asset_refs_for_domain(self, domain: str) -> list[str]:
        """Return all asset refs for one Registry domain ordered by ref."""
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT av.asset_ref
                FROM asset_version AS av
                JOIN asset AS a ON a.asset_id = av.asset_id
                WHERE a.domain = ?
                ORDER BY av.asset_ref
                """,
                (domain,),
            ).fetchall()
            return [cast(str, row[0]) for row in rows]

    def mark_runtime_tested(self, asset_ref: str, *, tested_at: str) -> None:
        """Record successful behavior verification for one immutable asset version."""
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE runtime_binding
                SET tested_at = ?, runtime_status = CASE
                    WHEN execution_mode = 'EXECUTABLE' THEN 'READY'
                    ELSE 'PLANNING_ONLY'
                END
                WHERE asset_ref = ?
                """,
                (tested_at, asset_ref),
            )
            if updated.rowcount != 1:
                raise ValueError(f"runtime binding not found for {asset_ref}")
            connection.execute(
                """
                UPDATE evaluation_run
                SET metrics_json = json_set(
                    metrics_json,
                    '$.runtime_behavior_tested',
                    json('true')
                ),
                    verdict = 'PASS',
                    evaluated_at = ?
                WHERE asset_ref = ?
                """,
                (tested_at, asset_ref),
            )

    def register_edges(self, edges: list[CapabilityEdge]) -> None:
        """Insert deterministic graph relationships after all assets exist."""
        with self.connect() as connection:
            for edge in edges:
                connection.execute(
                    """
                    INSERT INTO capability_edge(
                        from_ref,
                        to_ref,
                        edge_type,
                        adapter_ref,
                        evidence
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(from_ref, to_ref, edge_type) DO UPDATE SET
                        adapter_ref = excluded.adapter_ref,
                        evidence = excluded.evidence
                    """,
                    (
                        edge.from_ref,
                        edge.to_ref,
                        edge.edge_type.value,
                        edge.adapter_ref,
                        edge.evidence,
                    ),
                )

    def summary(self) -> dict[str, Any]:
        """Return counts used by verification and the review report."""
        with self.connect() as connection:
            kind_counts = {
                row["kind"]: row["count"]
                for row in connection.execute(
                    "SELECT kind, COUNT(*) AS count FROM asset GROUP BY kind ORDER BY kind"
                )
            }
            status_counts = {
                row["status"]: row["count"]
                for row in connection.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM asset_release
                    GROUP BY status
                    ORDER BY status
                    """
                )
            }
            return {
                "asset_count": connection.execute(
                    "SELECT COUNT(*) FROM asset_version"
                ).fetchone()[0],
                "kind_counts": kind_counts,
                "status_counts": status_counts,
                "validated_count": connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM asset_release
                    WHERE validation_status = 'PASS'
                    """
                ).fetchone()[0],
                "edge_count": connection.execute(
                    "SELECT COUNT(*) FROM capability_edge"
                ).fetchone()[0],
                "runtime_ready_count": connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM runtime_binding
                    WHERE runtime_status = 'READY'
                    """
                ).fetchone()[0],
                "planning_only_count": connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM runtime_binding
                    WHERE runtime_status = 'PLANNING_ONLY'
                    """
                ).fetchone()[0],
                "runtime_tested_count": connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM runtime_binding
                    WHERE tested_at IS NOT NULL
                    """
                ).fetchone()[0],
                "snapshot_count": connection.execute(
                    "SELECT COUNT(*) FROM registry_snapshot"
                ).fetchone()[0],
            }

    def asset_rows(self) -> list[sqlite3.Row]:
        """Return safe metadata rows for reporting."""
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        av.asset_ref,
                        a.kind,
                        rh.name,
                        rh.summary,
                        rh.recall_policy,
                        ar.status,
                        ar.validation_status,
                        ar.risk_level,
                        rb.runtime_status,
                        av.artifact_path,
                        av.artifact_digest
                    FROM asset_version AS av
                    JOIN asset AS a ON a.asset_id = av.asset_id
                    JOIN route_header AS rh ON rh.asset_ref = av.asset_ref
                    JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                    JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
                    ORDER BY a.kind, av.asset_ref
                    """
                )
            )

    def asset_rows_for_domain(self, domain: str) -> list[sqlite3.Row]:
        """Return safe metadata rows for one Registry domain."""
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT
                        av.asset_ref,
                        a.kind,
                        rh.name,
                        rh.summary,
                        rh.recall_policy,
                        ar.status,
                        ar.validation_status,
                        ar.risk_level,
                        rb.runtime_status,
                        av.artifact_path,
                        av.artifact_digest,
                        rb.metadata_path,
                        rb.metadata_digest,
                        rb.execution_mode,
                        rb.policy_version,
                        rb.tested_at
                    FROM asset_version AS av
                    JOIN asset AS a ON a.asset_id = av.asset_id
                    JOIN route_header AS rh ON rh.asset_ref = av.asset_ref
                    JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                    JOIN runtime_binding AS rb ON rb.asset_ref = av.asset_ref
                    WHERE a.domain = ?
                    ORDER BY a.kind, av.asset_ref
                    """,
                    (domain,),
                )
            )

    def summary_for_domain(self, domain: str) -> dict[str, Any]:
        """Return counts for one domain only."""
        with self.connect() as connection:
            kind_counts = {
                row["kind"]: row["count"]
                for row in connection.execute(
                    """
                    SELECT a.kind AS kind, COUNT(*) AS count
                    FROM asset_version AS av
                    JOIN asset AS a ON a.asset_id = av.asset_id
                    WHERE a.domain = ?
                    GROUP BY a.kind
                    ORDER BY a.kind
                    """,
                    (domain,),
                )
            }
            status_counts = {
                row["status"]: row["count"]
                for row in connection.execute(
                    """
                    SELECT ar.status AS status, COUNT(*) AS count
                    FROM asset_version AS av
                    JOIN asset AS a ON a.asset_id = av.asset_id
                    JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                    WHERE a.domain = ?
                    GROUP BY ar.status
                    ORDER BY ar.status
                    """,
                    (domain,),
                )
            }
            asset_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM asset_version AS av
                JOIN asset AS a ON a.asset_id = av.asset_id
                WHERE a.domain = ?
                """,
                (domain,),
            ).fetchone()[0]
            validated_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM asset_version AS av
                JOIN asset AS a ON a.asset_id = av.asset_id
                JOIN asset_release AS ar ON ar.asset_ref = av.asset_ref
                WHERE a.domain = ? AND ar.validation_status = 'PASS'
                """,
                (domain,),
            ).fetchone()[0]
            edge_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM capability_edge AS ce
                JOIN asset_version AS av ON av.asset_ref = ce.from_ref
                JOIN asset AS a ON a.asset_id = av.asset_id
                WHERE a.domain = ?
                """,
                (domain,),
            ).fetchone()[0]
            runtime_ready_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM runtime_binding AS rb
                JOIN asset_version AS av ON av.asset_ref = rb.asset_ref
                JOIN asset AS a ON a.asset_id = av.asset_id
                WHERE a.domain = ? AND rb.runtime_status = 'READY'
                """,
                (domain,),
            ).fetchone()[0]
            planning_only_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM runtime_binding AS rb
                JOIN asset_version AS av ON av.asset_ref = rb.asset_ref
                JOIN asset AS a ON a.asset_id = av.asset_id
                WHERE a.domain = ? AND rb.runtime_status = 'PLANNING_ONLY'
                """,
                (domain,),
            ).fetchone()[0]
            runtime_tested_count = connection.execute(
                """
                SELECT COUNT(*)
                FROM runtime_binding AS rb
                JOIN asset_version AS av ON av.asset_ref = rb.asset_ref
                JOIN asset AS a ON a.asset_id = av.asset_id
                WHERE a.domain = ? AND rb.tested_at IS NOT NULL
                """,
                (domain,),
            ).fetchone()[0]
            return {
                "asset_count": asset_count,
                "kind_counts": kind_counts,
                "status_counts": status_counts,
                "validated_count": validated_count,
                "edge_count": edge_count,
                "runtime_ready_count": runtime_ready_count,
                "planning_only_count": planning_only_count,
                "runtime_tested_count": runtime_tested_count,
                "snapshot_count": connection.execute(
                    "SELECT COUNT(*) FROM registry_snapshot"
                ).fetchone()[0],
            }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
