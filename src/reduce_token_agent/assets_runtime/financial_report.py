"""Deterministic local handlers for the financial_report asset set."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
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


TOOL_CONSOLIDATION_REF = "tool.financial_report.consolidation.intercompany_eliminate@1.0.0"
FSM_RECONCILIATION_REF = "fsm.financial_report.reconciliation.balance_sheet_route@1.0.0"
FSM_PERFORMANCE_REF = "fsm.financial_report.performance.analysis_route@1.0.0"
VALIDATOR_RECONCILIATION_REF = "validator.financial_report.reconciliation.balance_sheet@1.0.0"
VALIDATOR_PERFORMANCE_REF = "validator.financial_report.performance.analysis@1.0.0"


class FinancialReportRuntime:
    """Execute the deterministic financial_report capability set."""

    TOOL_POLICY_VERSION = "financial-report-tools.synthetic.v1"
    NORMALIZATION_POLICY_VERSION = "financial-report-normalization.synthetic.v1"
    RECONCILIATION_POLICY_VERSION = "financial-report-reconciliation.synthetic.v1"
    PERFORMANCE_POLICY_VERSION = "financial-report-performance.synthetic.v1"
    CASHFLOW_POLICY_VERSION = "financial-report-cashflow.synthetic.v1"
    RECEIVABLE_POLICY_VERSION = "financial-report-receivable.synthetic.v1"
    SUMMARY_POLICY_VERSION = "financial-report-summary.synthetic.v1"
    DAEF_POLICY_VERSION = "financial-report-daef.synthetic.v1"

    POLICY_CATALOG: dict[str, dict[str, Any]] = {
        TOOL_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "no_external_io": True,
            "tools": [
                "metric_loader",
                "formula_batch",
                "intercompany_eliminate",
                "evidence_text_compose",
            ],
        },
        NORMALIZATION_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "deterministic": True,
            "views": [
                "balance_sheet",
                "segment_currency",
                "budget_account",
                "receivable_invoice",
            ],
        },
        RECONCILIATION_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "status_values": ["PASS", "RECONCILE_FAIL"],
            "manual_review_for_mismatch": True,
        },
        PERFORMANCE_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "analysis_kinds": [
                "income_yoy",
                "segment_performance",
                "budget_variance",
                "financial_ratios",
            ],
        },
        CASHFLOW_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "anomaly_score_range": [0, 100],
            "human_review_for_high_risk": True,
        },
        RECEIVABLE_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "bucket_keys": ["0_30", "31_60", "61_90", "90_plus"],
            "concentration_threshold": 0.35,
        },
        SUMMARY_POLICY_VERSION: {
            "synthetic": True,
            "read_only": True,
            "citations_required": True,
            "draft_only": True,
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
        "snapshot": ("LOAD_SYNTHETIC_FACTS", "RETURN_CONTROLLED_SNAPSHOT"),
        "formula": ("APPLY_DETERMINISTIC_FORMULA", "ROUND_AND_LOG"),
        "consolidation": ("NORMALIZE_SEGMENTS", "APPLY_INTERCOMPANY_ELIMINATION", "RETURN_VIEW"),
        "summary": ("SELECT_MATERIAL_ITEMS", "COMPOSE_EVIDENCE_TEXT", "RETURN_CITATIONS"),
        "normalization": ("MAP_FIELDS", "NORMALIZE_CODES_AND_UNITS", "RETURN_CONTRACTED_VIEW"),
        "reconciliation": ("LOAD_VIEW", "COMPUTE_VARIANCE", "ROUTE_REVIEW", "WAIT_VALIDATOR"),
        "performance": ("LOAD_FACTS", "CALCULATE_METRICS", "RANK_SIGNALS", "WAIT_VALIDATOR"),
        "cashflow": ("LOAD_CASHFLOW", "COMPARE_OCF_AND_NI", "SCORE_ANOMALY", "WAIT_VALIDATOR"),
        "receivable": (
            "NORMALIZE_INVOICES",
            "APPLY_PAYMENTS",
            "BUCKET_AGING",
            "ASSESS_CONCENTRATION",
            "WAIT_VALIDATOR",
        ),
        "management": ("LOAD_METRICS", "FILTER_MATERIAL", "COMPOSE_SUMMARY", "WAIT_VALIDATOR"),
        "validator": ("LOAD_PAYLOAD", "CHECK_STRUCTURE", "RETURN_FAILURE_CODES"),
        "daef": ("INFORMATION", "TRANSFORM", "DECISION", "ACTION", "VALIDATION"),
    }

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "tool.financial_report.snapshot.metric_loader@1.0.0": self.metric_snapshot_load,
            "tool.financial_report.calc.formula_batch@1.0.0": self.formula_batch_calculate,
            TOOL_CONSOLIDATION_REF: self.intercompany_eliminate,
            "tool.financial_report.summary.evidence_text_compose@1.0.0": self.evidence_text_compose,
            "adapter.financial_report.normalization.report_view@1.0.0": self.report_view_normalize,
            FSM_RECONCILIATION_REF: self.balance_sheet_reconciliation_route,
            FSM_PERFORMANCE_REF: self.performance_analysis_route,
            "fsm.financial_report.cashflow.anomaly_route@1.0.0": self.cashflow_anomaly_route,
            "fsm.financial_report.receivable.aging_route@1.0.0": self.receivable_aging_route,
            "fsm.financial_report.management.summary_route@1.0.0": self.management_summary_route,
            VALIDATOR_RECONCILIATION_REF: self.validate_balance_sheet_reconciliation,
            VALIDATOR_PERFORMANCE_REF: self.validate_performance_analysis,
            "validator.financial_report.cashflow.anomaly@1.0.0": self.validate_cashflow_anomaly,
            "validator.financial_report.receivable.aging@1.0.0": self.validate_receivable_aging,
            "validator.financial_report.management.summary@1.0.0": self.validate_management_summary,
        }
        self._planning_priors = {
            "skeleton.financial_report.analysis_daef@1.0.0": {
                "stages": [
                    "INFORMATION",
                    "TRANSFORM",
                    "DECISION",
                    "ACTION",
                    "VALIDATION",
                ],
                "directly_executable": False,
                "binds_asset_refs": False,
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
            "tool.financial_report.snapshot.metric_loader@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:metric_snapshot_load",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("财务快照只来自本地合成目录", "不访问真实外部系统"),
                "READ_ONLY",
            ),
            "tool.financial_report.calc.formula_batch@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:formula_batch_calculate",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("公式批处理必须可重复", "不写回报表系统"),
                "READ_ONLY",
            ),
            "tool.financial_report.consolidation.intercompany_eliminate@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:intercompany_eliminate",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("内部交易抵销只在本地视图上发生", "不生成真实会计分录"),
                "READ_ONLY",
            ),
            "tool.financial_report.summary.evidence_text_compose@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:evidence_text_compose",
                "EXECUTABLE",
                self.TOOL_POLICY_VERSION,
                ("摘要必须引用已验证指标", "不发布正式公告"),
                "READ_ONLY",
            ),
            "adapter.financial_report.normalization.report_view@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:report_view_normalize",
                "EXECUTABLE",
                self.NORMALIZATION_POLICY_VERSION,
                ("Adapter 只能做确定性字段与币种归一",),
                "NONE",
            ),
            "fsm.financial_report.reconciliation.balance_sheet_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:balance_sheet_reconciliation_route",
                "EXECUTABLE",
                self.RECONCILIATION_POLICY_VERSION,
                ("资产负债表勾稽失败也必须保留结构化复核边界",),
                "NONE",
            ),
            "fsm.financial_report.performance.analysis_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:performance_analysis_route",
                "EXECUTABLE",
                self.PERFORMANCE_POLICY_VERSION,
                ("同比、分部、预算和比率分析共享同一确定性路由",),
                "NONE",
            ),
            "fsm.financial_report.cashflow.anomaly_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:cashflow_anomaly_route",
                "EXECUTABLE",
                self.CASHFLOW_POLICY_VERSION,
                ("异常评分只决定人工复核，不修改分类",),
                "NONE",
            ),
            "fsm.financial_report.receivable.aging_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:receivable_aging_route",
                "EXECUTABLE",
                self.RECEIVABLE_POLICY_VERSION,
                ("应收账龄必须保留桶、总额和集中度证据",),
                "NONE",
            ),
            "fsm.financial_report.management.summary_route@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:management_summary_route",
                "EXECUTABLE",
                self.SUMMARY_POLICY_VERSION,
                ("摘要只能基于已验证且带引用的指标",),
                "NONE",
            ),
            "validator.financial_report.reconciliation.balance_sheet@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:validate_balance_sheet_reconciliation",
                "EXECUTABLE",
                self.RECONCILIATION_POLICY_VERSION,
                ("勾稽结果必须含状态、差额与人工复核边界",),
                "NONE",
            ),
            "validator.financial_report.performance.analysis@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:validate_performance_analysis",
                "EXECUTABLE",
                self.PERFORMANCE_POLICY_VERSION,
                ("分析结果必须含分析项和风险等级",),
                "NONE",
            ),
            "validator.financial_report.cashflow.anomaly@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:validate_cashflow_anomaly",
                "EXECUTABLE",
                self.CASHFLOW_POLICY_VERSION,
                ("异常结果必须含评分、标签与复核边界",),
                "NONE",
            ),
            "validator.financial_report.receivable.aging@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:validate_receivable_aging",
                "EXECUTABLE",
                self.RECEIVABLE_POLICY_VERSION,
                ("账龄结果必须含桶、总额与风险标签",),
                "NONE",
            ),
            "validator.financial_report.management.summary@1.0.0": RuntimeMetadata(
                "python://reduce_token_agent.assets_runtime.financial_report:validate_management_summary",
                "EXECUTABLE",
                self.SUMMARY_POLICY_VERSION,
                ("管理摘要必须含正文、引用与重大项",),
                "NONE",
            ),
            "skeleton.financial_report.analysis_daef@1.0.0": RuntimeMetadata(
                "daef://financial_report/analysis",
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
        balance_raw = {
            "asset_total": 1_200_000.0,
            "liability_total": 730_000.0,
            "equity_total": 469_500.0,
            "currency": "CNY",
        }
        ratio_metrics = {
            "current_assets": 500_000.0,
            "inventory": 80_000.0,
            "current_liabilities": 250_000.0,
            "total_debt": 600_000.0,
            "total_equity": 400_000.0,
            "ebit": 120_000.0,
            "interest_expense": 30_000.0,
        }
        segment_records = [
            {
                "segment_id": "CN_MAIN",
                "region": "China",
                "currency": "CNY",
                "revenue": 800_000.0,
                "profit": 120_000.0,
                "intercompany_revenue": 50_000.0,
                "fx_rate": 1.0,
            },
            {
                "segment_id": "US_OVERSEAS",
                "region": "United States",
                "currency": "USD",
                "revenue": 100_000.0,
                "profit": 20_000.0,
                "intercompany_revenue": 10_000.0,
                "fx_rate": 7.1,
            },
            {
                "segment_id": "EU_DISTRIBUTION",
                "region": "Europe",
                "currency": "EUR",
                "revenue": 50_000.0,
                "profit": 6_000.0,
                "intercompany_revenue": 5_000.0,
                "fx_rate": 7.8,
            },
        ]
        management_records = [
            {
                "metric_code": "revenue_yoy",
                "label": "收入同比",
                "current": 1_500_000.0,
                "prior": 1_200_000.0,
                "delta_pct": 0.25,
                "evidence_ref": "trace_syn_financial_report_02_income_yoy#step_04",
            },
            {
                "metric_code": "cashflow_coverage",
                "label": "经营现金流覆盖率",
                "current": 0.2857,
                "prior": 0.5000,
                "delta_pct": -0.2143,
                "evidence_ref": "trace_syn_financial_report_03_cashflow_anomaly#step_02",
            },
            {
                "metric_code": "receivable_concentration",
                "label": "应收集中度",
                "current": 0.7037,
                "prior": 0.5400,
                "delta_pct": 0.1637,
                "evidence_ref": "trace_syn_financial_report_08_receivable_aging#step_04",
            },
            {
                "metric_code": "budget_variance",
                "label": "预算偏差",
                "current": 0.12,
                "prior": 0.04,
                "delta_pct": 0.08,
                "evidence_ref": "trace_syn_financial_report_07_budget_variance#step_03",
            },
        ]
        balance_route_input = {
            "statement_snapshot": {
                "view_kind": "balance_sheet",
                "raw_payload": balance_raw,
            },
            "tolerance": 0.01,
        }
        balance_route_output = self.balance_sheet_reconciliation_route(balance_route_input)
        income_route_input = {
            "analysis_kind": "income_yoy",
            "metric_snapshot": {
                "source_key": "income_yoy_2026_q3",
                "statement_type": "income_statement",
            },
            "thresholds": {"materiality_ratio": 0.05},
        }
        income_route_output = self.performance_analysis_route(income_route_input)
        cashflow_route_input = {
            "cashflow_snapshot": {
                "source_key": "cashflow_2026_q3",
                "statement_type": "cashflow_statement",
            },
            "thresholds": {"ratio_floor": 0.5},
        }
        cashflow_route_output = self.cashflow_anomaly_route(cashflow_route_input)
        receivable_route_input = {
            "receivable_snapshot": {
                "source_key": "receivable_aging_2026_q2",
                "statement_type": "receivable_ledger",
            },
            "thresholds": {"high_concentration_ratio": 0.35, "overdue_90_ratio": 0.3},
        }
        receivable_route_output = self.receivable_aging_route(receivable_route_input)
        management_route_input = {
            "metric_bundle": {
                "source_key": "management_summary_2026_q4",
                "statement_type": "metric_bundle",
            },
            "materiality_threshold": 0.1,
        }
        management_route_output = self.management_summary_route(management_route_input)
        return {
            "tool.financial_report.snapshot.metric_loader@1.0.0": {
                "source_key": "balance_sheet_2026_q2",
                "statement_type": "balance_sheet",
            },
            "tool.financial_report.calc.formula_batch@1.0.0": {
                "calculation_kind": "financial_ratios",
                "metrics": ratio_metrics,
            },
            "tool.financial_report.consolidation.intercompany_eliminate@1.0.0": {
                "segments": segment_records,
                "reporting_currency": "CNY",
                "fx_rates": {"USD": 7.1, "EUR": 7.8},
            },
            "tool.financial_report.summary.evidence_text_compose@1.0.0": {
                "summary_kind": "management_summary",
                "key_metrics": management_records[:3],
                "evidence_refs": [record["evidence_ref"] for record in management_records[:3]],
            },
            "adapter.financial_report.normalization.report_view@1.0.0": {
                "view_kind": "balance_sheet",
                "raw_payload": balance_raw,
            },
            "fsm.financial_report.reconciliation.balance_sheet_route@1.0.0": balance_route_input,
            "fsm.financial_report.performance.analysis_route@1.0.0": income_route_input,
            "fsm.financial_report.cashflow.anomaly_route@1.0.0": cashflow_route_input,
            "fsm.financial_report.receivable.aging_route@1.0.0": receivable_route_input,
            "fsm.financial_report.management.summary_route@1.0.0": management_route_input,
            "validator.financial_report.reconciliation.balance_sheet@1.0.0": {
                "payload": balance_route_output
            },
            "validator.financial_report.performance.analysis@1.0.0": {
                "payload": income_route_output
            },
            "validator.financial_report.cashflow.anomaly@1.0.0": {"payload": cashflow_route_output},
            "validator.financial_report.receivable.aging@1.0.0": {
                "payload": receivable_route_output
            },
            "validator.financial_report.management.summary@1.0.0": {
                "payload": management_route_output
            },
            "skeleton.financial_report.analysis_daef@1.0.0": {
                "objective": "财务报表分析与验证",
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

    def metric_snapshot_load(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Read one stable synthetic financial snapshot."""
        source_key = _required_string(payload, "source_key")
        statement_type = _optional_string(payload, "statement_type")
        catalog = _snapshot_catalog()
        try:
            record = catalog[source_key]
        except KeyError as exc:
            raise RuntimeExecutionError("SNAPSHOT_NOT_FOUND", source_key) from exc
        if statement_type is not None and statement_type != record["snapshot_type"]:
            raise RuntimeExecutionError(
                "SNAPSHOT_TYPE_MISMATCH",
                f"{source_key} is {record['snapshot_type']}, not {statement_type}",
            )
        return {"source_key": source_key, **record}

    def formula_batch_calculate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute deterministic financial formulas in a batch."""
        calculation_kind = _required_string(payload, "calculation_kind")
        metrics = _required_dict(payload, "metrics")
        audit_log: list[str] = []
        if calculation_kind == "balance_variance":
            assets = _number(metrics, "total_assets")
            liabilities = _number(metrics, "total_liabilities")
            equity = _number(metrics, "total_equity")
            tolerance = float(metrics.get("tolerance", payload.get("tolerance", 0.01)))
            variance_amount = round(assets - liabilities - equity, 4)
            is_balanced = abs(variance_amount) <= tolerance
            audit_log.extend(
                [
                    "extract_total_assets",
                    "extract_total_liabilities",
                    "extract_total_equity",
                    "compute_variance",
                ]
            )
            return {
                "calculation_kind": calculation_kind,
                "results": {
                    "variance_amount": variance_amount,
                    "is_balanced": is_balanced,
                    "tolerance": tolerance,
                    "equation": "assets - liabilities - equity",
                },
                "audit_log": audit_log,
            }
        if calculation_kind == "income_yoy":
            current = _required_dict(metrics, "current_period")
            prior = _required_dict(metrics, "prior_period")
            revenue_yoy_pct = _pct_change(current, prior, "revenue")
            gross_profit_yoy_pct = _pct_change(current, prior, "gross_profit")
            expense_yoy_pct = _pct_change(current, prior, "expense")
            audit_log.extend(["align_periods", "compute_yoy", "round_percentages"])
            return {
                "calculation_kind": calculation_kind,
                "results": {
                    "revenue_yoy_pct": revenue_yoy_pct,
                    "gross_profit_yoy_pct": gross_profit_yoy_pct,
                    "expense_yoy_pct": expense_yoy_pct,
                },
                "audit_log": audit_log,
            }
        if calculation_kind == "financial_ratios":
            current_assets = _number(metrics, "current_assets")
            inventory = _number(metrics, "inventory")
            current_liabilities = _number(metrics, "current_liabilities")
            total_debt = _number(metrics, "total_debt")
            total_equity = _number(metrics, "total_equity")
            ebit = _number(metrics, "ebit")
            interest_expense = _number(metrics, "interest_expense")
            current_ratio = _safe_div(current_assets, current_liabilities)
            quick_ratio = _safe_div(current_assets - inventory, current_liabilities)
            debt_to_equity = _safe_div(total_debt, total_equity)
            interest_coverage = _safe_div(ebit, interest_expense)
            audit_log.extend(["compute_liquidity", "compute_leverage", "compute_coverage"])
            return {
                "calculation_kind": calculation_kind,
                "results": {
                    "current_ratio": round(current_ratio, 4),
                    "quick_ratio": round(quick_ratio, 4),
                    "debt_to_equity": round(debt_to_equity, 4),
                    "interest_coverage": round(interest_coverage, 4),
                },
                "audit_log": audit_log,
            }
        if calculation_kind == "budget_variance":
            lines = _records_from(metrics, "budget_lines")
            variances: list[dict[str, Any]] = []
            total_budget = 0.0
            total_actual = 0.0
            for line in lines:
                budget = _number(line, "budget")
                actual = _number(line, "actual")
                account_code = _required_string(line, "account_code")
                variance = round(actual - budget, 4)
                ratio = _safe_div(variance, budget)
                variances.append(
                    {
                        "account_code": account_code,
                        "budget": round(budget, 4),
                        "actual": round(actual, 4),
                        "variance": variance,
                        "variance_pct": round(ratio, 4),
                    }
                )
                total_budget += budget
                total_actual += actual
            audit_log.extend(["align_accounts", "compute_budget_variance", "rank_material_lines"])
            return {
                "calculation_kind": calculation_kind,
                "results": {
                    "line_items": variances,
                    "total_budget": round(total_budget, 4),
                    "total_actual": round(total_actual, 4),
                    "total_variance": round(total_actual - total_budget, 4),
                },
                "audit_log": audit_log,
            }
        raise RuntimeExecutionError("CALCULATION_KIND_UNSUPPORTED", calculation_kind)

    def intercompany_eliminate(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize segments and eliminate intercompany revenue."""
        segments = _records_from(payload, "segments")
        reporting_currency = _optional_string(payload, "reporting_currency") or "CNY"
        fx_rates = _optional_dict(payload, "fx_rates") or {}
        normalized_segments: list[dict[str, Any]] = []
        elimination_entries: list[dict[str, Any]] = []
        consolidated_revenue = 0.0
        for segment in segments:
            segment_id = _required_string(segment, "segment_id")
            region = _optional_string(segment, "region") or segment_id
            if {
                "revenue_reporting",
                "profit_reporting",
                "intercompany_revenue_reporting",
            }.issubset(segment):
                revenue_reporting = _number(segment, "revenue_reporting")
                profit_reporting = _number(segment, "profit_reporting")
                intercompany_reporting = _number(segment, "intercompany_revenue_reporting")
            else:
                currency = _optional_string(segment, "currency") or reporting_currency
                revenue = _number(segment, "revenue")
                profit = _number(segment, "profit")
                intercompany_revenue = _number(segment, "intercompany_revenue")
                fx_rate = float(segment.get("fx_rate", fx_rates.get(currency, 1.0)))
                revenue_reporting = _convert_amount(
                    revenue,
                    currency,
                    reporting_currency,
                    fx_rate,
                )
                profit_reporting = _convert_amount(
                    profit,
                    currency,
                    reporting_currency,
                    fx_rate,
                )
                intercompany_reporting = _convert_amount(
                    intercompany_revenue,
                    currency,
                    reporting_currency,
                    fx_rate,
                )
            net_revenue = round(revenue_reporting - intercompany_reporting, 4)
            normalized_segments.append(
                {
                    "segment_id": segment_id,
                    "region": region,
                    "currency": reporting_currency,
                    "revenue_reporting": revenue_reporting,
                    "profit_reporting": profit_reporting,
                    "intercompany_revenue_reporting": intercompany_reporting,
                    "net_revenue_reporting": net_revenue,
                }
            )
            elimination_entries.append(
                {
                    "segment_id": segment_id,
                    "eliminated_revenue": round(intercompany_reporting, 4),
                    "reason": "INTERCOMPANY_REVENUE",
                }
            )
            consolidated_revenue += net_revenue
        if consolidated_revenue < 0:
            raise RuntimeExecutionError("NEGATIVE_CONSOLIDATION", "consolidated revenue < 0")
        return {
            "segments": normalized_segments,
            "consolidated_revenue": round(consolidated_revenue, 4),
            "elimination_entries": elimination_entries,
        }

    def evidence_text_compose(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Compose a short evidence-based financial summary draft."""
        summary_kind = _required_string(payload, "summary_kind")
        key_metrics = _records_from(payload, "key_metrics")
        evidence_refs = _string_list(payload, "evidence_refs")
        if not evidence_refs:
            raise RuntimeExecutionError("CITATION_MISSING", "evidence_refs cannot be empty")
        prefix = _summary_prefix(summary_kind)
        parts: list[str] = []
        for metric in key_metrics:
            label = _optional_string(metric, "label") or _optional_string(metric, "metric_code")
            if label is None:
                raise RuntimeExecutionError("SUMMARY_METRIC_INVALID", "metric label missing")
            value = metric.get("current", metric.get("value", metric.get("delta_pct")))
            note = _optional_string(metric, "note")
            parts.append(_compose_metric_fragment(label, value, note))
        if not parts:
            raise RuntimeExecutionError("SUMMARY_KIND_UNSUPPORTED", summary_kind)
        summary_text = f"{prefix}：{'；'.join(parts)}。"
        return {
            "summary_text": summary_text,
            "citations": evidence_refs,
            "length_ok": len(summary_text) <= 240,
        }

    def report_view_normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Normalize fields and currencies into a stable analysis view."""
        view_kind = _required_string(payload, "view_kind")
        raw_payload = _required_dict(payload, "raw_payload")
        if view_kind == "balance_sheet":
            normalized_payload = {
                "total_assets": _number_from_aliases(raw_payload, "asset_total", "total_assets"),
                "total_liabilities": _number_from_aliases(
                    raw_payload,
                    "liability_total",
                    "total_liabilities",
                ),
                "total_equity": _number_from_aliases(raw_payload, "equity_total", "total_equity"),
                "currency": _optional_string(raw_payload, "currency") or "CNY",
            }
            return {
                "view_kind": view_kind,
                "normalized_payload": normalized_payload,
                "applied_rules": ["MAP_BALANCE_TOTALS", "STANDARDIZE_CURRENCY"],
            }
        if view_kind == "segment_currency":
            records = _records_from(raw_payload, "records")
            reporting_currency = _optional_string(raw_payload, "reporting_currency") or "CNY"
            fx_rates = _optional_dict(raw_payload, "fx_rates") or {}
            normalized_segments = [
                _normalize_segment_record(record, reporting_currency, fx_rates)
                for record in records
            ]
            return {
                "view_kind": view_kind,
                "normalized_payload": {
                    "segments": normalized_segments,
                    "reporting_currency": reporting_currency,
                },
                "applied_rules": ["NORMALIZE_SEGMENT_CURRENCY"],
            }
        if view_kind == "budget_account":
            records = _records_from(raw_payload, "records")
            normalized_lines = []
            for record in records:
                normalized_lines.append(
                    {
                        "account_code": _normalize_account_code(record),
                        "budget": _number(record, "budget"),
                        "actual": _number(record, "actual"),
                    }
                )
            return {
                "view_kind": view_kind,
                "normalized_payload": {"budget_lines": normalized_lines},
                "applied_rules": ["MAP_BUDGET_ACCOUNT_CODES"],
            }
        if view_kind == "receivable_invoice":
            records = _records_from(raw_payload, "records")
            as_of_date = _optional_string(raw_payload, "as_of_date") or "2026-06-30"
            normalized_records = []
            for record in records:
                normalized_records.append(
                    {
                        "invoice_id": _required_string(record, "invoice_id"),
                        "customer_id": _normalize_customer_id(record),
                        "invoice_date": _required_string(record, "invoice_date"),
                        "due_date": _required_string(record, "due_date"),
                        "amount": _number(record, "amount"),
                        "payments": _number(record, "payments"),
                        "credit_notes": _number(record, "credit_notes"),
                        "currency": _optional_string(record, "currency") or "CNY",
                    }
                )
            return {
                "view_kind": view_kind,
                "normalized_payload": {
                    "records": normalized_records,
                    "as_of_date": as_of_date,
                },
                "applied_rules": ["NORMALIZE_INVOICE_CUSTOMER", "STANDARDIZE_DATES"],
            }
        raise RuntimeExecutionError("VIEW_KIND_UNSUPPORTED", view_kind)

    def balance_sheet_reconciliation_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Route balance sheet reconciliation into a stable structural result."""
        snapshot = _required_dict(payload, "statement_snapshot")
        tolerance = float(payload.get("tolerance", 0.01))
        normalized = self.report_view_normalize(
            {"view_kind": "balance_sheet", "raw_payload": _extract_snapshot_payload(snapshot)}
        )
        calculation = self.formula_batch_calculate(
            {
                "calculation_kind": "balance_variance",
                "metrics": normalized["normalized_payload"],
                "tolerance": tolerance,
            }
        )
        variance_amount = float(calculation["results"]["variance_amount"])
        is_balanced = bool(calculation["results"]["is_balanced"])
        if is_balanced:
            reconciliation_status = "PASS"
            discrepancies: list[dict[str, Any]] = []
        else:
            reconciliation_status = "RECONCILE_FAIL"
            discrepancies = [
                {
                    "code": "EQUATION_MISMATCH",
                    "amount": variance_amount,
                    "field": "balance_equation",
                },
                {
                    "code": "HUMAN_REVIEW_REQUIRED",
                    "amount": variance_amount,
                    "field": "review_boundary",
                },
            ]
        return {
            "reconciliation_status": reconciliation_status,
            "variance_amount": variance_amount,
            "is_balanced": is_balanced,
            "discrepancies": discrepancies,
            "human_review_required": not is_balanced,
        }

    def performance_analysis_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Analyze income, segment, budget, or ratio performance deterministically."""
        analysis_kind = _required_string(payload, "analysis_kind")
        metric_snapshot = _required_dict(payload, "metric_snapshot")
        thresholds = _optional_dict(payload, "thresholds") or {}
        snapshot = self.metric_snapshot_load(metric_snapshot)
        if analysis_kind == "income_yoy":
            formula = self.formula_batch_calculate(
                {
                    "calculation_kind": "income_yoy",
                    "metrics": snapshot["metrics"],
                }
            )
            results = formula["results"]
            revenue_yoy_pct = float(results["revenue_yoy_pct"])
            gross_profit_yoy_pct = float(results["gross_profit_yoy_pct"])
            analysis_items = [
                {
                    "metric": "revenue_yoy_pct",
                    "value": revenue_yoy_pct,
                    "comment": "收入同比变化",
                },
                {
                    "metric": "gross_profit_yoy_pct",
                    "value": gross_profit_yoy_pct,
                    "comment": "毛利同比变化",
                },
            ]
            risk_level = _risk_from_pct(
                revenue_yoy_pct, negative_threshold=-0.1, warn_threshold=0.15
            )
            human_review_required = risk_level == "HIGH" or revenue_yoy_pct < 0
            return {
                "analysis_kind": analysis_kind,
                "analysis_items": analysis_items,
                "risk_level": risk_level,
                "human_review_required": human_review_required,
            }
        if analysis_kind == "segment_performance":
            normalized = self.report_view_normalize(
                {"view_kind": "segment_currency", "raw_payload": snapshot}
            )
            consolidated = self.intercompany_eliminate(
                {
                    "segments": normalized["normalized_payload"]["segments"],
                    "reporting_currency": normalized["normalized_payload"]["reporting_currency"],
                }
            )
            segments = list(consolidated["segments"])
            segments.sort(key=lambda item: float(item["net_revenue_reporting"]), reverse=True)
            total_revenue = float(consolidated["consolidated_revenue"])
            top_share = (
                float(segments[0]["net_revenue_reporting"]) / total_revenue
                if segments and total_revenue
                else 0.0
            )
            threshold = float(thresholds.get("concentration_ratio", 0.35))
            risk_level = (
                "HIGH"
                if top_share >= threshold
                or any(float(segment["profit_reporting"]) < 0 for segment in segments)
                else "MEDIUM"
            )
            analysis_items = [
                {
                    "segment_id": segment["segment_id"],
                    "net_revenue_reporting": segment["net_revenue_reporting"],
                    "profit_reporting": segment["profit_reporting"],
                }
                for segment in segments
            ]
            return {
                "analysis_kind": analysis_kind,
                "analysis_items": analysis_items,
                "risk_level": risk_level,
                "human_review_required": risk_level == "HIGH",
            }
        if analysis_kind == "budget_variance":
            normalized = self.report_view_normalize(
                {"view_kind": "budget_account", "raw_payload": snapshot}
            )
            formula = self.formula_batch_calculate(
                {
                    "calculation_kind": "budget_variance",
                    "metrics": normalized["normalized_payload"],
                }
            )
            line_items = list(formula["results"]["line_items"])
            materiality = float(thresholds.get("materiality_ratio", 0.1))
            material_lines = [
                item for item in line_items if abs(float(item["variance_pct"])) >= materiality
            ]
            risk_level = "HIGH" if material_lines else "LOW"
            return {
                "analysis_kind": analysis_kind,
                "analysis_items": material_lines or line_items,
                "risk_level": risk_level,
                "human_review_required": bool(material_lines),
            }
        if analysis_kind == "financial_ratios":
            formula = self.formula_batch_calculate(
                {
                    "calculation_kind": "financial_ratios",
                    "metrics": snapshot["metrics"],
                }
            )
            results = formula["results"]
            current_ratio = float(results["current_ratio"])
            quick_ratio = float(results["quick_ratio"])
            debt_to_equity = float(results["debt_to_equity"])
            interest_coverage = float(results["interest_coverage"])
            minimum_current_ratio = float(thresholds.get("minimum_current_ratio", 1.0))
            minimum_interest_coverage = float(thresholds.get("minimum_interest_coverage", 2.0))
            risk_level = "HIGH"
            if (
                current_ratio >= minimum_current_ratio
                and interest_coverage >= minimum_interest_coverage
            ):
                risk_level = "LOW" if debt_to_equity <= 1.5 else "MEDIUM"
            elif current_ratio >= minimum_current_ratio * 0.8:
                risk_level = "MEDIUM"
            analysis_items = [
                {"metric": "current_ratio", "value": current_ratio},
                {"metric": "quick_ratio", "value": quick_ratio},
                {"metric": "debt_to_equity", "value": debt_to_equity},
                {"metric": "interest_coverage", "value": interest_coverage},
            ]
            return {
                "analysis_kind": analysis_kind,
                "analysis_items": analysis_items,
                "risk_level": risk_level,
                "human_review_required": risk_level != "LOW",
            }
        raise RuntimeExecutionError("ANALYSIS_KIND_UNSUPPORTED", analysis_kind)

    def cashflow_anomaly_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Score cashflow divergence and return a review boundary."""
        cashflow_snapshot = _required_dict(payload, "cashflow_snapshot")
        thresholds = _optional_dict(payload, "thresholds") or {}
        snapshot = self.metric_snapshot_load(cashflow_snapshot)
        metrics = snapshot["metrics"]
        operating_cashflow = _number(metrics, "operating_cashflow")
        net_income = _number(metrics, "net_income")
        investing_cashflow = _number(metrics, "investing_cashflow")
        financing_cashflow = _number(metrics, "financing_cashflow")
        ratio_floor = float(thresholds.get("ratio_floor", 0.5))
        ocf_to_net_income_ratio = _safe_div(abs(operating_cashflow), abs(net_income))
        divergence_ratio = abs(net_income - operating_cashflow) / max(abs(net_income), 1.0)
        score = 0.0
        score += min(divergence_ratio * 70.0, 70.0)
        score += max(0.0, (ratio_floor - ocf_to_net_income_ratio) * 60.0)
        if investing_cashflow < 0:
            score += min(abs(investing_cashflow) / max(abs(net_income), 1.0) * 5.0, 10.0)
        if financing_cashflow > 0:
            score += 4.0
        anomaly_score = round(min(score, 100.0), 1)
        anomaly_flags = []
        if ocf_to_net_income_ratio < ratio_floor:
            anomaly_flags.append("OCF_BELOW_NET_INCOME")
        if investing_cashflow < 0:
            anomaly_flags.append("INVESTING_OUTFLOW")
        if financing_cashflow > 0:
            anomaly_flags.append("FINANCING_SUPPORT")
        risk_level = (
            "HIGH" if anomaly_score >= 70.0 or ocf_to_net_income_ratio < ratio_floor else "MEDIUM"
        )
        return {
            "anomaly_score": anomaly_score,
            "risk_level": risk_level,
            "anomaly_flags": anomaly_flags,
            "human_review_required": risk_level == "HIGH",
            "ocf_to_net_income_ratio": round(ocf_to_net_income_ratio, 4),
            "divergence_ratio": round(divergence_ratio, 4),
        }

    def receivable_aging_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Bucket receivables by aging and assess concentration risk."""
        receivable_snapshot = _required_dict(payload, "receivable_snapshot")
        thresholds = _optional_dict(payload, "thresholds") or {}
        snapshot = self.metric_snapshot_load(receivable_snapshot)
        normalized = self.report_view_normalize(
            {"view_kind": "receivable_invoice", "raw_payload": snapshot}
        )
        normalized_payload = normalized["normalized_payload"]
        records = _records_from(normalized_payload, "records")
        as_of_date = _parse_date(_required_string(normalized_payload, "as_of_date"))
        buckets = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "90_plus": 0.0}
        customer_totals: dict[str, float] = {}
        total_receivable = 0.0
        for record in records:
            outstanding = (
                _number(record, "amount")
                - _number(record, "payments")
                - _number(record, "credit_notes")
            )
            outstanding = round(max(outstanding, 0.0), 4)
            due_date = _parse_date(_required_string(record, "due_date"))
            age_days = max((as_of_date - due_date).days, 0)
            bucket = _aging_bucket(age_days)
            buckets[bucket] += outstanding
            customer_id = _required_string(record, "customer_id")
            customer_totals[customer_id] = customer_totals.get(customer_id, 0.0) + outstanding
            total_receivable += outstanding
        concentration_ratio = (
            max(customer_totals.values()) / total_receivable if total_receivable else 0.0
        )
        overdue_90_share = buckets["90_plus"] / total_receivable if total_receivable else 0.0
        high_concentration_ratio = float(thresholds.get("high_concentration_ratio", 0.35))
        overdue_90_ratio = float(thresholds.get("overdue_90_ratio", 0.3))
        risk_level = "HIGH"
        if concentration_ratio < high_concentration_ratio and overdue_90_share < overdue_90_ratio:
            risk_level = "MEDIUM" if total_receivable else "LOW"
        return {
            "aging_buckets": {key: round(value, 4) for key, value in buckets.items()},
            "total_receivable": round(total_receivable, 4),
            "concentration_ratio": round(concentration_ratio, 4),
            "risk_level": risk_level,
            "human_review_required": risk_level == "HIGH",
            "customer_totals": {
                customer_id: round(amount, 4) for customer_id, amount in customer_totals.items()
            },
            "overdue_90_share": round(overdue_90_share, 4),
        }

    def management_summary_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Filter material metrics and compose a cited summary draft."""
        metric_bundle = _required_dict(payload, "metric_bundle")
        materiality_threshold = float(payload.get("materiality_threshold", 0.1))
        snapshot = self.metric_snapshot_load(metric_bundle)
        records = _records_from(snapshot, "records")
        material_items: list[dict[str, Any]] = []
        for record in records:
            delta_pct = float(record.get("delta_pct", 0.0))
            if abs(delta_pct) >= materiality_threshold:
                material_items.append(
                    {
                        "label": _required_string(record, "label"),
                        "value": record.get("current", record.get("value")),
                        "delta_pct": delta_pct,
                        "evidence_ref": _required_string(record, "evidence_ref"),
                    }
                )
        if not material_items:
            raise RuntimeExecutionError("MATERIALITY_EMPTY", "no material items selected")
        summary = self.evidence_text_compose(
            {
                "summary_kind": "management_summary",
                "key_metrics": material_items,
                "evidence_refs": [item["evidence_ref"] for item in material_items],
            }
        )
        return {
            "summary_text": summary["summary_text"],
            "material_items": material_items,
            "citations": summary["citations"],
            "human_review_required": any(
                abs(float(item["delta_pct"])) >= 0.2 for item in material_items
            ),
        }

    def validate_balance_sheet_reconciliation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate balance sheet reconciliation results."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        status = candidate.get("reconciliation_status")
        if status not in {"PASS", "RECONCILE_FAIL"}:
            failure_codes.append("RECONCILIATION_STATUS_INVALID")
        if not isinstance(candidate.get("variance_amount"), (int, float)):
            failure_codes.append("VARIANCE_MISSING")
        if not isinstance(candidate.get("is_balanced"), bool):
            failure_codes.append("BALANCE_FLAG_MISSING")
        if not isinstance(candidate.get("discrepancies"), list):
            failure_codes.append("DISCREPANCIES_MISSING")
        if candidate.get("human_review_required") is None:
            failure_codes.append("REVIEW_ROUTE_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}

    def validate_performance_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate performance analysis results."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        if candidate.get("analysis_kind") not in {
            "income_yoy",
            "segment_performance",
            "budget_variance",
            "financial_ratios",
        }:
            failure_codes.append("ANALYSIS_KIND_INVALID")
        if not isinstance(candidate.get("analysis_items"), list) or not candidate["analysis_items"]:
            failure_codes.append("ANALYSIS_ITEMS_MISSING")
        if candidate.get("risk_level") not in {"LOW", "MEDIUM", "HIGH"}:
            failure_codes.append("RISK_LEVEL_INVALID")
        if not isinstance(candidate.get("human_review_required"), bool):
            failure_codes.append("REVIEW_ROUTE_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}

    def validate_cashflow_anomaly(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate cashflow anomaly scoring results."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        anomaly_score = candidate.get("anomaly_score")
        if not isinstance(anomaly_score, (int, float)) or not 0 <= float(anomaly_score) <= 100:
            failure_codes.append("SCORE_OUT_OF_RANGE")
        if candidate.get("risk_level") not in {"LOW", "MEDIUM", "HIGH"}:
            failure_codes.append("RISK_LEVEL_INVALID")
        if not isinstance(candidate.get("anomaly_flags"), list) or not candidate["anomaly_flags"]:
            failure_codes.append("ANOMALY_FLAGS_MISSING")
        if not isinstance(candidate.get("human_review_required"), bool):
            failure_codes.append("REVIEW_ROUTE_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}

    def validate_receivable_aging(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate receivable aging results."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        buckets = candidate.get("aging_buckets")
        if not isinstance(buckets, dict):
            failure_codes.append("AGING_BUCKETS_MISSING")
        else:
            expected_keys = {"0_30", "31_60", "61_90", "90_plus"}
            if expected_keys - set(buckets):
                failure_codes.append("AGING_BUCKETS_MISSING")
        if (
            not isinstance(candidate.get("total_receivable"), (int, float))
            or float(candidate["total_receivable"]) < 0
        ):
            failure_codes.append("TOTAL_INVALID")
        if candidate.get("risk_level") not in {"LOW", "MEDIUM", "HIGH"}:
            failure_codes.append("RISK_LEVEL_INVALID")
        if not isinstance(candidate.get("human_review_required"), bool):
            failure_codes.append("REVIEW_ROUTE_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}

    def validate_management_summary(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Validate management summary draft results."""
        candidate = _unwrap_payload(payload)
        failure_codes: list[str] = []
        if (
            not isinstance(candidate.get("summary_text"), str)
            or not candidate["summary_text"].strip()
        ):
            failure_codes.append("SUMMARY_EMPTY")
        if not isinstance(candidate.get("material_items"), list) or not candidate["material_items"]:
            failure_codes.append("MATERIAL_ITEMS_MISSING")
        if not isinstance(candidate.get("citations"), list) or not candidate["citations"]:
            failure_codes.append("CITATION_MISSING")
        if not isinstance(candidate.get("human_review_required"), bool):
            failure_codes.append("REVIEW_ROUTE_MISSING")
        return {"valid": not failure_codes, "failure_codes": failure_codes}


