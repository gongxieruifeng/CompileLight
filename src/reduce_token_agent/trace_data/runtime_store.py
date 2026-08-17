"""Read runtime events and materialize an extraction-compatible trace envelope."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

from reduce_token_agent.trace_data.runtime_models import (
    RuntimeExtractionEvidence,
    RuntimeTraceEnvelope,
    RuntimeTraceEvent,
    RuntimeTraceGovernance,
    RuntimeTraceOutcome,
    RuntimeTracePlan,
    RuntimeTraceProvenance,
    RuntimeTraceTask,
)


class RuntimeTraceStore:
    """Build reviewable JSON projections from the runtime event database."""

    def __init__(self, database_path: Path, trace_root: Path) -> None:
        self.database_path = database_path
        self.trace_root = trace_root

    def materialize(self, identifier: str) -> tuple[RuntimeTraceEnvelope, Path]:
        """Load by trace_id or run_id, validate, and atomically refresh JSON."""
        envelope, started_at = self.load(identifier)
        day = started_at[:10]
        output_path = self.trace_root / "records" / day / f"{envelope.trace_id}.json"
        # The SQLite event log is canonical. A PARTIAL run can receive resume
        # events after its first projection, so returning an existing JSON
        # file would silently hide the continuation. Always refresh the
        # projection from the current event log.
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(
                envelope.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output_path)
        with self._connect() as connection:
            connection.execute(
                "UPDATE control_run SET trace_path = ? WHERE run_id = ?",
                (str(output_path), envelope.run_id),
            )
        return envelope, output_path

    def load(self, identifier: str) -> tuple[RuntimeTraceEnvelope, str]:
        """Load and validate a trace without rewriting its JSON projection."""
        identifier = identifier.split("?", 1)[0].removeprefix("trace://")
        with self._connect() as connection:
            run = connection.execute(
                """
                SELECT * FROM control_run
                WHERE run_id = ? OR trace_id = ?
                """,
                (identifier, identifier),
            ).fetchone()
            if run is None:
                raise LookupError(f"runtime trace not found: {identifier}")
            event_rows = connection.execute(
                """
                SELECT * FROM control_event
                WHERE run_id = ?
                ORDER BY sequence
                """,
                (run["run_id"],),
            ).fetchall()
            blueprint = connection.execute(
                "SELECT * FROM control_blueprint WHERE run_id = ?",
                (run["run_id"],),
            ).fetchone()

        events = [_event_from_row(row) for row in event_rows]
        normalized = next(
            (
                event.payload
                for event in events
                if event.stage == "normalize"
                and event.event_type == "completed"
                and "task_id" in event.payload
            ),
            {},
        )
        plan = RuntimeTracePlan(
            registry_view=_json_column(blueprint, "registry_view_json"),
            proposal=_json_column(blueprint, "proposal_json"),
            compile_result=_json_column(blueprint, "compile_result_json"),
            repair_attempts=(
                int(blueprint["repair_attempts"]) if blueprint is not None else 0
            ),
        )
        all_failure_codes = sorted(
            {
                code
                for event in events
                for code in event.failure_codes
            }
            | set(_compile_failure_codes(plan.compile_result))
            | ({str(run["failure_code"])} if run["failure_code"] else set())
        )
        observed_refs = sorted(
            {
                asset_ref
                for event in events
                for asset_ref in event.asset_refs
            }
            | set(_asset_refs(plan.proposal))
            | set(_asset_refs(plan.compile_result))
        )
        validated_refs = sorted(
            {
                asset_ref
                for event in events
                if _is_validated_execution(event)
                for asset_ref in event.asset_refs
            }
        )
        failed_events = [event for event in events if event.status == "FAILED"]
        business_validated = any(
            _contains_true(event.payload, {"business_validated", "validated_success"})
            for event in events
            if event.stage in {"validate_output", "finalize", "execution"}
        )
        execution_status = _execution_status(str(run["status"]), business_validated)
        candidate_status = _candidate_status(
            run_status=str(run["status"]),
            execution_status=execution_status,
            business_validated=business_validated,
        )
        quality_flags = _quality_flags(
            plan=plan,
            events=events,
            candidate_status=candidate_status,
            domains=cast(list[str], normalized.get("domain_hints", [])),
        )
        governance = RuntimeTraceGovernance(
            eligible_for_candidate_extraction=(
                candidate_status == "ELIGIBLE_VALIDATED_EXECUTION"
            ),
            allowed_uses=[
                "runtime_audit",
                "failure_analysis",
                "asset_candidate_mining_when_eligible",
                "replay_fixture_design",
            ],
            prohibited_uses=[
                "automatic_activation",
                "store_chain_of_thought",
                "claim_unexecuted_plan_as_business_success",
                "production_decisioning_without_human_review",
            ],
        )
        classification = cast(str | None, normalized.get("data_classification"))
        query_preview = cast(str, run["safe_query"] or "[QUERY_REFERENCE_ONLY]")
        if classification not in {"PUBLIC", "SYNTHETIC", "PUBLIC_SYNTHETIC"}:
            query_preview = cast(str, run["query_ref"])
        task = RuntimeTraceTask(
            task_id=cast(str | None, run["task_id"] or normalized.get("task_id")),
            tenant_id=cast(str | None, run["tenant_id"]),
            principal_ref=cast(str, run["principal_ref"]),
            query_preview=query_preview,
            requested_at=cast(str | None, normalized.get("requested_at")),
            domains=cast(list[str], normalized.get("domain_hints", [])),
            data_classification=classification,
            risk_level=cast(str | None, normalized.get("risk_level")),
            entities=cast(dict[str, Any], normalized.get("entities", {})),
            acceptance_criteria=cast(
                list[str],
                normalized.get("acceptance_criteria", []),
            ),
        )
        outcome = RuntimeTraceOutcome(
            status=cast(str, run["status"]),
            mode=cast(str | None, run["mode"]),
            destinations=cast(list[str], json.loads(run["destinations_json"])),
            failure_codes=all_failure_codes,
            failed_stage=failed_events[-1].stage if failed_events else None,
            execution_status=execution_status,
            business_validated=business_validated,
            summary=_outcome_summary(
                status=cast(str, run["status"]),
                mode=cast(str | None, run["mode"]),
                execution_status=execution_status,
                failure_codes=all_failure_codes,
            ),
        )
        envelope = RuntimeTraceEnvelope(
            trace_id=cast(str, run["trace_id"]),
            run_id=cast(str, run["run_id"]),
            task=task,
            timeline=events,
            plan=plan,
            outcome=outcome,
            extraction_evidence=RuntimeExtractionEvidence(
                source_run_ids=[cast(str, run["run_id"])],
                domains=task.domains,
                observed_asset_refs=observed_refs,
                validated_asset_refs=validated_refs,
                successful_stages=list(
                    dict.fromkeys(
                        event.stage for event in events if event.status == "SUCCESS"
                    )
                ),
                failed_stages=list(
                    dict.fromkeys(
                        event.stage for event in events if event.status == "FAILED"
                    )
                ),
                failure_codes=all_failure_codes,
                quality_flags=quality_flags,
                candidate_hint_status=candidate_status,
            ),
            provenance=RuntimeTraceProvenance(
                recorder="reduce_token_agent.control_trace_recorder",
                recorded_at=datetime.fromisoformat(
                    cast(str, run["finished_at"] or run["started_at"])
                ),
                source_database=str(self.database_path),
                event_count=len(events),
            ),
            governance=governance,
        )
        return envelope, cast(str, run["started_at"])

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


def _event_from_row(row: sqlite3.Row) -> RuntimeTraceEvent:
    payload = cast(dict[str, Any], json.loads(row["payload_json"]))
    event_type = cast(str, row["event_type"])
    lowered = event_type.lower()
    if any(token in lowered for token in ("failed", "error", "rejected")):
        status: Literal["SUCCESS", "FAILED", "INFORMATIONAL"] = "FAILED"
    elif any(
        token in lowered
        for token in ("completed", "success", "succeeded", "validated")
    ):
        status = "SUCCESS"
    else:
        status = "INFORMATIONAL"
    return RuntimeTraceEvent(
        event_id=cast(str, row["event_id"]),
        sequence=int(row["sequence"]),
        stage=cast(str, row["stage"]),
        event_type=event_type,
        status=status,
        created_at=datetime.fromisoformat(cast(str, row["created_at"])),
        failure_codes=sorted(_event_failure_codes(payload, status)),
        asset_refs=sorted(_asset_refs(payload)),
        payload=payload,
    )


def _json_column(row: sqlite3.Row | None, column: str) -> dict[str, Any] | None:
    if row is None or row[column] is None:
        return None
    return cast(dict[str, Any], json.loads(row[column]))


def _failure_codes(value: Any, *, parent_key: str = "") -> set[str]:
    codes: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"failure_code", "error_code"} and isinstance(item, str):
                codes.add(item)
            elif key == "errors" and isinstance(item, list):
                for error in item:
                    if isinstance(error, dict) and isinstance(error.get("code"), str):
                        codes.add(error["code"])
            codes.update(_failure_codes(item, parent_key=key))
    elif isinstance(value, list):
        for item in value:
            codes.update(_failure_codes(item, parent_key=parent_key))
    return codes


def _event_failure_codes(
    payload: dict[str, Any],
    status: Literal["SUCCESS", "FAILED", "INFORMATIONAL"],
) -> set[str]:
    """Do not mistake a successful business `error_code` fact for run failure."""
    if status == "FAILED":
        return _failure_codes(payload)
    code = payload.get("failure_code")
    return {code} if isinstance(code, str) and code else set()


def _compile_failure_codes(value: dict[str, Any] | None) -> list[str]:
    return sorted(_failure_codes(value or {}))


def _asset_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"asset_ref", "validator_ref", "compensation_ref"} and isinstance(
                item,
                str,
            ):
                refs.add(item)
            elif key in {"allowed_asset_refs", "validated_asset_refs"} and isinstance(
                item,
                list,
            ):
                refs.update(entry for entry in item if isinstance(entry, str))
            refs.update(_asset_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_asset_refs(item))
    return refs


def _contains_true(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            (key in keys and item is True) or _contains_true(item, keys)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_true(item, keys) for item in value)
    return False


def _is_validated_execution(event: RuntimeTraceEvent) -> bool:
    return (
        event.stage in {"validate_output", "execution", "finalize"}
        and event.status == "SUCCESS"
        and _contains_true(event.payload, {"business_validated", "validated_success"})
    )


def _execution_status(
    run_status: str,
    business_validated: bool,
) -> Literal["NOT_EXECUTED", "PARTIAL", "SUCCEEDED", "FAILED", "WAITING_HUMAN"]:
    if run_status == "FAILED":
        return "FAILED"
    if run_status == "WAITING_HUMAN":
        return "WAITING_HUMAN"
    if run_status == "PARTIAL":
        return "PARTIAL"
    if run_status == "SUCCEEDED" or business_validated:
        return "SUCCEEDED"
    return "NOT_EXECUTED"


def _candidate_status(
    *,
    run_status: str,
    execution_status: str,
    business_validated: bool,
) -> Literal[
    "ELIGIBLE_VALIDATED_EXECUTION",
    "INELIGIBLE_CONTROL_ONLY",
    "INELIGIBLE_FAILED_RUN",
    "INELIGIBLE_UNVALIDATED_EXECUTION",
]:
    if run_status == "FAILED" or execution_status == "FAILED":
        return "INELIGIBLE_FAILED_RUN"
    if business_validated and execution_status == "SUCCEEDED":
        return "ELIGIBLE_VALIDATED_EXECUTION"
    if execution_status == "NOT_EXECUTED":
        return "INELIGIBLE_CONTROL_ONLY"
    return "INELIGIBLE_UNVALIDATED_EXECUTION"


def _quality_flags(
    *,
    plan: RuntimeTracePlan,
    events: list[RuntimeTraceEvent],
    candidate_status: str,
    domains: list[str],
) -> list[str]:
    flags = [candidate_status]
    if not domains:
        flags.append("DOMAIN_NOT_IDENTIFIED")
    if plan.compile_result and not plan.compile_result.get("success", False):
        flags.append("COMPILE_FAILED")
    if not any(event.stage == "execution" for event in events):
        flags.append("NO_EXECUTION_EVENTS")
    if not any(event.stage == "validate_output" for event in events):
        flags.append("NO_BUSINESS_VALIDATION_EVIDENCE")
    return list(dict.fromkeys(flags))


def _outcome_summary(
    *,
    status: str,
    mode: str | None,
    execution_status: str,
    failure_codes: list[str],
) -> str:
    summary = (
        f"控制运行状态={status}，模式={mode or 'UNSET'}，"
        f"业务执行状态={execution_status}。"
    )
    if failure_codes:
        summary += "失败码：" + "、".join(failure_codes) + "。"
    if execution_status == "NOT_EXECUTED":
        summary += "当前 Trace 仅证明控制平台规划与路由，不证明业务能力执行成功。"
    return summary
