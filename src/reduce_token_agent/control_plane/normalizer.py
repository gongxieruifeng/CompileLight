"""Normalize authoritative caller context separately from model-extracted facts."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal

from reduce_token_agent.domain.task import (
    ClarificationRequest,
    DataClassification,
    NormalizedTaskFacts,
    TaskContext,
    TaskRequest,
)
from reduce_token_agent.llm.base import StructuredModel, StructuredUsage
from reduce_token_agent.registry.models import RiskLevel

_RISK_ORDER = {RiskLevel.LOW: 1, RiskLevel.MEDIUM: 2, RiskLevel.HIGH: 3}
_DATA_ORDER = {
    DataClassification.PUBLIC: 1,
    DataClassification.INTERNAL: 2,
    DataClassification.SYNTHETIC: 2,
    DataClassification.CONFIDENTIAL: 3,
    DataClassification.RESTRICTED: 4,
}


@dataclass(frozen=True, slots=True)
class NormalizationOutcome:
    context: TaskContext | None
    clarification: ClarificationRequest | None
    usage: StructuredUsage | None


class TaskNormalizer:
    """LLM extracts business facts; identity always comes from caller metadata."""

    def __init__(self, model: StructuredModel) -> None:
        self.model = model

    def normalize(self, request: TaskRequest) -> NormalizationOutcome:
        missing: list[str] = []
        if not request.tenant_id:
            missing.append("tenant_id")
        if not request.principal_id:
            missing.append("principal_id")
        if missing:
            if len(missing) == 2:
                reason: Literal[
                    "MISSING_TENANT_ID",
                    "MISSING_PRINCIPAL_ID",
                    "MISSING_IDENTITY",
                    "INPUT_AMBIGUOUS",
                ] = "MISSING_IDENTITY"
            elif missing[0] == "tenant_id":
                reason = "MISSING_TENANT_ID"
            else:
                reason = "MISSING_PRINCIPAL_ID"
            return NormalizationOutcome(
                context=None,
                clarification=ClarificationRequest(
                    reason_code=reason,
                    missing_fields=missing,
                    message="缺少可信调用身份信息，请补充租户与调用者身份后重试。",
                ),
                usage=None,
            )

        assert request.tenant_id is not None
        assert request.principal_id is not None
        result = self.model.generate_structured(
            stage="normalize",
            system_prompt=(
                "你是任务规范化器，只提取业务实体、领域、验收条件、数据级别、"
                "风险和时间表达。不得推断或改写 tenant_id、principal_id、scope，"
                "不得生成执行步骤。相对时间必须保留原表达，由代码提供时间基准。"
            ),
            user_payload={
                "query": request.query,
                "time_basis": request.requested_at.isoformat(),
                "timezone": request.timezone,
                "locale": request.locale,
                "allowed_domains": [
                    "corporate_operations",
                    "customer_service",
                    "financial_report",
                    "internal_communication",
                    "loan_contract",
                    "risk_compliance",
                ],
            },
            output_model=NormalizedTaskFacts,
        )
        facts = result.value
        risk = _max_risk(facts.risk_level, request.declared_risk_level)
        # This PoC Registry is intentionally built from local synthetic traces.
        # In the local environment, treat business examples as synthetic
        # verification inputs by default so validated local assets are not
        # filtered out merely because the user did not say "synthetic" in the
        # request. Real tenant data should move to a non-local environment and
        # a matching Registry asset classification.
        local_synthetic = request.environment == "local"
        classification = _max_classification(
            facts.data_classification,
            request.declared_data_classification,
        )
        normalization_codes = [
            "IDENTITY_FROM_CALLER_CONTEXT",
            "TIME_BASIS_FROZEN",
            *facts.normalization_codes,
        ]
        if local_synthetic:
            classification = DataClassification.SYNTHETIC
            if _mentions_local_synthetic_data(request.query):
                normalization_codes.append("LOCAL_SYNTHETIC_DATA_DECLARED_BY_QUERY")
            else:
                normalization_codes.append("LOCAL_POC_SYNTHETIC_ASSET_VIEW")
        acceptance = list(
            dict.fromkeys([*request.acceptance_criteria, *facts.acceptance_criteria])
        )
        context = TaskContext(
            task_id="task_" + secrets.token_hex(8),
            query=request.query,
            tenant_id=request.tenant_id,
            principal_id=request.principal_id,
            scopes=list(dict.fromkeys(request.scopes)),
            requested_at=request.requested_at,
            timezone=request.timezone,
            locale=request.locale,
            environment=request.environment,
            entities=facts.entities,
            domain_hints=list(facts.domain_hints),
            data_classification=classification,
            risk_level=risk,
            acceptance_criteria=acceptance,
            time_expressions=facts.time_expressions,
            irreversible_action_requested=facts.irreversible_action_requested,
            normalization_codes=list(dict.fromkeys(normalization_codes)),
        )
        return NormalizationOutcome(
            context=context,
            clarification=None,
            usage=result.usage,
        )


def _max_risk(inferred: RiskLevel, declared: RiskLevel | None) -> RiskLevel:
    if declared is None:
        return inferred
    return inferred if _RISK_ORDER[inferred] >= _RISK_ORDER[declared] else declared


def _max_classification(
    inferred: DataClassification,
    declared: DataClassification | None,
) -> DataClassification:
    if declared is None:
        return inferred
    return (
        inferred
        if _DATA_ORDER[inferred] >= _DATA_ORDER[declared]
        else declared
    )


def _mentions_local_synthetic_data(query: str) -> bool:
    lowered = query.lower()
    markers = (
        "synthetic",
        "fixture",
        "demo data",
        "本地合成",
        "合成数据",
        "模拟数据",
        "演示数据",
        "测试数据",
    )
    return any(marker in lowered for marker in markers)