def _flow_key(asset_ref: str) -> str:
    if asset_ref.startswith("tool.financial_report.snapshot."):
        return "snapshot"
    if asset_ref.startswith("tool.financial_report.calc."):
        return "formula"
    if asset_ref.startswith("tool.financial_report.consolidation."):
        return "consolidation"
    if asset_ref.startswith("tool.financial_report.summary."):
        return "summary"
    if asset_ref.startswith("adapter.financial_report.normalization."):
        return "normalization"
    if asset_ref.startswith("fsm.financial_report.reconciliation."):
        return "reconciliation"
    if asset_ref.startswith("fsm.financial_report.performance."):
        return "performance"
    if asset_ref.startswith("fsm.financial_report.cashflow."):
        return "cashflow"
    if asset_ref.startswith("fsm.financial_report.receivable."):
        return "receivable"
    if asset_ref.startswith("fsm.financial_report.management."):
        return "management"
    if asset_ref.startswith("validator.financial_report."):
        return "validator"
    return "daef"


def _snapshot_catalog() -> dict[str, dict[str, Any]]:
    return {
        "balance_sheet_2026_q2": {
            "snapshot_type": "balance_sheet",
            "period": "2026-Q2",
            "metrics": {
                "total_assets": 1_200_000.0,
                "total_liabilities": 730_000.0,
                "total_equity": 469_500.0,
                "currency": "CNY",
            },
            "records": [
                {"line_item": "total_assets", "value": 1_200_000.0},
                {"line_item": "total_liabilities", "value": 730_000.0},
                {"line_item": "total_equity", "value": 469_500.0},
            ],
            "notes": [
                "资产负债表存在 500 元可解释差额，用于验证 RECONCILE_FAIL 路径。",
            ],
        },
        "income_yoy_2026_q3": {
            "snapshot_type": "income_statement",
            "period": "2026-Q3",
            "metrics": {
                "current_period": {
                    "revenue": 1_500_000.0,
                    "gross_profit": 520_000.0,
                    "expense": 300_000.0,
                },
                "prior_period": {
                    "revenue": 1_200_000.0,
                    "gross_profit": 410_000.0,
                    "expense": 250_000.0,
                },
                "currency": "CNY",
            },
            "records": [
                {"metric": "revenue", "current": 1_500_000.0, "prior": 1_200_000.0},
                {"metric": "gross_profit", "current": 520_000.0, "prior": 410_000.0},
                {"metric": "expense", "current": 300_000.0, "prior": 250_000.0},
            ],
        },
        "cashflow_2026_q3": {
            "snapshot_type": "cashflow_statement",
            "period": "2026-Q3",
            "metrics": {
                "operating_cashflow": 120_000.0,
                "net_income": 420_000.0,
                "investing_cashflow": -90_000.0,
                "financing_cashflow": 30_000.0,
            },
            "records": [
                {"label": "经营现金流", "value": 120_000.0},
                {"label": "净利润", "value": 420_000.0},
                {"label": "投资现金流", "value": -90_000.0},
                {"label": "筹资现金流", "value": 30_000.0},
            ],
        },
        "ratios_2026_q4": {
            "snapshot_type": "metrics",
            "period": "2026-Q4",
            "metrics": {
                "current_assets": 500_000.0,
                "inventory": 80_000.0,
                "current_liabilities": 250_000.0,
                "total_debt": 600_000.0,
                "total_equity": 400_000.0,
                "ebit": 120_000.0,
                "interest_expense": 30_000.0,
            },
            "records": [],
        },
        "segment_2026_q4": {
            "snapshot_type": "segment_report",
            "period": "2026-Q4",
            "metrics": {},
            "records": [
                {
                    "segment_id": "CN_MAIN",
                    "region": "China",
                    "currency": "CNY",
                    "revenue": 800_000.0,
                    "profit": 120_000.0,
                    "intercompany_revenue": 50_000.0,
                    "fx_rate": 1.0,
                },
                {
                    "segment_id": "US_OVERSEAS",
                    "region": "United States",
                    "currency": "USD",
                    "revenue": 100_000.0,
                    "profit": 20_000.0,
                    "intercompany_revenue": 10_000.0,
                    "fx_rate": 7.1,
                },
                {
                    "segment_id": "EU_DISTRIBUTION",
                    "region": "Europe",
                    "currency": "EUR",
                    "revenue": 50_000.0,
                    "profit": 6_000.0,
                    "intercompany_revenue": 5_000.0,
                    "fx_rate": 7.8,
                },
            ],
        },
        "budget_2026_q4": {
            "snapshot_type": "budget_report",
            "period": "2026-Q4",
            "metrics": {},
            "records": [
                {
                    "account_alias": "R&D-Cloud",
                    "account_code": "RD_CLOUD",
                    "budget": 120_000.0,
                    "actual": 138_000.0,
                },
                {
                    "account_alias": "Sales-Marketing",
                    "account_code": "SMKT",
                    "budget": 200_000.0,
                    "actual": 182_000.0,
                },
                {
                    "account_alias": "G&A",
                    "account_code": "GA",
                    "budget": 150_000.0,
                    "actual": 149_000.0,
                },
            ],
        },
        "receivable_aging_2026_q2": {
            "snapshot_type": "receivable_ledger",
            "period": "2026-Q2",
            "as_of_date": "2026-06-30",
            "metrics": {},
            "records": [
                {
                    "invoice_id": "INV-A001",
                    "customer_alias": "A星科技股份有限公司",
                    "amount": 180_000.0,
                    "payments": 50_000.0,
                    "credit_notes": 0.0,
                    "invoice_date": "2026-03-01",
                    "due_date": "2026-05-15",
                    "currency": "CNY",
                },
                {
                    "invoice_id": "INV-B002",
                    "customer_alias": "B智造集团",
                    "amount": 90_000.0,
                    "payments": 10_000.0,
                    "credit_notes": 0.0,
                    "invoice_date": "2026-02-15",
                    "due_date": "2026-04-10",
                    "currency": "CNY",
                },
                {
                    "invoice_id": "INV-A003",
                    "customer_alias": "A星科技",
                    "amount": 60_000.0,
                    "payments": 0.0,
                    "credit_notes": 0.0,
                    "invoice_date": "2026-01-10",
                    "due_date": "2026-03-01",
                    "currency": "CNY",
                },
            ],
        },
        "management_summary_2026_q4": {
            "snapshot_type": "metric_bundle",
            "period": "2026-Q4",
            "metrics": {},
            "records": [
                {
                    "metric_code": "revenue_yoy",
                    "label": "收入同比",
                    "current": 1_500_000.0,
                    "prior": 1_200_000.0,
                    "delta_pct": 0.25,
                    "evidence_ref": "trace_syn_financial_report_02_income_yoy#step_04",
                },
                {
                    "metric_code": "cashflow_coverage",
                    "label": "经营现金流覆盖率",
                    "current": 0.2857,
                    "prior": 0.5,
                    "delta_pct": -0.2143,
                    "evidence_ref": "trace_syn_financial_report_03_cashflow_anomaly#step_02",
                },
                {
                    "metric_code": "receivable_concentration",
                    "label": "应收集中度",
                    "current": 0.7037,
                    "prior": 0.54,
                    "delta_pct": 0.1637,
                    "evidence_ref": "trace_syn_financial_report_08_receivable_aging#step_04",
                },
                {
                    "metric_code": "budget_variance",
                    "label": "预算偏差",
                    "current": 0.12,
                    "prior": 0.04,
                    "delta_pct": 0.08,
                    "evidence_ref": "trace_syn_financial_report_07_budget_variance#step_03",
                },
            ],
        },
    }


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


