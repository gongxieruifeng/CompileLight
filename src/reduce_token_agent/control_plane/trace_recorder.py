"""Structured runtime trace persistence with sensitive-data minimization."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from reduce_token_agent.trace_data.runtime_models import RuntimeExecutionStepRecord
from reduce_token_agent.trace_data.runtime_store import RuntimeTraceStore

_SENSITIVE_KEYS = re.compile(
    r"(password|passwd|token|secret|api[_-]?key|authorization|"
    r"chain.of.thought|reasoning|principal_id|user_id|identity_id|"
    r"customer_id|account_id|employee_id|phone|address|query$)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_LONG_NUMBER = re.compile(r"\b\d{12,19}\b")
_INLINE_SECRET = re.compile(
    r"(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)"
    r"\s*[:=]\s*[^\s,;，；]+"
)
_INLINE_SECRET_ZH = re.compile(r"(密码|令牌|密钥)\s*[:：=]\s*[^\s,;，；]+")
_TOKEN_ACCOUNTING_KEYS = {
    "input_tokens",
    "output_tokens",
    "total_duration_ns",
    "max_token_budget",
    "token_budget",
}


class ControlTraceRecorder:
    """Persist necessary decisions while omitting raw identity, secrets, and CoT."""

    def __init__(
        self,
        database_path: Path,
        migration_path: Path,
        trace_root: Path | None = None,
    ) -> None:
        self.database_path = database_path
        self.migration_path = migration_path
        data_root = (
            database_path.parent.parent
            if database_path.parent.name == "db"
            else database_path.parent
        )
        self.trace_root = trace_root or data_root / "traces/runtime/v1"
        self.store = RuntimeTraceStore(database_path, self.trace_root)

    def migrate(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(self.migration_path.read_text(encoding="utf-8"))
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(control_run)")
            }
            additions = {
                "trace_id": "TEXT",
                "safe_query": "TEXT",
                "failure_code": "TEXT",
                "trace_path": "TEXT",
            }
            for name, declaration in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE control_run ADD COLUMN {name} {declaration}"
                    )
            connection.execute(
                """
                UPDATE control_run
                SET trace_id = 'trace_run_' || substr(run_id, 5)
                WHERE trace_id IS NULL
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_control_run_trace_id
                ON control_run(trace_id)
                """
            )

    def start(
        self,
        *,
        run_id: str,
        query: str,
        tenant_id: str | None,
        principal_id: str | None,
    ) -> str:
        now = datetime.now(UTC).isoformat()
        trace_id = "trace_run_" + run_id.removeprefix("run_")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO control_run(
                    run_id, trace_id, tenant_id, principal_ref, query_ref,
                    safe_query, status, destinations_json, started_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'PLANNING', '[]', ?)
                """,
                (
                    run_id,
                    trace_id,
                    tenant_id,
                    _digest_ref("principal", principal_id or "missing"),
                    _digest_ref("query", query),
                    _sanitize_text(query),
                    now,
                ),
            )
        return trace_id

    def event(
        self,
        *,
        run_id: str,
        stage: str,
        event_type: str,
        payload: BaseModel | dict[str, Any],
    ) -> None:
        safe = _sanitize(
            payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
        )
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            run = connection.execute(
                "SELECT finished_at FROM control_run WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise LookupError(f"control run not found: {run_id}")
            if run[0] is not None:
                raise RuntimeError(f"control run trace is already finalized: {run_id}")
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM control_event WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            connection.execute(
                """
                INSERT INTO control_event(
                    event_id, run_id, sequence, stage, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "evt_" + secrets.token_hex(8),
                    run_id,
                    sequence,
                    stage,
                    event_type,
                    json.dumps(safe, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )

    def blueprint(
        self,
        *,
        run_id: str,
        proposal: BaseModel | None,
        compile_result: BaseModel | None,
        registry_view: BaseModel | None,
        repair_attempts: int,
    ) -> None:
        def encoded(value: BaseModel | None) -> str | None:
            if value is None:
                return None
            return json.dumps(
                _sanitize(value.model_dump(mode="json")),
                ensure_ascii=False,
                sort_keys=True,
            )

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO control_blueprint(
                    run_id, proposal_json, compile_result_json,
                    repair_attempts, registry_view_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    proposal_json = excluded.proposal_json,
                    compile_result_json = excluded.compile_result_json,
                    repair_attempts = excluded.repair_attempts,
                    registry_view_json = excluded.registry_view_json
                """,
                (
                    run_id,
                    encoded(proposal),
                    encoded(compile_result),
                    repair_attempts,
                    encoded(registry_view),
                ),
            )

    def execution_step(
        self,
        *,
        run_id: str,
        record: RuntimeExecutionStepRecord,
    ) -> None:
        """Record one future executor step using an extraction-ready contract."""
        event_type = {
            "STARTED": "step_started",
            "SUCCEEDED": "step_succeeded",
            "FAILED": "step_failed",
            "WAITING_HUMAN": "step_waiting_human",
        }[record.phase]
        self.event(
            run_id=run_id,
            stage="execution",
            event_type=event_type,
            payload=record,
        )

    def finish(
        self,
        *,
        run_id: str,
        task_id: str | None,
        status: str,
        mode: str,
        destinations: list[str],
    ) -> str:
        interrupted = status in {"PARTIAL", "WAITING_HUMAN"}
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE control_run
                SET task_id = ?, status = ?, mode = ?, destinations_json = ?,
                    finished_at = ?
                WHERE run_id = ?
                """,
                (
                    task_id,
                    status,
                    mode,
                    json.dumps(destinations),
                    None if interrupted else datetime.now(UTC).isoformat(),
                    run_id,
                ),
            )
        envelope, path = self.store.materialize(run_id)
        return f"trace://{envelope.trace_id}?path={path}"

    def fail(
        self,
        *,
        run_id: str,
        task_id: str | None,
        stage: str,
        failure_code: str,
        message: str,
    ) -> str:
        """Persist an unexpected failure and still materialize a reviewable trace."""
        self.event(
            run_id=run_id,
            stage=stage,
            event_type="failed",
            payload={
                "failure_code": failure_code,
                "message": message,
            },
        )
        self.event(
            run_id=run_id,
            stage="final_response",
            event_type="completed",
            payload={
                "run_id": run_id,
                "status": "FAILED",
                "mode": "REJECT",
                "answer": (
                    "任务执行失败，未生成成功结论。"
                    f"失败码：{failure_code}。"
                ),
                "result_items": [],
                "pending_step_ids": [],
                "failure_code": failure_code,
                "business_validated": False,
            },
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE control_run
                SET task_id = ?, status = 'FAILED', mode = 'REJECT',
                    destinations_json = '["SAFE_STOP"]', failure_code = ?,
                    finished_at = ?
                WHERE run_id = ?
                """,
                (
                    task_id,
                    failure_code,
                    datetime.now(UTC).isoformat(),
                    run_id,
                ),
            )
        envelope, path = self.store.materialize(run_id)
        return f"trace://{envelope.trace_id}?path={path}"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _digest_ref(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}:sha256:{digest}"


def _sanitize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _sanitize(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if (
                    _SENSITIVE_KEYS.search(str(key))
                    and str(key) not in _TOKEN_ACCOUNTING_KEYS
                )
                else _sanitize(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _sanitize_text(value: str) -> str:
    text = _INLINE_SECRET.sub(r"\1=[REDACTED]", value)
    text = _INLINE_SECRET_ZH.sub(r"\1=[REDACTED]", text)
    return _LONG_NUMBER.sub(
        "[NUMBER_REDACTED]",
        _EMAIL.sub("[EMAIL_REDACTED]", text),
    )
