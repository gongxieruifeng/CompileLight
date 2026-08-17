"""Deterministic local handlers for the customer_service asset set."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any


class RuntimeExecutionError(ValueError):
    """Typed failure returned by a local asset handler."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class RuntimeMetadata:
    """Implementation and policy metadata persisted beside Registry assets."""

    implementation_ref: str
    execution_mode: str
    policy_version: str
    business_rules: tuple[str, ...]
    side_effect: str
    policy_document: dict[str, Any] | None = None
    audit_flow: tuple[str, ...] = ()


class CustomerServiceRuntime:
    """Execute the small, deterministic customer_service capability set."""

    TOOL_POLICY_VERSION = "customer-service-tools.synthetic.v1"
    PROJECTION_POLICY_VERSION = "customer-service-projection.synthetic.v1"
    BILLING_POLICY_VERSION = "customer-service-billing.synthetic.v1"
    INVESTIGATION_POLICY_VERSION = "customer-service-investigation.synthetic.v1"
    REQUEST_POLICY_VERSION = "customer-service-request.synthetic.v1"
    ESCALATION_POLICY_VERSION = "customer-service-escalation.synthetic.v1"
    DAEF_POLICY_VERSION = "customer-service-daef.synthetic.v1"

    POLICY_CATALOG: dict[str, dict[str, Any]] = {
        TOOL_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "no_external_io": True,
            "intents": [
                "repayment_inquiry",
                "overdue_complaint",
                "rate_explanation",
                "prepayment_request",
                "fraud_report",
                "payment_failure",
                "profile_correction",
                "credit_dispute",
            ],
        },
        PROJECTION_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "projection_kinds": ["repayment_summary", "rate_explanation"],
            "sensitive_fields_removed": True,
        },
        BILLING_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "disclosure_requirements": [
                "amount_due",
                "due_date",
                "grace_period",
                "repricing_rule",
            ],
            "no_write_back": True,
        },
        INVESTIGATION_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "allowed_routes": [
                "EXPLAIN_BANK_DELAY",
                "READ_ONLY_TROUBLESHOOTING",
                "HUMAN_REVIEW",
            ],
            "no_account_write": True,
        },
        REQUEST_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "required_fields": {
                "prepayment_request": [
                    "loan_account_id",
                    "requested_amount",
                    "requested_date",
                ],
                "profile_correction": [
                    "customer_id",
                    "new_address",
                    "identity_evidence",
                ],
            },
            "no_direct_write": True,
        },
        ESCALATION_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "deadline_hours": {"fraud_report": 2.0, "credit_dispute": 24.0},
            "handoff_team": {
                "fraud_report": "SECURITY_TEAM",
                "credit_dispute": "CREDIT_OPERATIONS",
            },
            "mask_sensitive": True,
        },
        DAEF_POLICY_VERSION: {
            "stages": [
                "INFORMATION",
                "TRANSFORM",
                "DECISION",
                "ACTION",
                "VALIDATION",
            ],
            "binds_asset_refs": False,
            "directly_executable": False,
        },
    }

    AUDIT_FLOWS: dict[str, tuple[str, ...]] = {
        "intent": (
            "CLASSIFY_INTENT",
            "EXTRACT_ENTITIES",
            "ASSIGN_ROUTE_FAMILY",
            "FLAG_RISK_HINTS",
        ),
        "lookup": (
            "RESOLVE_SYNTHETIC_KEY",
            "LOAD_LOCAL_SNAPSHOT",
            "RETURN_CONTROLLED_FACTS",
        ),
        "extract": (
            "PARSE_DIALOGUE",
            "STRUCTURE_FACTS",
            "REDACT_INPUT_REFERENCE",
            "RETURN_CONTRACTED_FACTS",
        ),
        "risk": (
            "INGEST_SIGNALS",
            "SCORE_RISK",
            "SELECT_ROUTE",
            "FLAG_HUMAN_REVIEW",
        ),
        "projection": (
            "LOAD_INTERNAL_FACTS",
            "PROJECT_CUSTOMER_REPLY",
            "REMOVE_SENSITIVE_FIELDS",
        ),
        "billing": (
            "INTAKE",
            "LOOKUP",
            "PROJECTION",
            "VALIDATE",
        ),
        "investigation": (
            "EXTRACT",
            "COMPARE",
            "EXPLAIN",
            "VALIDATE",
        ),
        "request": (
            "EXTRACT",
            "GAP_CHECK",
            "RISK_GATE",
            "DRAFT",
            "VALIDATE",
        ),
        "escalation": (
            "EXTRACT",
            "SCORE",
            "MASK",
            "DEADLINE",
            "HANDOFF",
            "VALIDATE",
        ),
        "daef": (
            "INFORMATION",
            "TRANSFORM",
            "DECISION",
            "ACTION",
            "VALIDATION",
        ),
    }

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "tool.customer_service.dialogue.intent_normalize@1.0.0": self.intent_normalize,
            "tool.customer_service.case.snapshot_lookup@1.0.0": self.case_snapshot_lookup,
            "tool.customer_service.claim.context_extract@1.0.0": self.claim_context_extract,
            "tool.customer_service.risk.signal_score@1.0.0": self.risk_signal_score,
            "adapter.customer_service.response.customer_projection@1.0.0": (
                self.customer_response_projection
            ),
            "fsm.customer_service.billing.answer_route@1.0.0": self.billing_answer_route,
            "fsm.customer_service.case.investigation_route@1.0.0": self.case_investigation_route,
            "fsm.customer_service.request.intake_route@1.0.0": self.request_intake_route,
            "fsm.customer_service.escalation.triage_route@1.0.0": self.escalation_triage_route,
            "validator.customer_service.billing.response@1.0.0": self.validate_billing_response,
            "validator.customer_service.case.investigation@1.0.0": self.validate_case_investigation,
            "validator.customer_service.request.intake@1.0.0": self.validate_request_intake,
            "validator.customer_service.escalation.triage@1.0.0": self.validate_escalation_triage,
        }
        self._planning_priors = {
            "skeleton.customer_service.intake_resolution_daef@1.0.0": {
                "stages": [
                    "INFORMATION",
                    "TRANSFORM",
                    "DECISION",
                    "ACTION",
                    "VALIDATION",
                ],
                "directly_executable": False,
            }
        }

    def execute(self, asset_ref: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute one exact asset version in the local test/runtime harness."""
        handler = self._handlers.get(asset_ref)
        if handler is None:
            if asset_ref in self._planning_priors:
                raise RuntimeExecutionError(
                    "ASSET_NOT_EXECUTABLE",
                    "WORKFLOW_SKELETON is a planning prior, not an executor",
                )
            raise RuntimeExecutionError("ASSET_NOT_AVAILABLE", f"unknown asset {asset_ref}")
        return handler(payload)

    def planning_prior(self, asset_ref: str) -> dict[str, Any]:
        """Return a DAEF prior without executing it."""
        try:
            return dict(self._planning_priors[asset_ref])
        except KeyError as exc:
            raise RuntimeExecutionError(
                "PLANNING_PRIOR_NOT_FOUND",
                f"unknown planning prior {asset_ref}",
            ) from exc

    def metadata(self) -> dict[str, RuntimeMetadata]:
        """Return implementation and policy metadata for Registry binding."""
        base = {
            "tool.customer_service.dialogue.intent_normalize@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:intent_normalize",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("客服意图必须归一为稳定路由族", "只读处理不写入客户系统"),
                "READ_ONLY",
            ),
            "tool.customer_service.case.snapshot_lookup@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:case_snapshot_lookup",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("事实快照只来自本地合成目录", "不访问真实外部系统"),
                "READ_ONLY",
            ),
            "tool.customer_service.claim.context_extract@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:claim_context_extract",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("抽取候选事实但不保留 EXTRACTOR kind", "提取结果必须可验证"),
                "READ_ONLY",
            ),
            "tool.customer_service.risk.signal_score@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:risk_signal_score",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("风险评分只决定人工路由，不执行冻结或写回",),
                "READ_ONLY",
            ),
            "adapter.customer_service.response.customer_projection@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:customer_response_projection",
                "EXECUTABLE",
                self.PROJECTION_POLICY_VERSION,
                ("内部事实投影为客户展示字段",),
                "NONE",
            ),
            "fsm.customer_service.billing.answer_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:billing_answer_route",
                "EXECUTABLE",
                self.BILLING_POLICY_VERSION,
                ("还款咨询与利率解释共用同一路由", "披露字段必须完整"),
                "NONE",
            ),
            "fsm.customer_service.case.investigation_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:case_investigation_route",
                "EXECUTABLE",
                self.INVESTIGATION_POLICY_VERSION,
                ("只读调查只输出解释或排障建议",),
                "NONE",
            ),
            "fsm.customer_service.request.intake_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:request_intake_route",
                "EXECUTABLE",
                self.REQUEST_POLICY_VERSION,
                ("高敏请求必须保留人工复核", "只能生成草稿和缺口清单"),
                "NONE",
            ),
            "fsm.customer_service.escalation.triage_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:escalation_triage_route",
                "EXECUTABLE",
                self.ESCALATION_POLICY_VERSION,
                ("高风险事件必须脱敏并人工移交",),
                "NONE",
            ),
            "validator.customer_service.billing.response@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:validate_billing_response",
                "EXECUTABLE",
                self.BILLING_POLICY_VERSION,
                ("回复必须包含金额、日期或利率披露",),
                "NONE",
            ),
            "validator.customer_service.case.investigation@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:validate_case_investigation",
                "EXECUTABLE",
                self.INVESTIGATION_POLICY_VERSION,
                ("调查结果必须是只读边界",),
                "NONE",
            ),
            "validator.customer_service.request.intake@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:validate_request_intake",
                "EXECUTABLE",
                self.REQUEST_POLICY_VERSION,
                ("高敏请求必须保留人工复核",),
                "NONE",
            ),
            "validator.customer_service.escalation.triage@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.customer_service:validate_escalation_triage",
                "EXECUTABLE",
                self.ESCALATION_POLICY_VERSION,
                ("脱敏、时限与人工移交必须同时成立",),
                "NONE",
            ),
            "skeleton.customer_service.intake_resolution_daef@1.0.0": RuntimeMetadata(
                "daef://customer_service/intake_resolution",
                "PLANNING_ONLY",
                self.DAEF_POLICY_VERSION,
                ("宏观阶段固定为信息、转换、决策、行动、验证",),
                "NONE",
            ),
        }
        enriched: dict[str, RuntimeMetadata] = {}
        for asset_ref, metadata in base.items():
            flow_key = _flow_key(asset_ref)
            enriched[asset_ref] = replace(
                metadata,
                policy_document=dict(self.POLICY_CATALOG[metadata.policy_version]),
                audit_flow=self.AUDIT_FLOWS[flow_key],
            )
        return enriched

    def sample_payloads(self) -> dict[str, dict[str, Any]]:
        """Return canonical success-case payloads for runtime verification."""
        intent_repayment = {
            "intent_category": "repayment_inquiry",
            "route_family": "billing_answer",
            "risk_level": "medium",
            "entities": {
                "account_id": "ACC-9876543",
                "amount_hint": 1340.5,
                "due_date_hint": "2023-11-15",
            },
            "human_review_hint": False,
        }
        billing_snapshot = {
            "lookup_key": "billing_snapshot_account_9876543",
            "snapshot_type": "billing_snapshot",
            "facts": {
                "account_id": "ACC-9876543",
                "next_due_amount": 1340.5,
                "due_date": "2023-11-15",
                "grace_period_end": "2023-11-18",
                "account_status": "NORMAL",
            },
        }
        claim_overdue = {
            "extract_kind": "PAYMENT_CLAIM",
            "facts": {
                "amount_claimed": 10000.0,
                "claimed_payment_time": "2023-10-25T23:45:00",
                "channel": "BANK_APP",
                "transaction_reference": "ICBC-20231025-2345",
            },
            "confidence_score": 0.97,
        }
        risk_fraud = {
            "case_kind": "fraud_report",
            "signals": ["unrecognized_debit", "merchant_risk_92"],
            "amount": 4500.0,
            "evidence_complete": True,
        }
        projection = {
            "projection_kind": "repayment_summary",
            "facts": {
                "next_due_amount": 1340.5,
                "due_date": "2023-11-15",
                "grace_period_end": "2023-11-18",
                "account_status": "NORMAL",
            },
        }
        billing_route = {
            "intent_profile": intent_repayment,
            "support_snapshot": billing_snapshot,
            "projection_kind": "repayment_summary",
        }
        investigation_route = {
            "case_type": "overdue_complaint",
            "claim_context": claim_overdue["facts"],
            "case_snapshot": {
                "due_date": "2023-10-25",
                "late_fee_rule": "逾期后按每日万分之五",
                "current_late_fee": 45.0,
                "settlement_cutoff": "2023-10-25T23:59:59",
                "actual_settlement": "2023-10-26T08:00:00",
            },
        }
        request_route = {
            "request_type": "prepayment_request",
            "extracted_facts": {
                "loan_account_id": "LN-2023-0001",
                "requested_amount": 50000.0,
                "requested_date": "2023-11-20",
                "customer_id": "CUST-1100",
            },
            "risk_decision": {
                "risk_score": 72.0,
                "risk_band": "HIGH",
                "recommended_route": "HUMAN_REVIEW",
                "human_review_required": True,
            },
        }
        escalation_route = {
            "case_type": "fraud_report",
            "case_facts": {
                "customer_id": "CUST-2255",
                "amount": 4500.0,
                "merchant_code": "MCH-998",
                "transaction_id": "TXN-998877665",
                "summary": "未知来源扣款，疑似欺诈。",
            },
            "risk_decision": {
                "risk_score": 91.0,
                "risk_band": "HIGH",
                "recommended_route": "SECURITY_ESCALATION",
                "human_review_required": True,
            },
            "evidence_bundle": {
                "records": ["ctx_01_inquiry_log", "ctx_02_system_alert"],
                "complete": True,
            },
        }
        billing_output = self.customer_response_projection(
            {
                "projection_kind": "repayment_summary",
                "facts": billing_snapshot["facts"],
            }
        )
        case_output = self.case_investigation_route(investigation_route)
        request_output = self.request_intake_route(request_route)
        escalation_output = self.escalation_triage_route(escalation_route)
        return {
            "tool.customer_service.dialogue.intent_normalize@1.0.0": {
                "source_text": "您好，我想查询我名下账户下期的应还金额和具体扣款日期。",
            },
            "tool.customer_service.case.snapshot_lookup@1.0.0": {
                "lookup_key": "billing_snapshot_account_9876543",
                "lookup_type": "billing",
            },
            "tool.customer_service.claim.context_extract@1.0.0": {
                "source_text": (
                    "用户反馈昨天尝试还款，错误码是 E_PAY_INSUFFICIENT_FUNDS_02，余额只有 5.89 元。"
                ),
                "extract_kind": "PAYMENT_FAILURE",
            },
            "tool.customer_service.risk.signal_score@1.0.0": risk_fraud,
            "adapter.customer_service.response.customer_projection@1.0.0": projection,
            "fsm.customer_service.billing.answer_route@1.0.0": billing_route,
            "fsm.customer_service.case.investigation_route@1.0.0": investigation_route,
            "fsm.customer_service.request.intake_route@1.0.0": request_route,
            "fsm.customer_service.escalation.triage_route@1.0.0": escalation_route,
            "validator.customer_service.billing.response@1.0.0": {"payload": billing_output},
            "validator.customer_service.case.investigation@1.0.0": {"payload": case_output},
            "validator.customer_service.request.intake@1.0.0": {"payload": request_output},
            "validator.customer_service.escalation.triage@1.0.0": {"payload": escalation_output},
            "skeleton.customer_service.intake_resolution_daef@1.0.0": {
                "objective": "客户服务任务受理与验证",
                "risk_level": "HIGH",
                "constraints": ["no_write_back", "human_review_for_high_risk"],
            },
        }

    def sample_payload(self, asset_ref: str) -> dict[str, Any]:
        """Return the canonical success payload for one exact asset ref."""
        try:
            return dict(self.sample_payloads()[asset_ref])
        except KeyError as exc:
            raise RuntimeExecutionError("SAMPLE_PAYLOAD_NOT_FOUND", asset_ref) from exc

    def intent_normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize a customer-facing dialogue into a stable route family."""
        source_text = _required_string(payload, "source_text")
        scenario_hint = _optional_string(payload, "scenario_hint")
        normalized = source_text.lower()
        intent_category = _infer_intent(normalized, scenario_hint)
        route_family = {
            "repayment_inquiry": "billing_answer",
            "rate_explanation": "billing_answer",
            "overdue_complaint": "case_investigation",
            "payment_failure": "case_investigation",
            "prepayment_request": "request_intake",
            "profile_correction": "request_intake",
            "fraud_report": "escalation_triage",
            "credit_dispute": "escalation_triage",
        }[intent_category]
        risk_level = (
            "HIGH"
            if intent_category
            in {"fraud_report", "credit_dispute", "prepayment_request", "profile_correction"}
            else "MEDIUM"
        )
        amount_hint = _extract_amount(source_text)
        error_code = _extract_error_code(source_text)
        entities: dict[str, Any] = {}
        if amount_hint is not None:
            entities["amount_hint"] = amount_hint
        if error_code is not None:
            entities["error_code"] = error_code
        if "地址" in source_text or "address" in normalized:
            entities["address_change"] = True
        if "利率" in source_text or "lpr" in normalized or "加点" in source_text:
            entities["rate_terms"] = True
        if "征信" in source_text or "异议" in source_text:
            entities["dispute"] = True
        if not entities:
            entities["text_fragment"] = source_text[:48]
        return {
            "intent_category": intent_category,
            "route_family": route_family,
            "risk_level": risk_level,
            "entities": entities,
            "human_review_hint": risk_level == "HIGH",
            "normalized_summary": source_text[:120],
        }

    def case_snapshot_lookup(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Read one entry from the local synthetic case snapshot catalog."""
        lookup_key = _required_string(payload, "lookup_key")
        lookup_type = _optional_string(payload, "lookup_type") or "generic"
        catalog: dict[str, dict[str, Any]] = {
            "billing_snapshot_account_9876543": {
                "snapshot_type": "billing_snapshot",
                "facts": {
                    "account_id": "ACC-9876543",
                    "next_due_amount": 1340.5,
                    "due_date": "2023-11-15",
                    "grace_period_end": "2023-11-18",
                    "account_status": "NORMAL",
                },
            },
            "rate_contract_loan_01": {
                "snapshot_type": "contract_snapshot",
                "facts": {
                    "base_rate_type": "LPR",
                    "base_rate": 3.85,
                    "spread": 0.5,
                    "effective_rate": 4.35,
                    "repricing_rule": "每年1月1日或提款日对应日，节假日顺延",
                },
            },
            "overdue_billing_stmt_9981": {
                "snapshot_type": "billing_statement",
                "facts": {
                    "due_date": "2023-10-25",
                    "late_fee_rule": "逾期后按每日万分之五",
                    "current_late_fee": 45.0,
                    "settlement_cutoff": "2023-10-25T23:59:59",
                },
            },
            "payment_error_txn_9988": {
                "snapshot_type": "payment_log",
                "facts": {
                    "error_code": "E_PAY_INSUFFICIENT_FUNDS_02",
                    "available_balance": 5.89,
                    "required_amount": 100.0,
                    "transaction_id": "TXN_9988",
                },
            },
            "prepayment_policy_v1": {
                "snapshot_type": "policy_snapshot",
                "facts": {
                    "allowed": True,
                    "notice_days": 5,
                    "fee_rule": "提前还款仅收固定手续费",
                    "required_fields": [
                        "loan_account_id",
                        "requested_amount",
                        "requested_date",
                    ],
                },
            },
            "profile_snapshot_98765": {
                "snapshot_type": "profile_snapshot",
                "facts": {
                    "customer_id": "CUST-98765",
                    "current_address": "上海市浦东新区世纪大道123号",
                    "risk_flag": False,
                    "last_update_time": "2023-10-15T10:00:00Z",
                },
            },
            "fraud_event_7721": {
                "snapshot_type": "security_alert",
                "facts": {
                    "merchant_risk_score": 92,
                    "event_id": "FRAUD-EVT-7721",
                    "transaction_id": "TXN-998877665",
                    "suspicious_pattern": "high_frequency_small_tickets_then_large_debit",
                    "security_team_queue": "SEC-QUEUE-07",
                },
            },
            "credit_dispute_ds_20231027_894": {
                "snapshot_type": "dispute_snapshot",
                "facts": {
                    "disputed_entity_id": "DS-20231027-894",
                    "reason_code": "UNAUTHORIZED_LOAN_STATUS",
                    "evidence_required": ["bank_statement", "call_summary"],
                    "deadline_hours": 24,
                },
            },
        }
        try:
            record = catalog[lookup_key]
        except KeyError as exc:
            raise RuntimeExecutionError("SNAPSHOT_NOT_FOUND", lookup_key) from exc
        return {
            "lookup_key": lookup_key,
            "lookup_type": lookup_type,
            **record,
        }

    def claim_context_extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Extract customer claim facts from a controlled synthetic text source."""
        source_text = _required_string(payload, "source_text")
        extract_kind = _required_string(payload, "extract_kind")
        normalized = source_text.lower()
        facts: dict[str, Any]
        if extract_kind == "PAYMENT_CLAIM":
            amount = _extract_amount(source_text) or 0.0
            facts = {
                "amount_claimed": amount,
                "claimed_payment_time": _extract_datetime(source_text) or "2023-10-25T23:45:00",
                "channel": "BANK_APP"
                if "app" in normalized or "银行" in source_text
                else "UNKNOWN",
                "transaction_reference": "ICBC-20231025-2345" if amount else "UNKNOWN",
            }
        elif extract_kind == "PAYMENT_FAILURE":
            facts = {
                "error_code": _extract_error_code(source_text) or "E_PAY_UNKNOWN",
                "available_balance": _extract_amount_after_phrase(source_text, "余额") or 5.89,
                "required_amount": _extract_amount_after_phrase(source_text, "需要支付") or 100.0,
                "transaction_id": "TXN_9988",
            }
        elif extract_kind == "ADDRESS_CHANGE":
            facts = {
                "customer_id": _extract_customer_id(source_text) or "CUST-98765",
                "old_address": _extract_old_address(source_text) or "上海市浦东新区世纪大道123号",
                "new_address": _extract_new_address(source_text) or "北京市朝阳区建国路88号",
            }
        elif extract_kind == "CREDIT_DISPUTE":
            facts = {
                "disputed_entity_id": "CREDIT-REPORT-8899",
                "claim_reason_code": "UNAUTHORIZED_LOAN_STATUS",
                "evidence_summary": "银行流水与通话摘要已上传",
            }
        elif extract_kind == "PREPAYMENT_REQUEST":
            facts = {
                "loan_account_id": _extract_loan_account(source_text) or "LN-2023-0001",
                "requested_amount": _extract_amount(source_text) or 50000.0,
                "requested_date": _extract_date_token(source_text) or "2023-11-20",
                "customer_id": _extract_customer_id(source_text) or "CUST-1100",
            }
        elif extract_kind == "RISK_ALERT":
            facts = {
                "customer_id": _extract_customer_id(source_text) or "CUST-2255",
                "amount": _extract_amount(source_text) or 4500.0,
                "merchant_code": _extract_merchant_code(source_text) or "MCH-998",
                "transaction_id": _extract_transaction_id(source_text) or "TXN-998877665",
            }
        else:
            raise RuntimeExecutionError("EXTRACT_KIND_UNSUPPORTED", extract_kind)
        return {
            "extract_kind": extract_kind,
            "facts": facts,
            "confidence_score": 0.96,
        }

    def risk_signal_score(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calculate a deterministic risk score for high-sensitivity customer cases."""
        case_kind = _required_string(payload, "case_kind")
        signals = _string_list(payload, "signals")
        amount = _number(payload, "amount")
        evidence_complete = payload.get("evidence_complete")
        if not isinstance(evidence_complete, bool):
            raise RuntimeExecutionError("RISK_SIGNAL_INVALID", "evidence_complete must be boolean")
        base = {
            "fraud_report": 78.0,
            "credit_dispute": 72.0,
            "profile_correction": 60.0,
            "prepayment_request": 58.0,
            "payment_failure": 42.0,
            "overdue_complaint": 45.0,
            "repayment_inquiry": 18.0,
            "rate_explanation": 16.0,
        }.get(case_kind)
        if base is None:
            raise RuntimeExecutionError("CASE_KIND_UNSUPPORTED", case_kind)
        score = base
        if amount >= 1000.0:
            score += 8.0
        if not evidence_complete:
            score += 15.0
        score += min(len(signals) * 3.0, 12.0)
        if any(
            "risk" in signal or "unauthorized" in signal or "fraud" in signal for signal in signals
        ):
            score += 7.0
        score = round(min(score, 100.0), 1)
        if score >= 75.0:
            risk_band = "HIGH"
            recommended_route = (
                "SECURITY_ESCALATION"
                if case_kind in {"fraud_report", "credit_dispute"}
                else "HUMAN_REVIEW"
            )
        elif score >= 45.0:
            risk_band = "MEDIUM"
            recommended_route = "HUMAN_REVIEW"
        else:
            risk_band = "LOW"
            recommended_route = "AUTO_PROCESS"
        return {
            "risk_score": score,
            "risk_band": risk_band,
            "recommended_route": recommended_route,
            "human_review_required": risk_band != "LOW",
            "blocking_signals": list(signals),
        }

    def customer_response_projection(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Project internal billing or term facts into customer-facing reply fields."""
        projection_kind = _required_string(payload, "projection_kind")
        facts = _required_dict(payload, "facts")
        if projection_kind == "repayment_summary":
            return {
                "response_kind": projection_kind,
                "response_draft": (
                    f"您下期应还金额为 {facts.get('next_due_amount', 0):.2f} 元，"
                    f"预计扣款日期为 {facts.get('due_date')}。"
                ),
                "disclosure_items": [
                    "amount_due",
                    "due_date",
                    "grace_period",
                ],
                "sensitive_fields_removed": True,
            }
        if projection_kind == "rate_explanation":
            return {
                "response_kind": projection_kind,
                "response_draft": (
                    f"当前执行利率由基准利率 {facts.get('base_rate', 0):.2f}% "
                    f"和加点 {facts.get('spread', 0):.2f}% 组成，"
                    f"重定价规则为 {facts.get('repricing_rule')}。"
                ),
                "disclosure_items": [
                    "base_rate",
                    "spread",
                    "repricing_rule",
                ],
                "sensitive_fields_removed": True,
            }
        raise RuntimeExecutionError("PROJECTION_KIND_UNSUPPORTED", projection_kind)

    def billing_answer_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route billing and rate questions into a deterministic reply draft."""
        intent_profile = _required_dict(payload, "intent_profile")
        support_snapshot = _required_dict(payload, "support_snapshot")
        projection_kind = _required_string(payload, "projection_kind")
        intent_category = _required_string(intent_profile, "intent_category")
        if intent_category not in {"repayment_inquiry", "rate_explanation"}:
            raise RuntimeExecutionError("BILLING_ROUTE_UNSUPPORTED", intent_category)
        if projection_kind == "repayment_summary":
            projected = self.customer_response_projection(
                {"projection_kind": "repayment_summary", "facts": support_snapshot["facts"]}
            )
            answer_type = "REPAYMENT_INQUIRY"
        elif projection_kind == "rate_explanation":
            projected = self.customer_response_projection(
                {"projection_kind": "rate_explanation", "facts": support_snapshot["facts"]}
            )
            answer_type = "RATE_EXPLANATION"
        else:
            raise RuntimeExecutionError("BILLING_ROUTE_UNSUPPORTED", projection_kind)
        return {
            "answer_type": answer_type,
            "response_draft": projected["response_draft"],
            "disclosure_items": projected["disclosure_items"],
            "human_review_required": bool(intent_profile.get("human_review_hint")),
            "sensitive_fields_removed": projected["sensitive_fields_removed"],
        }

    def case_investigation_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route payment disputes and failures through a read-only investigation path."""
        case_type = _required_string(payload, "case_type")
        claim_context = _required_dict(payload, "claim_context")
        case_snapshot = _required_dict(payload, "case_snapshot")
        if case_type == "overdue_complaint":
            claimed_time = claim_context.get("claimed_payment_time")
            settlement_cutoff = case_snapshot.get("settlement_cutoff")
            actual_settlement = case_snapshot.get("actual_settlement")
            route = "EXPLAIN_BANK_DELAY"
            cause_code = "BANK_SETTLEMENT_DELAY"
            if claimed_time and settlement_cutoff and actual_settlement:
                claimed_dt = _parse_dt(claimed_time)
                cutoff_dt = _parse_dt(settlement_cutoff)
                actual_dt = _parse_dt(actual_settlement)
                if claimed_dt <= cutoff_dt and actual_dt > cutoff_dt:
                    cause_code = "BANK_DELAY_CONFIRMED"
                elif actual_dt <= cutoff_dt:
                    cause_code = "ON_TIME_SETTLEMENT"
            message = "已核对到您在应还日前后提交的转账记录，账单逾期费由银行到账时间差导致。"
            next_steps = [
                "说明到账延迟与账单入账时间差",
                "保留转账凭证供人工复核",
            ]
        elif case_type == "payment_failure":
            error_code = str(claim_context.get("error_code", "E_PAY_UNKNOWN"))
            available = float(claim_context.get("available_balance", 0.0))
            required = float(claim_context.get("required_amount", 0.0))
            route = "READ_ONLY_TROUBLESHOOTING"
            if error_code == "E_PAY_INSUFFICIENT_FUNDS_02" and available < required:
                cause_code = "INSUFFICIENT_FUNDS"
            else:
                cause_code = "PAYMENT_GATEWAY_RETRY"
            message = (
                f"检测到错误码 {error_code}，当前可用余额 {available:.2f} 元低于"
                f"应付金额 {required:.2f} 元。"
            )
            next_steps = [
                "提示补足余额",
                "建议在余额充足后重新发起扣款",
            ]
        else:
            raise RuntimeExecutionError("CASE_TYPE_UNSUPPORTED", case_type)
        return {
            "resolution_route": route,
            "cause_code": cause_code,
            "customer_message_draft": message,
            "next_steps": next_steps,
            "side_effects_allowed": False,
        }

    def request_intake_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route high-sensitivity requests into draft creation plus human review."""
        request_type = _required_string(payload, "request_type")
        extracted_facts = _required_dict(payload, "extracted_facts")
        risk_decision = _optional_dict(payload, "risk_decision") or {}
        required_fields = self.POLICY_CATALOG[self.REQUEST_POLICY_VERSION]["required_fields"].get(
            request_type
        )
        if required_fields is None:
            raise RuntimeExecutionError("REQUEST_TYPE_UNSUPPORTED", request_type)
        missing_fields = [field for field in required_fields if field not in extracted_facts]
        if request_type == "prepayment_request":
            route = "DRAFT_APPLICATION" if not missing_fields else "REQUEST_MISSING_INFO"
            draft_prefix = "PREPAY"
            next_required_actions = [
                "补充缺失字段",
                "等待人工审批",
            ]
        else:
            route = "DRAFT_TICKET" if not missing_fields else "REQUEST_MISSING_INFO"
            draft_prefix = "PROFILE"
            next_required_actions = [
                "提交身份或材料证明",
                "等待人工复核",
            ]
        risk_band = str(risk_decision.get("risk_band", "HIGH")).upper()
        human_review_required = bool(missing_fields) or risk_band == "HIGH"
        draft_id = f"{draft_prefix}-{request_type}-{_stable_key(extracted_facts)}"
        return {
            "route": route,
            "missing_fields": missing_fields,
            "draft_id": draft_id,
            "human_review_required": human_review_required,
            "next_required_actions": next_required_actions,
            "side_effects_allowed": False,
        }

    def escalation_triage_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Triage fraud and credit-dispute events into a masked human handoff."""
        case_type = _required_string(payload, "case_type")
        case_facts = _required_dict(payload, "case_facts")
        risk_decision = _required_dict(payload, "risk_decision")
        evidence_bundle = _optional_dict(payload, "evidence_bundle") or {}
        if case_type not in {"fraud_report", "credit_dispute"}:
            raise RuntimeExecutionError("ESCALATION_TYPE_UNSUPPORTED", case_type)
        deadline_hours = float(
            self.POLICY_CATALOG[self.ESCALATION_POLICY_VERSION]["deadline_hours"][case_type]
        )
        handoff_team = str(
            self.POLICY_CATALOG[self.ESCALATION_POLICY_VERSION]["handoff_team"][case_type]
        )
        ticket_type = "FRAUD_SECURITY" if case_type == "fraud_report" else "CREDIT_DISPUTE"
        source_summary = case_facts.get("summary") or case_facts.get("evidence_summary") or ""
        masked_case_summary = _mask_sensitive(str(source_summary))
        if evidence_bundle:
            masked_case_summary = _mask_sensitive(
                f"{masked_case_summary} | evidence={evidence_bundle.get('records', [])}"
            )
        human_review_required = bool(risk_decision.get("human_review_required", True))
        if case_type == "credit_dispute":
            human_review_required = True
        return {
            "ticket_type": ticket_type,
            "handoff_team": handoff_team,
            "deadline_hours": deadline_hours,
            "masked_case_summary": masked_case_summary,
            "human_review_required": human_review_required,
            "sensitive_fields_removed": True,
        }

    def validate_billing_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate billing answer completion and disclosure coverage."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        response_draft = candidate.get("response_draft")
        disclosure_items = candidate.get("disclosure_items")
        sensitive_fields_removed = candidate.get("sensitive_fields_removed")
        answer_type = str(candidate.get("answer_type", ""))
        if not isinstance(response_draft, str) or not response_draft.strip():
            failure_codes.append("RESPONSE_EMPTY")
        if not isinstance(disclosure_items, list) or not disclosure_items:
            failure_codes.append("DISCLOSURE_INCOMPLETE")
        elif answer_type == "RATE_EXPLANATION":
            required = {"base_rate", "spread", "repricing_rule"}
            if not required.issubset(set(str(item) for item in disclosure_items)):
                failure_codes.append("DISCLOSURE_INCOMPLETE")
        elif answer_type == "REPAYMENT_INQUIRY":
            required = {"amount_due", "due_date"}
            if not required.issubset(set(str(item) for item in disclosure_items)):
                failure_codes.append("DISCLOSURE_INCOMPLETE")
        if sensitive_fields_removed is not True:
            failure_codes.append("SENSITIVE_DATA_DETECTED")
        return {"valid": not failure_codes, "failure_codes": failure_codes}

    def validate_case_investigation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate read-only investigation outputs."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        if candidate.get("resolution_route") not in {
            "EXPLAIN_BANK_DELAY",
            "READ_ONLY_TROUBLESHOOTING",
        }:
            failure_codes.append("ROUTE_MISSING")
        if not str(candidate.get("cause_code", "")).strip():
            failure_codes.append("CAUSE_CODE_MISSING")
        if candidate.get("side_effects_allowed") is not False:
            failure_codes.append("UNAUTHORIZED_WRITE")
        if not isinstance(candidate.get("next_steps"), list) or not candidate["next_steps"]:
            failure_codes.append("NEXT_STEPS_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}

    def validate_request_intake(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate high-sensitivity request drafts and human review routing."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        if not str(candidate.get("draft_id", "")).strip():
            failure_codes.append("DRAFT_ID_MISSING")
        if candidate.get("human_review_required") is not True:
            failure_codes.append("HUMAN_REVIEW_REQUIRED")
        if candidate.get("side_effects_allowed") is not False:
            failure_codes.append("UNAUTHORIZED_WRITE")
        if not isinstance(candidate.get("missing_fields"), list):
            failure_codes.append("FIELDS_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}

    def validate_escalation_triage(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate masked escalation output and time-bound human handoff."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        if candidate.get("human_review_required") is not True:
            failure_codes.append("HUMAN_HANDOFF_REQUIRED")
        if candidate.get("sensitive_fields_removed") is not True:
            failure_codes.append("MASKING_REQUIRED")
        deadline_hours = candidate.get("deadline_hours")
        if not isinstance(deadline_hours, (int, float)) or deadline_hours > 24:
            failure_codes.append("DEADLINE_INVALID")
        if not str(candidate.get("masked_case_summary", "")).strip():
            failure_codes.append("SUMMARY_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}


def _flow_key(asset_ref: str) -> str:
    if asset_ref.startswith("tool.customer_service.dialogue.") or asset_ref.startswith(
        "tool.customer_service.case."
    ):
        return "lookup" if "snapshot" in asset_ref else "intent"
    if asset_ref.startswith("tool.customer_service.claim."):
        return "extract"
    if asset_ref.startswith("tool.customer_service.risk."):
        return "risk"
    if asset_ref.startswith("adapter.customer_service.response."):
        return "projection"
    if asset_ref.startswith("fsm.customer_service.billing."):
        return "billing"
    if asset_ref.startswith("fsm.customer_service.case."):
        return "investigation"
    if asset_ref.startswith("fsm.customer_service.request."):
        return "request"
    if asset_ref.startswith("fsm.customer_service.escalation."):
        return "escalation"
    if asset_ref.startswith("validator.customer_service.billing."):
        return "billing"
    if asset_ref.startswith("validator.customer_service.case."):
        return "investigation"
    if asset_ref.startswith("validator.customer_service.request."):
        return "request"
    if asset_ref.startswith("validator.customer_service.escalation."):
        return "escalation"
    return "daef"


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be a non-empty string")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be a string")
    return value


def _required_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be an object")
    return value


def _optional_dict(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be an object")
    return value


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be a list of strings")
    return [item for item in value if item]


def _number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be numeric")
    return float(value)


def _unwrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) == {"payload"} and isinstance(payload["payload"], dict):
        return payload["payload"]
    return payload


def _infer_intent(source_text: str, scenario_hint: str | None) -> str:
    if "利率" in source_text or "lpr" in source_text or "加点" in source_text:
        return "rate_explanation"
    if "逾期" in source_text or "逾期费" in source_text:
        return "overdue_complaint"
    if "失败" in source_text or "e_pay" in source_text:
        return "payment_failure"
    if "提前还款" in source_text:
        return "prepayment_request"
    if "征信" in source_text or "异议" in source_text:
        return "credit_dispute"
    if "欺诈" in source_text or "不明来源" in source_text or "未授权" in source_text:
        return "fraud_report"
    if "地址" in source_text or "更正" in source_text or "修改" in source_text:
        return "profile_correction"
    if "还款" in source_text or "应还金额" in source_text or "扣款日期" in source_text:
        return "repayment_inquiry"
    if scenario_hint:
        normalized = scenario_hint.lower()
        for candidate in (
            "repayment_inquiry",
            "overdue_complaint",
            "rate_explanation",
            "prepayment_request",
            "fraud_report",
            "payment_failure",
            "profile_correction",
            "credit_dispute",
        ):
            if candidate in normalized:
                return candidate
    raise RuntimeExecutionError("INTENT_UNSUPPORTED", source_text[:80])


def _extract_amount(text: str) -> float | None:
    matches = re.findall(r"(?<!\d)(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d)", text)
    if not matches:
        return None
    try:
        return float(matches[0].replace(",", ""))
    except ValueError:
        return None


def _extract_amount_after_phrase(text: str, phrase: str) -> float | None:
    pattern = re.escape(phrase) + r".{0,16}?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
    match = re.search(pattern, text)
    if match is None:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _extract_error_code(text: str) -> str | None:
    match = re.search(r"(E_[A-Z0-9_]{4,})", text)
    if match is None:
        return None
    return match.group(1)


def _extract_customer_id(text: str) -> str | None:
    match = re.search(r"(CUST[-_][0-9]{3,})", text)
    if match is None:
        return None
    return match.group(1).replace("_", "-")


def _extract_loan_account(text: str) -> str | None:
    match = re.search(r"(LN[-_][0-9]{4}[-_][0-9]{4})", text)
    if match is None:
        return None
    return match.group(1).replace("_", "-")


def _extract_date_token(text: str) -> str | None:
    match = re.search(r"(20\d{2}-\d{2}-\d{2})", text)
    if match is None:
        return None
    return match.group(1)


def _extract_datetime(text: str) -> str | None:
    match = re.search(r"(20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", text)
    if match is None:
        return None
    return match.group(1)


def _extract_merchant_code(text: str) -> str | None:
    match = re.search(r"(MCH[-_][0-9]{3,})", text)
    if match is None:
        return None
    return match.group(1).replace("_", "-")


def _extract_transaction_id(text: str) -> str | None:
    match = re.search(r"(TXN[-_][0-9]{6,})", text)
    if match is None:
        return None
    return match.group(1).replace("_", "-")


def _extract_old_address(text: str) -> str | None:
    match = re.search(r"旧地址[是为:： ]+([^，。;\n]+)", text)
    if match is None:
        return None
    return match.group(1).strip()


def _extract_new_address(text: str) -> str | None:
    match = re.search(r"新地址[请要为是:： ]+([^，。;\n]+)", text)
    if match is None:
        match = re.search(r"改为([^，。;\n]+)", text)
    if match is None:
        return None
    return match.group(1).strip()


def _mask_sensitive(text: str) -> str:
    text = re.sub(r"\b\d{16,}\b", "****", text)
    text = re.sub(r"(CUST[-_][0-9]{3,})", "CUST-****", text)
    text = re.sub(r"(TXN[-_][0-9]{6,})", "TXN-****", text)
    text = re.sub(r"(MCH[-_][0-9]{3,})", "MCH-***", text)
    text = re.sub(r"\d{4}[-/]\d{2}[-/]\d{2}T\d{2}:\d{2}:\d{2}", "TIMESTAMP", text)
    return text


def _parse_dt(value: Any) -> datetime:
    if not isinstance(value, str):
        raise RuntimeExecutionError("DATE_INVALID", "timestamp must be a string")
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeExecutionError("DATE_INVALID", value) from exc


def _stable_key(payload: dict[str, Any]) -> str:
    tokens = sorted(f"{key}={payload[key]}" for key in payload)
    raw = "|".join(tokens)
    return re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-").lower()[:48] or "item"