def _number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be numeric")
    return float(value)


def _string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be a list of strings")
    return [item for item in value if item]


def _records_from(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeExecutionError("INPUT_INVALID", f"{key} must be a list of objects")
    return [dict(item) for item in value]


def _unwrap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) == {"payload"} and isinstance(payload["payload"], dict):
        return payload["payload"]
    return payload


def _safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _pct_change(current: dict[str, Any], prior: dict[str, Any], key: str) -> float:
    current_value = _number(current, key)
    prior_value = _number(prior, key)
    if prior_value == 0:
        return 0.0
    return round((current_value - prior_value) / abs(prior_value), 4)


def _risk_from_pct(value: float, *, negative_threshold: float, warn_threshold: float) -> str:
    if value <= negative_threshold:
        return "HIGH"
    if value <= warn_threshold:
        return "MEDIUM"
    return "LOW"


def _convert_amount(
    amount: float,
    currency: str,
    reporting_currency: str,
    fx_rate: float,
) -> float:
    if currency == reporting_currency:
        return round(amount, 4)
    return round(amount * fx_rate, 4)


def _normalize_segment_record(
    record: dict[str, Any],
    reporting_currency: str,
    fx_rates: dict[str, Any],
) -> dict[str, Any]:
    currency = _optional_string(record, "currency") or reporting_currency
    fx_rate = float(record.get("fx_rate", fx_rates.get(currency, 1.0)))
    revenue = _number(record, "revenue")
    profit = _number(record, "profit")
    intercompany_revenue = _number(record, "intercompany_revenue")
    return {
        "segment_id": _required_string(record, "segment_id"),
        "region": _optional_string(record, "region") or _required_string(record, "segment_id"),
        "currency": reporting_currency,
        "revenue_reporting": _convert_amount(revenue, currency, reporting_currency, fx_rate),
        "profit_reporting": _convert_amount(profit, currency, reporting_currency, fx_rate),
        "intercompany_revenue_reporting": _convert_amount(
            intercompany_revenue,
            currency,
            reporting_currency,
            fx_rate,
        ),
    }


