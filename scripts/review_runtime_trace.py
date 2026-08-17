"""Generate a JSON and Markdown review from one runtime trace ID or run ID."""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer

from reduce_token_agent.control_plane.trace_recorder import ControlTraceRecorder
from reduce_token_agent.trace_data.review import RuntimeTraceReviewWriter
from reduce_token_agent.trace_data.runtime_models import RuntimeTraceEnvelope

app = typer.Typer(add_completion=False)
_EXTERNAL_WRITE_CLAIM = re.compile(
    r"(?:已经|已)(?:成功)?(?:提交|发送|通知|创建|注册|更新|归档|冻结|修改|写入|移交)"
    r"|(?:正式提交|完成提交)"
)


@app.command()
def review(
    identifier: str = typer.Argument(
        ...,
        help="trace_run_<16 hex> or run_<16 hex>",
    ),
    database: Path | None = typer.Option(  # noqa: B008
        None,
        help="Override runtime SQLite path.",
    ),
    output_root: Path | None = typer.Option(  # noqa: B008
        None,
        help="Override review report root.",
    ),
) -> None:
    """Materialize and review one real runtime trace."""
    project_root = Path(__file__).resolve().parents[1]
    database_path = database or project_root / "data/db/runtime.sqlite3"
    trace_root = (
        project_root / "data/traces/runtime/v1"
        if database is None
        else database_path.parent / "traces/runtime/v1"
    )
    recorder = ControlTraceRecorder(
        database_path,
        project_root / "migrations/004_control_trace.sql",
        trace_root,
    )
    recorder.migrate()
    envelope, raw_trace_path = recorder.store.materialize(identifier)
    writer = RuntimeTraceReviewWriter(
        output_root or project_root / "data/reports/trace_review"
    )
    markdown_path, json_path = writer.write(envelope)
    final_response = latest_final_response(envelope)
    consistency = final_response_consistency(envelope, final_response)
    quality_flags = final_response_quality_flags(envelope, final_response)
    typer.echo(
        json.dumps(
            {
                "event": "runtime_trace_review_ready",
                "trace_id": envelope.trace_id,
                "run_id": envelope.run_id,
                "status": envelope.outcome.status,
                "execution_status": envelope.outcome.execution_status,
                "eligible_for_candidate_extraction": (
                    envelope.governance.eligible_for_candidate_extraction
                ),
                "final_response_present": final_response is not None,
                "final_response_event_count": final_response_event_count(envelope),
                "final_response_status": (
                    final_response.get("status")
                    if final_response is not None
                    else None
                ),
                "final_response_answer": (
                    final_response.get("answer")
                    if final_response is not None
                    else None
                ),
                "final_response_generation_method": (
                    final_response.get("generation_method")
                    if final_response is not None
                    else None
                ),
                "final_response_evidence_step_ids": (
                    final_response.get("evidence_step_ids", [])
                    if final_response is not None
                    else []
                ),
                "final_response_limitations": (
                    final_response.get("limitations", [])
                    if final_response is not None
                    else []
                ),
                "user_input_grounded": (
                    final_response.get("user_input_grounded")
                    if final_response is not None
                    else None
                ),
                "external_write_executed": (
                    final_response.get("external_write_executed")
                    if final_response is not None
                    else None
                ),
                "pending_human_step_ids": (
                    final_response.get("pending_step_ids", [])
                    if final_response is not None
                    else []
                ),
                "final_response_consistency": consistency,
                "final_response_quality_flags": quality_flags,
                "resume_quality_flags": resume_quality_flags(envelope),
                "raw_trace_path": str(raw_trace_path),
                "markdown_review_path": str(markdown_path),
                "json_review_path": str(json_path),
            },
            ensure_ascii=False,
        )
    )


def latest_final_response(
    envelope: RuntimeTraceEnvelope,
) -> dict[str, object] | None:
    """Return the last structured final response, if this Trace has one."""
    responses = [
        event.payload
        for event in envelope.timeline
        if event.stage == "final_response"
        and event.event_type == "completed"
    ]
    return responses[-1] if responses else None


def final_response_event_count(envelope: RuntimeTraceEnvelope) -> int:
    """Count all initial/resumed final-response projections."""
    return sum(
        event.stage == "final_response"
        and event.event_type == "completed"
        for event in envelope.timeline
    )


