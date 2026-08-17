"""Framework-light UI handlers that call only the Application Facade."""

from __future__ import annotations

import json
from typing import Any

from reduce_token_agent.application.facade import ApplicationFacade
from reduce_token_agent.application.view_models import (
    TaskRunView,
    to_persisted_task_run_view,
    to_task_run_view,
)
from reduce_token_agent.domain.task import DataClassification, TaskRequest
from reduce_token_agent.registry.models import RiskLevel


class LocalUiHandlers:
    def __init__(self, facade: ApplicationFacade) -> None:
        self.facade = facade

    def execute(
        self,
        *,
        query: str,
        tenant_id: str,
        principal_id: str,
        scopes: str,
        environment: str,
        data_classification: str,
        risk_level: str,
        business_facts_json: str,
        acceptance_criteria: str,
        domain_hint: str,
    ) -> TaskRunView:
        facts = json.loads(business_facts_json) if business_facts_json.strip() else {}
        if not isinstance(facts, dict):
            raise ValueError("业务事实必须是JSON对象")
        result = self.facade.execute_task(
            TaskRequest(
                query=query,
                tenant_id=tenant_id,
                principal_id=principal_id,
                scopes=_split_scopes(scopes),
                environment=environment,  # type: ignore[arg-type]
                declared_data_classification=(
                    DataClassification(data_classification) if data_classification else None
                ),
                declared_risk_level=RiskLevel(risk_level) if risk_level else None,
                authoritative_entities=facts,
                acceptance_criteria=_split_lines(acceptance_criteria),
                declared_domain_hints=[domain_hint] if domain_hint else [],  # type: ignore[list-item]
            )
        )
        return self._with_persisted_audit(to_task_run_view(result))

    def resume_dm(self, *, run_id: str, message: str) -> TaskRunView:
        return self._with_persisted_audit(
            to_task_run_view(self.facade.resume_task_user_input(run_id, message=message))
        )

    def resume_human(self, *, run_id: str, answers_json: str) -> TaskRunView:
        payload = json.loads(answers_json)
        if not isinstance(payload, dict) or not payload:
            raise ValueError("HUMAN answers must be a non-empty JSON object")
        answers = {
            str(step_id): value if isinstance(value, dict) else {"decision": value}
            for step_id, value in payload.items()
        }
        return self._with_persisted_audit(
            to_task_run_view(self.facade.resume_task_human(run_id, human_answers=answers))
        )

    def dm_runtime_status(self) -> dict[str, object]:
        """Expose only safe startup-mode facts needed to present the DM demo."""
        router = getattr(self.facade, "task_router", None)
        settings = getattr(router, "settings", None)
        environments = list(getattr(settings, "enabled_dm_environments", []))
        robot_nos = list(getattr(settings, "enabled_dm_robot_nos", []))
        return {
            "enabled": bool(getattr(settings, "enable_dm_fsm", False)),
            "sit_enabled": "sit" in environments,
            "robot_353_enabled": "R8976-BVPYV" in robot_nos,
        }

    def inspect(self, run_id: str) -> TaskRunView:
        identifier = run_id.strip()
        if not identifier:
            raise ValueError("请输入 Run ID、Trace ID 或 Trace Ref")
        try:
            return self._with_persisted_audit(to_task_run_view(self.facade.get_task(identifier)))
        except LookupError:
            trace = self.facade.task_router.trace
            if trace is None:
                raise RuntimeError("runtime trace recorder is unavailable") from None
            envelope, path = trace.store.materialize(identifier)
            return to_persisted_task_run_view(envelope, path)

    def _with_persisted_audit(self, view: TaskRunView) -> TaskRunView:
        router = getattr(self.facade, "task_router", None)
        trace = getattr(router, "trace", None)
        if trace is None:
            return view
        try:
            envelope, path = trace.store.materialize(view.run_id)
        except (LookupError, ValueError):
            return view
        persisted = to_persisted_task_run_view(envelope, path)
        return view.model_copy(update={"audit": persisted.audit})

    def component_probe(self, component: str, run_id: str) -> dict[str, Any]:
        if component == "Application Result Contract":
            return self.inspect(run_id).model_dump(mode="json")
        if component == "Runtime Trace Projection":
            trace = self.facade.task_router.trace
            if trace is None:
                raise RuntimeError("runtime trace recorder is unavailable")
            envelope, path = trace.store.materialize(run_id)
            return {
                "trace_id": envelope.trace_id,
                "status": envelope.outcome.status,
                "mode": envelope.outcome.mode,
                "event_count": envelope.provenance.event_count,
                "failure_codes": envelope.outcome.failure_codes,
                "trace_path": str(path),
            }
        if component == "DM Conversation Contract":
            view = self.inspect(run_id)
            return {
                "interaction_kind": view.interaction_kind,
                "conversation_ref": view.conversation_ref,
                "dialog_ref": view.dialog_ref,
                "token_visibility": view.token_visibility,
                "raw_dialog_no_exposed": False,
            }
        raise ValueError(f"unsupported component: {component}")


def _split_scopes(value: str) -> list[str]:
    return [item.strip() for item in value.replace("\n", ",").split(",") if item.strip()]


def _split_lines(value: str) -> list[str]:
    return [item.strip() for item in value.splitlines() if item.strip()]