def _normalize_account_code(record: dict[str, Any]) -> str:
    alias = _optional_string(record, "account_alias") or _optional_string(record, "account_name")
    if alias is None:
        return _required_string(record, "account_code")
    normalized = alias.upper().replace("-", "_").replace(" ", "_")
    normalized = normalized.replace("&", "AND")
    return _required_string(record, "account_code") if not normalized else normalized[:32]


def _normalize_customer_id(record: dict[str, Any]) -> str:
    alias = _optional_string(record, "customer_alias")
    if alias is None:
        return _required_string(record, "customer_id")
    alias_map = {
        "A星科技股份有限公司": "CUST-A001",
        "A星科技": "CUST-A001",
        "B智造集团": "CUST-B002",
    }
    return alias_map.get(
        alias, "CUST-" + alias[:8].upper().replace(" ", "").replace("股份有限公司", "")
    )


def _number_from_aliases(payload: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    raise RuntimeExecutionError("INPUT_INVALID", f"none of {keys} found as numeric fields")


def _extract_snapshot_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    if "raw_payload" in snapshot and isinstance(snapshot["raw_payload"], dict):
        return dict(snapshot["raw_payload"])
    if "normalized_payload" in snapshot and isinstance(snapshot["normalized_payload"], dict):
        return dict(snapshot["normalized_payload"])
    return dict(snapshot)


def _compose_metric_fragment(label: str, value: Any, note: str | None) -> str:
    if isinstance(value, (int, float)):
        rendered = f"{float(value):.1%}" if abs(float(value)) <= 1.0 else f"{float(value):,.0f}"
    else:
        rendered = str(value)
    if note:
        return f"{label}{rendered}（{note}）"
    return f"{label}{rendered}"


def _summary_prefix(summary_kind: str) -> str:
    prefixes = {
        "management_summary": "管理层财务摘要",
        "income_yoy": "利润同比摘要",
        "budget_variance": "预算偏差摘要",
        "segment_performance": "分部表现摘要",
        "cashflow_anomaly": "现金流异常摘要",
        "receivable_aging": "应收账龄摘要",
    }
    try:
        return prefixes[summary_kind]
    except KeyError as exc:
        raise RuntimeExecutionError("SUMMARY_KIND_UNSUPPORTED", summary_kind) from exc


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeExecutionError("DATE_INVALID", value) from exc


def _aging_bucket(age_days: int) -> str:
    if age_days <= 30:
        return "0_30"
    if age_days <= 60:
        return "31_60"
    if age_days <= 90:
        return "61_90"
    return "90_plus"