def final_response_consistency(
    envelope: RuntimeTraceEnvelope,
    response: dict[str, object] | None,
) -> list[str]:
    """Check that the final reply agrees with the persisted Trace outcome."""
    if response is None:
        return ["FINAL_RESPONSE_MISSING"]
    expected_status = envelope.outcome.status
    observed_status = response.get("status")
    issues: list[str] = []
    if observed_status != expected_status:
        issues.append("FINAL_RESPONSE_STATUS_MISMATCH")
    pending = response.get("pending_step_ids")
    if expected_status == "PARTIAL" and (
        not isinstance(pending, list) or not pending
    ):
        issues.append("PARTIAL_RESPONSE_PENDING_STEPS_MISSING")
    if expected_status == "SUCCEEDED" and isinstance(pending, list) and pending:
        issues.append("SUCCESS_RESPONSE_HAS_PENDING_STEPS")
    answer = response.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        issues.append("FINAL_RESPONSE_ANSWER_MISSING")
    if (
        any(
            event.stage == "human_interaction"
            and event.event_type == "human_answer_received"
            for event in envelope.timeline
        )
        and final_response_event_count(envelope) < 2
    ):
        issues.append("HUMAN_RESUME_FINAL_RESPONSE_MISSING")
    if (
        response.get("generation_method") == "LLM_GROUNDED"
        and not any(
            event.stage == "final_response"
            and event.event_type == "llm_usage"
            for event in envelope.timeline
        )
    ):
        issues.append("FINAL_RESPONSE_TOKEN_USAGE_MISSING")
    return issues or ["CONSISTENT"]


def final_response_quality_flags(
    envelope: RuntimeTraceEnvelope,
    response: dict[str, object] | None,
) -> list[str]:
    """Expose answer-quality caveats separately from structural consistency."""
    if response is None:
        return ["FINAL_RESPONSE_NOT_REVIEWABLE"]
    flags: list[str] = []
    legacy_sample_input = any(
        "SAMPLE" in str(step.get("input_source", ""))
        for event in envelope.timeline
        if event.stage == "execution"
        and event.event_type == "execution_completed"
        for step in (
            event.payload.get("step_results", [])
            if isinstance(event.payload.get("step_results"), list)
            else []
        )
        if isinstance(step, dict)
    )
    if (
        response.get("user_input_grounded") is False
        or response.get("user_input_grounded") is None
        and legacy_sample_input
    ):
        flags.append("USER_INPUT_NOT_GROUNDED")
    if response.get("business_validated") is False:
        flags.append("BUSINESS_RESULT_NOT_VALIDATED")
    rejection = response.get("generation_rejection_code")
    if isinstance(rejection, str) and rejection:
        flags.append(rejection)
    proposal = envelope.plan.proposal or {}
    proposal_steps = proposal.get("steps", [])
    external_write_planned = (
        isinstance(proposal_steps, list)
        and any(
            isinstance(step, dict)
            and step.get("side_effect") == "LOCAL_WRITE"
            for step in proposal_steps
        )
    )
    external_write_executed = response.get("external_write_executed")
    if external_write_executed is False or (
        external_write_executed is None and not external_write_planned
    ):
        flags.append("NO_EXTERNAL_WRITE_EXECUTED")
        answer = response.get("answer")
        if isinstance(answer, str) and _EXTERNAL_WRITE_CLAIM.search(answer):
            flags.append("FINAL_RESPONSE_EXTERNAL_WRITE_CLAIM")
    return flags or ["NONE"]


def resume_quality_flags(envelope: RuntimeTraceEnvelope) -> list[str]:
    """Detect whether a resumed run repeated already completed steps."""
    resume_sequences = [
        event.sequence
        for event in envelope.timeline
        if event.stage == "execution"
        and event.event_type == "execution_resumed"
    ]
    if not resume_sequences:
        return ["NOT_APPLICABLE"]
    first_resume = min(resume_sequences)
    before = {
        str(event.payload.get("step_id"))
        for event in envelope.timeline
        if event.sequence < first_resume
        and event.stage == "execution"
        and event.event_type == "step_started"
        and event.payload.get("step_id")
    }
    after = {
        str(event.payload.get("step_id"))
        for event in envelope.timeline
        if event.sequence > first_resume
        and event.stage == "execution"
        and event.event_type == "step_started"
        and event.payload.get("step_id")
    }
    repeated = sorted(before & after)
    return (
        ["RESUME_REEXECUTED_STEPS:" + ",".join(repeated)]
        if repeated
        else ["NONE"]
    )


if __name__ == "__main__":
    app()
