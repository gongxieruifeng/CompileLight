"""Runtime Ledger separated from LangGraph checkpoint persistence."""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from reduce_token_agent.domain.runtime import ExecutionRunResult
from reduce_token_agent.trace_data.runtime_models import RuntimeExecutionStepRecord


class RuntimeLedger:
    """Persist execution attempts, summaries, state changes, and token usage."""

    def __init__(self, database_path: Path, migration_path: Path) -> None:
        self.database_path = database_path
        self.migration_path = migration_path

    def migrate(self) -> None:
        with self._connect() as connection:
            connection.executescript(self.migration_path.read_text(encoding="utf-8"))
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(execution_step_attempt)"
                )
            }
            if "validated_asset_refs_json" not in columns:
                connection.execute(
                    """
                    ALTER TABLE execution_step_attempt
                    ADD COLUMN validated_asset_refs_json TEXT NOT NULL DEFAULT '[]'
                    """
                )

    def start_run(self, *, run_id: str, thread_id: str, blueprint_id: str) -> None:
        self.migrate()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO execution_run(
                    run_id, thread_id, blueprint_id, status, started_at
                ) VALUES (?, ?, ?, 'RUNNING', ?)
                """,
                (run_id, thread_id, blueprint_id, _now()),
            )

    def resume_run(self, *, run_id: str, blueprint_id: str) -> None:
        """Reopen an existing interrupted run without creating a second run."""
        self.migrate()
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE execution_run
                SET blueprint_id = ?, status = 'RUNNING', finished_at = NULL
                WHERE run_id = ?
                """,
                (blueprint_id, run_id),
            ).rowcount
        if updated == 0:
            raise LookupError(f"execution run not found for resume: {run_id}")

    def record_step(self, run_id: str, record: RuntimeExecutionStepRecord) -> None:
        payload = record.model_dump(mode="json")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO execution_step_attempt(
                    run_id, step_id, attempt_number, phase, subgoal_id,
                    executor_kind, operation_key, asset_ref, validator_ref,
                    validated_asset_refs_json,
                    input_refs_json, output_artifact_refs_json,
                    input_summary_json, output_summary_json, validation_status,
                    business_validated, failure_code, side_effect,
                    idempotency_key_ref, decision_summary, duration_ns,
                    input_tokens, output_tokens, recorded_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    run_id,
                    record.step_id,
                    record.attempt_number,
                    record.phase,
                    record.subgoal_id,
                    record.executor_kind,
                    record.operation_key,
                    record.asset_ref,
                    record.validator_ref,
                    json.dumps(payload["validated_asset_refs"], ensure_ascii=False),
                    json.dumps(payload["input_refs"], ensure_ascii=False),
                    json.dumps(payload["output_artifact_refs"], ensure_ascii=False),
                    json.dumps(payload["input_safe_summary"], ensure_ascii=False),
                    json.dumps(payload["output_safe_summary"], ensure_ascii=False),
                    record.validation_status,
                    int(record.business_validated),
                    record.failure_code,
                    record.side_effect,
                    record.idempotency_key_ref,
                    record.decision_summary,
                    record.duration_ns,
                    record.input_tokens,
                    record.output_tokens,
                    _now(),
                ),
            )

    def record_token_usage(
        self,
        *,
        run_id: str,
        stage: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        attempts: int,
        estimated: bool,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO execution_token_usage(
                    usage_id, run_id, stage, model, input_tokens, output_tokens,
                    attempts, estimated, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "usage_" + secrets.token_hex(8),
                    run_id,
                    stage,
                    model,
                    input_tokens,
                    output_tokens,
                    attempts,
                    int(estimated),
                    _now(),
                ),
            )

    def finish_run(self, result: ExecutionRunResult) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE execution_run
                SET status = ?, placeholder_step_count = ?,
                    business_validated = ?, input_tokens = ?,
                    output_tokens = ?, result_json = ?, finished_at = ?
                WHERE run_id = ?
                """,
                (
                    result.status,
                    len(result.placeholder_step_ids),
                    int(result.business_validated),
                    result.input_tokens,
                    result.output_tokens,
                    json.dumps(result.model_dump(mode="json"), ensure_ascii=False),
                    _now(),
                    result.run_id,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _now() -> str:
    return datetime.now(UTC).isoformat()
