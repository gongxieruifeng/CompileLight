"""Curated Kind assets extracted from financial_report synthetic traces."""

from __future__ import annotations

from typing import Any, Literal

from reduce_token_agent.registry.models import (
    AdapterBody,
    AssetBody,
    AssetContract,
    AssetDefinition,
    AssetKind,
    CapabilityEdge,
    EdgeType,
    FsmShardBody,
    JsonObjectSchema,
    PrimitiveToolBody,
    RecallPolicy,
    ReleaseStatus,
    RiskLevel,
    RouteHeader,
    SideEffect,
    SourceEvidence,
    ValidatorBody,
    WorkflowSkeletonBody,
)

DOMAIN: Literal["financial_report"] = "financial_report"
OWNER: Literal["financial_report_poc"] = "financial_report_poc"
SUITE_REF: Literal["suite.financial_report.kind_contract@1.0.0"] = (
    "suite.financial_report.kind_contract@1.0.0"
)


def _schema(
    title: str,
    properties: dict[str, dict[str, Any]],
    required: list[str],
) -> JsonObjectSchema:
    return JsonObjectSchema(title=title, properties=properties, required=required)


def _contract(
    *,
    goal: str,
    operation: str,
    input_schema: JsonObjectSchema,
    output_schema: JsonObjectSchema,
    preconditions: list[str],
    effects: list[str],
    failure_modes: list[str],
    side_effect: SideEffect = SideEffect.READ_ONLY,
    required_scopes: list[str] | None = None,
) -> AssetContract:
    return AssetContract(
        goal=goal,
        operation=operation,
        input_schema=input_schema,
        output_schema=output_schema,
        preconditions=preconditions,
        effects=effects,
        side_effect=side_effect,
        failure_modes=failure_modes,
        timeout_seconds=30,
        max_retries=1 if side_effect in {SideEffect.NONE, SideEffect.READ_ONLY} else 0,
        idempotency_required=side_effect is SideEffect.LOCAL_WRITE,
        compensation=None,
        required_scopes=required_scopes or [],
    )


def _header(
    *,
    name: str,
    summary: str,
    positive: list[str],
    anti: list[str],
    input_type: str,
    output_type: str,
    keywords: list[str],
) -> RouteHeader:
    return RouteHeader(
        name=name,
        summary=summary,
        positive_triggers=positive,
        anti_triggers=anti,
        input_type_summary=input_type,
        output_type_summary=output_type,
        keywords=keywords,
    )


def _evidence(
    scenario_suffix: str,
    *,
    steps: list[str],
    candidates: list[str] | None = None,
) -> SourceEvidence:
    scenario_id = f"{DOMAIN}_{scenario_suffix}"
    return SourceEvidence(
        trace_id=f"trace_syn_{scenario_id}",
        scenario_id=scenario_id,
        step_ids=steps,
        candidate_ids=candidates or [],
    )


def _asset(
    *,
    asset_id: str,
    kind: AssetKind,
    recall_policy: RecallPolicy,
    risk: RiskLevel,
    header: RouteHeader,
    contract: AssetContract,
    body: AssetBody,
    evidence: list[SourceEvidence],
) -> AssetDefinition:
    return AssetDefinition(
        asset_id=asset_id,
        version="1.0.0",
        kind=kind,
        owner=OWNER,
        domain=DOMAIN,
        recall_policy=recall_policy,
        risk_level=risk,
        release_status=ReleaseStatus.DRAFT,
        route_header=header,
        contract=contract,
        body=body,
        source_evidence=evidence,
        test_suite_ref=SUITE_REF,
    )


def _fsm_body(**data: Any) -> FsmShardBody:
    return FsmShardBody.model_validate(data)


def _adapter_body(**data: Any) -> AdapterBody:
    return AdapterBody.model_validate(data)


def _skeleton_body(**data: Any) -> WorkflowSkeletonBody:
    return WorkflowSkeletonBody.model_validate(data)


def _validator_body(**data: Any) -> ValidatorBody:
    return ValidatorBody.model_validate(data)


def build_financial_report_assets() -> list[AssetDefinition]:
    """Return reusable financial_report assets oriented to future Blueprint reuse."""
    string = {"type": "string"}
    number = {"type": "number"}
    boolean = {"type": "boolean"}
    array = {"type": "array"}
    object_value = {"type": "object"}

    assets = [
        _asset(
            asset_id="tool.financial_report.snapshot.metric_loader",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.LOW,
            header=_header(
                name="财务快照指标加载",
                summary="从本地合成财务快照读取报表指标、分部、预算或应收数据。",
                positive=["加载财务指标", "读取利润表快照", "读取应收账龄数据"],
                anti=["访问真实 ERP", "修改报表数据", "生成最终分析结论"],
                input_type="FinancialSnapshotQuery",
                output_type="FinancialSnapshot",
                keywords=["财务报表", "快照", "指标", "分部", "应收"],
            ),
            contract=_contract(
                goal="读取本地合成财务报表快照，输出后续资产可消费的稳定事实结构。",
                operation="financial_report.snapshot.metric_loader",
                input_schema=_schema(
                    "FinancialSnapshotQuery",
                    {"source_key": string, "statement_type": string},
                    ["source_key"],
                ),
                output_schema=_schema(
                    "FinancialSnapshot",
                    {
                        "source_key": string,
                        "snapshot_type": string,
                        "period": string,
                        "metrics": object_value,
                        "records": array,
                    },
                    ["source_key", "snapshot_type", "period"],
                ),
                preconditions=["source_key 来自合成 Trace 或测试 fixture"],
                effects=["只读取本地合成数据，不访问真实外部系统"],
                failure_modes=["SNAPSHOT_NOT_FOUND", "SOURCE_KEY_EMPTY"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.financial_report:"
                    "metric_snapshot_load"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "02_income_yoy",
                    steps=["step_01"],
                    candidates=["candidate_extractor_financial_v1"],
                ),
                _evidence(
                    "06_segment_performance",
                    steps=["step_01"],
                    candidates=["candidate_01_segment_extractor"],
                ),
                _evidence(
                    "08_receivable_aging",
                    steps=["step_01"],
                    candidates=["candidate_adapter_norm_inv"],
                ),
                _evidence("10_management_summary", steps=["step_01"]),
            ],
        ),
        _asset(
            asset_id="tool.financial_report.calc.formula_batch",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="财务公式批量计算",
                summary="执行勾稽差异、同比、财务比率和预算偏差等确定性公式计算。",
                positive=["计算同比", "计算财务比率", "计算预算偏差", "计算资产负债表差额"],
                anti=["撰写管理层评论", "审批报表调整", "访问真实账套"],
                input_type="FinancialFormulaInput",
                output_type="FinancialFormulaResult",
                keywords=["公式", "同比", "比率", "预算偏差", "勾稽"],
            ),
            contract=_contract(
                goal="把常见财务报表计算沉淀为可复用的受控公式批处理能力。",
                operation="financial_report.calc.formula_batch",
                input_schema=_schema(
                    "FinancialFormulaInput",
                    {"calculation_kind": string, "metrics": object_value},
                    ["calculation_kind", "metrics"],
                ),
                output_schema=_schema(
                    "FinancialFormulaResult",
                    {
                        "calculation_kind": string,
                        "results": object_value,
                        "audit_log": array,
                    },
                    ["calculation_kind", "results", "audit_log"],
                ),
                preconditions=["输入指标来自受控快照或已归一化视图"],
                effects=["只返回计算结果和审计日志，不写入报表"],
                failure_modes=["CALCULATION_KIND_UNSUPPORTED", "DIVISION_BY_ZERO"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.financial_report:"
                    "formula_batch_calculate"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "01_balance_sheet_reconcile",
                    steps=["step_03"],
                    candidates=["candidate_01_variance_detector"],
                ),
                _evidence("02_income_yoy", steps=["step_03"]),
                _evidence(
                    "04_financial_ratios",
                    steps=["step_02"],
                    candidates=["candidate_ratio_calculator_01"],
                ),
                _evidence("07_budget_variance", steps=["step_03"]),
            ],
        ),
        _asset(
            asset_id="tool.financial_report.consolidation.intercompany_eliminate",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="分部内部交易抵销",
                summary="对统一币种后的分部经营数据执行本地内部交易抵销计算。",
                positive=["抵销内部交易", "合并分部收入", "计算分部贡献"],
                anti=["生成真实会计分录", "写入合并报表系统"],
                input_type="SegmentConsolidationInput",
                output_type="SegmentConsolidationResult",
                keywords=["分部", "抵销", "合并", "内部交易", "收入"],
            ),
            contract=_contract(
                goal="对合成分部数据执行确定性内部交易抵销，供分部表现分析复用。",
                operation="financial_report.consolidation.intercompany_eliminate",
                input_schema=_schema(
                    "SegmentConsolidationInput",
                    {"segments": array, "reporting_currency": string, "fx_rates": object_value},
                    ["segments"],
                ),
                output_schema=_schema(
                    "SegmentConsolidationResult",
                    {
                        "segments": array,
                        "consolidated_revenue": number,
                        "elimination_entries": array,
                    },
                    ["segments", "consolidated_revenue", "elimination_entries"],
                ),
                preconditions=["分部数据已归一或附带合成汇率"],
                effects=["只生成本地抵销结果，不写入会计系统"],
                failure_modes=["SEGMENT_SCHEMA_INVALID", "NEGATIVE_CONSOLIDATION"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.financial_report:"
                    "intercompany_eliminate"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "06_segment_performance",
                    steps=["step_03"],
                    candidates=["candidate_03_elimination_tool"],
                ),
            ],
        ),
        _asset(
            asset_id="tool.financial_report.summary.evidence_text_compose",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="证据化财务摘要生成",
                summary="根据已验证指标生成带引用的短财务摘要草稿。",
                positive=["生成管理摘要", "生成同比摘要", "生成预算偏差说明"],
                anti=["替代管理层判断", "引用未经验证指标", "写入正式公告"],
                input_type="EvidenceSummaryInput",
                output_type="EvidenceSummaryDraft",
                keywords=["摘要", "证据", "管理层", "引用", "报告"],
            ),
            contract=_contract(
                goal="把已验证的关键财务指标转换为带证据引用的摘要草稿。",
                operation="financial_report.summary.evidence_text_compose",
                input_schema=_schema(
                    "EvidenceSummaryInput",
                    {"summary_kind": string, "key_metrics": array, "evidence_refs": array},
                    ["summary_kind", "key_metrics", "evidence_refs"],
                ),
                output_schema=_schema(
                    "EvidenceSummaryDraft",
                    {
                        "summary_text": string,
                        "citations": array,
                        "length_ok": boolean,
                    },
                    ["summary_text", "citations", "length_ok"],
                ),
                preconditions=["输入指标已经由上游 Validator 或固定规则校验"],
                effects=["只生成本地摘要草稿，不发布正式报告"],
                failure_modes=["CITATION_MISSING", "SUMMARY_KIND_UNSUPPORTED"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.financial_report:"
                    "evidence_text_compose"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "02_income_yoy",
                    steps=["step_04"],
                    candidates=["candidate_fsm_report_builder_v1"],
                ),
                _evidence(
                    "10_management_summary",
                    steps=["step_03"],
                    candidates=["candidate_tool_summary_gen_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="adapter.financial_report.normalization.report_view",
            kind=AssetKind.ADAPTER,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.LOW,
            header=_header(
                name="财务报表视图归一 Adapter",
                summary="把科目、币种、分部和应收发票字段确定性转换为标准分析视图。",
                positive=["科目映射", "币种归一", "发票客户归一", "报表字段标准化"],
                anti=["执行公式计算", "生成管理摘要", "做异常判断"],
                input_type="RawFinancialView",
                output_type="NormalizedFinancialView",
                keywords=["Adapter", "科目", "币种", "发票", "归一"],
            ),
            contract=_contract(
                goal="在原始财务视图和标准分析 Contract 之间做确定性字段转换。",
                operation="financial_report.normalization.report_view",
                input_schema=_schema(
                    "RawFinancialView",
                    {"view_kind": string, "raw_payload": object_value},
                    ["view_kind", "raw_payload"],
                ),
                output_schema=_schema(
                    "NormalizedFinancialView",
                    {
                        "view_kind": string,
                        "normalized_payload": object_value,
                        "applied_rules": array,
                    },
                    ["view_kind", "normalized_payload", "applied_rules"],
                ),
                preconditions=["输入数据来自本地合成 Trace 或测试 fixture"],
                effects=["只做字段和币种转换，不产生业务结论"],
                side_effect=SideEffect.NONE,
                failure_modes=["VIEW_KIND_UNSUPPORTED", "MAPPING_RULE_MISSING"],
            ),
            body=_adapter_body(
                kind=AssetKind.ADAPTER,
                from_schema="RawFinancialView",
                to_schema="NormalizedFinancialView",
                mappings=[
                    {
                        "source": "raw_payload.asset_total",
                        "target": "normalized_payload.total_assets",
                        "transform": "COPY",
                    },
                    {
                        "source": "raw_payload.liability_total",
                        "target": "normalized_payload.total_liabilities",
                        "transform": "COPY",
                    },
                    {
                        "source": "raw_payload.equity_total",
                        "target": "normalized_payload.total_equity",
                        "transform": "COPY",
                    },
                    {
                        "source": "raw_payload.currency",
                        "target": "normalized_payload.currency",
                        "transform": "NORMALIZE_ENUM",
                    },
                    {
                        "source": "raw_payload.account_code",
                        "target": "normalized_payload.metric_code",
                        "transform": "NORMALIZE_ENUM",
                    },
                    {
                        "source": "raw_payload.customer_alias",
                        "target": "normalized_payload.customer_id",
                        "transform": "NORMALIZE_ENUM",
                    },
                ],
            ),
            evidence=[
                _evidence(
                    "01_balance_sheet_reconcile",
                    steps=["step_02"],
                    candidates=["candidate_03_discrepancy_reporter"],
                ),
                _evidence(
                    "06_segment_performance",
                    steps=["step_02"],
                    candidates=["candidate_02_currency_adapter"],
                ),
                _evidence(
                    "07_budget_variance", steps=["step_01"], candidates=["candidate_adapter_map_01"]
                ),
                _evidence(
                    "08_receivable_aging",
                    steps=["step_01"],
                    candidates=["candidate_adapter_norm_inv"],
                ),
            ],
        ),
        _asset(
            asset_id="fsm.financial_report.reconciliation.balance_sheet_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="资产负债表勾稽路由",
                summary="对资产负债表执行字段归一、恒等式勾稽、差异定位和人工复核路由。",
                positive=["资产负债表不平", "会计恒等式校验", "勾稽差异分析"],
                anti=["自动改账", "生成真实调整分录"],
                input_type="BalanceSheetReconciliationRequest",
                output_type="BalanceSheetReconciliationResult",
                keywords=["资产负债表", "勾稽", "差异", "平衡", "复核"],
            ),
            contract=_contract(
                goal="完成资产负债表勾稽检查并输出结构化差异报告。",
                operation="financial_report.reconciliation.balance_sheet_route",
                input_schema=_schema(
                    "BalanceSheetReconciliationRequest",
                    {"statement_snapshot": object_value, "tolerance": number},
                    ["statement_snapshot"],
                ),
                output_schema=_schema(
                    "BalanceSheetReconciliationResult",
                    {
                        "reconciliation_status": string,
                        "variance_amount": number,
                        "is_balanced": boolean,
                        "discrepancies": array,
                        "human_review_required": boolean,
                    },
                    ["reconciliation_status", "variance_amount", "is_balanced"],
                ),
                preconditions=["报表快照已归一为标准资产、负债、权益字段"],
                effects=["只输出差异和复核建议，不修改报表"],
                side_effect=SideEffect.NONE,
                failure_modes=["STATEMENT_SCHEMA_INVALID", "RECONCILIATION_INCOMPLETE"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成资产负债表恒等式勾稽与差异复核路由。",
                states=[
                    {"state_id": "normalize", "invariant": "报表字段已映射到标准视图。"},
                    {"state_id": "calculate", "invariant": "资产与负债权益差额可重复计算。"},
                    {"state_id": "classify", "invariant": "差异状态来自容忍度规则。"},
                    {"state_id": "validated", "invariant": "结构化结果等待独立 Validator。"},
                ],
                transitions=[
                    {
                        "from_state": "normalize",
                        "event": "VIEW_READY",
                        "to_state": "calculate",
                        "guard": "标准字段完整",
                    },
                    {
                        "from_state": "calculate",
                        "event": "VARIANCE_COMPUTED",
                        "to_state": "classify",
                        "guard": "差额为有效数字",
                    },
                    {
                        "from_state": "classify",
                        "event": "ROUTE_BUILT",
                        "to_state": "validated",
                        "guard": "失败时保留人工复核",
                    },
                ],
                start_state="normalize",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence(
                    "01_balance_sheet_reconcile",
                    steps=["step_02", "step_03", "step_04"],
                    candidates=["candidate_02_reconciliation_validator"],
                ),
            ],
        ),
        _asset(
            asset_id="fsm.financial_report.performance.analysis_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="经营表现分析路由",
                summary="覆盖利润同比、分部贡献和预算偏差的财务表现分析状态图。",
                positive=["利润同比分析", "分部表现排名", "预算偏差分级", "重大波动筛选"],
                anti=["现金流异常专项", "应收账龄专项", "自动调预算"],
                input_type="PerformanceAnalysisRequest",
                output_type="PerformanceAnalysisResult",
                keywords=["同比", "分部", "预算", "表现", "重大性"],
            ),
            contract=_contract(
                goal="对常见经营表现类财务指标生成可验证分析结果。",
                operation="financial_report.performance.analysis_route",
                input_schema=_schema(
                    "PerformanceAnalysisRequest",
                    {
                        "analysis_kind": string,
                        "metric_snapshot": object_value,
                        "thresholds": object_value,
                    },
                    ["analysis_kind", "metric_snapshot"],
                ),
                output_schema=_schema(
                    "PerformanceAnalysisResult",
                    {
                        "analysis_kind": string,
                        "analysis_items": array,
                        "risk_level": string,
                        "human_review_required": boolean,
                    },
                    ["analysis_kind", "analysis_items", "risk_level"],
                ),
                preconditions=["输入指标已加载或归一化，阈值来自固定本地政策"],
                effects=["输出分析项和风险等级，不写入报表"],
                side_effect=SideEffect.NONE,
                failure_modes=["ANALYSIS_KIND_UNSUPPORTED", "NO_ANALYSIS_ITEMS"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成同比、分部和预算类经营表现分析。",
                states=[
                    {"state_id": "metrics_ready", "invariant": "指标包可用于公式或排序。"},
                    {"state_id": "calculate", "invariant": "同比、贡献或偏差计算完成。"},
                    {"state_id": "rank", "invariant": "重大项目已排序或标记。"},
                    {"state_id": "validated", "invariant": "分析结果等待 Validator。"},
                ],
                transitions=[
                    {
                        "from_state": "metrics_ready",
                        "event": "METRICS_COMPLETE",
                        "to_state": "calculate",
                        "guard": "分析所需字段存在",
                    },
                    {
                        "from_state": "calculate",
                        "event": "ANALYSIS_COMPUTED",
                        "to_state": "rank",
                        "guard": "结果可排序或分级",
                    },
                    {
                        "from_state": "rank",
                        "event": "ANALYSIS_READY",
                        "to_state": "validated",
                        "guard": "风险等级来自固定枚举",
                    },
                ],
                start_state="metrics_ready",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence(
                    "02_income_yoy",
                    steps=["step_02", "step_03", "step_04"],
                    candidates=["candidate_fsm_report_builder_v1"],
                ),
                _evidence("06_segment_performance", steps=["step_02", "step_03", "step_04"]),
                _evidence(
                    "07_budget_variance",
                    steps=["step_01", "step_02", "step_03"],
                    candidates=["candidate_validator_thresh_02"],
                ),
            ],
        ),
        _asset(
            asset_id="fsm.financial_report.cashflow.anomaly_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="现金流异常识别路由",
                summary="比较经营现金流、净利润和趋势阈值，输出异常评分与风险标签。",
                positive=["现金流异常", "经营现金流偏离净利润", "异常评分"],
                anti=["生成筹资建议", "修改现金流分类"],
                input_type="CashflowAnomalyRequest",
                output_type="CashflowAnomalyResult",
                keywords=["现金流", "异常", "净利润", "评分", "风险"],
            ),
            contract=_contract(
                goal="完成现金流偏离风险的确定性评分和人工复核路由。",
                operation="financial_report.cashflow.anomaly_route",
                input_schema=_schema(
                    "CashflowAnomalyRequest",
                    {"cashflow_snapshot": object_value, "thresholds": object_value},
                    ["cashflow_snapshot"],
                ),
                output_schema=_schema(
                    "CashflowAnomalyResult",
                    {
                        "anomaly_score": number,
                        "risk_level": string,
                        "anomaly_flags": array,
                        "human_review_required": boolean,
                    },
                    ["anomaly_score", "risk_level", "anomaly_flags"],
                ),
                preconditions=["现金流和净利润指标来自合成快照"],
                effects=["只生成异常评分和证据，不修改分类"],
                side_effect=SideEffect.NONE,
                failure_modes=["CASHFLOW_INPUT_INVALID", "SCORE_OUT_OF_RANGE"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成经营现金流与净利润偏离的异常识别。",
                states=[
                    {"state_id": "cashflow_ready", "invariant": "现金流事实已分类。"},
                    {"state_id": "compare", "invariant": "经营现金流和净利润可比较。"},
                    {"state_id": "score", "invariant": "异常分数位于 0 到 100。"},
                    {"state_id": "validated", "invariant": "风险输出等待 Validator。"},
                ],
                transitions=[
                    {
                        "from_state": "cashflow_ready",
                        "event": "CASHFLOW_COMPLETE",
                        "to_state": "compare",
                        "guard": "OCF 和净利润存在",
                    },
                    {
                        "from_state": "compare",
                        "event": "DIVERGENCE_COMPUTED",
                        "to_state": "score",
                        "guard": "偏离比例可计算",
                    },
                    {
                        "from_state": "score",
                        "event": "SCORE_READY",
                        "to_state": "validated",
                        "guard": "高风险进入人工复核",
                    },
                ],
                start_state="cashflow_ready",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence(
                    "03_cashflow_anomaly",
                    steps=["step_01", "step_02", "step_03"],
                    candidates=["candidate_01_cashflow_tool", "candidate_02_anomaly_fsm"],
                ),
            ],
        ),
        _asset(
            asset_id="fsm.financial_report.receivable.aging_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="应收账款账龄分析路由",
                summary="归一发票、应用回款、计算账龄桶并检查客户集中度风险。",
                positive=["应收账龄分析", "逾期桶计算", "集中度风险", "回款抵扣"],
                anti=["核销真实应收", "修改客户信用额度"],
                input_type="ReceivableAgingRequest",
                output_type="ReceivableAgingResult",
                keywords=["应收", "账龄", "集中度", "逾期", "发票"],
            ),
            contract=_contract(
                goal="完成应收账款账龄桶和客户集中度风险的确定性分析。",
                operation="financial_report.receivable.aging_route",
                input_schema=_schema(
                    "ReceivableAgingRequest",
                    {"receivable_snapshot": object_value, "thresholds": object_value},
                    ["receivable_snapshot"],
                ),
                output_schema=_schema(
                    "ReceivableAgingResult",
                    {
                        "aging_buckets": object_value,
                        "total_receivable": number,
                        "concentration_ratio": number,
                        "risk_level": string,
                    },
                    ["aging_buckets", "total_receivable", "risk_level"],
                ),
                preconditions=["发票和回款数据来自合成快照或已归一化视图"],
                effects=["只输出账龄和风险评估，不修改应收余额"],
                side_effect=SideEffect.NONE,
                failure_modes=["AGING_INPUT_INVALID", "BUCKET_TOTAL_MISMATCH"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成应收账款账龄桶与集中度风险计算。",
                states=[
                    {"state_id": "normalize", "invariant": "客户和发票名称已归一。"},
                    {"state_id": "apply_payments", "invariant": "回款和贷项通知已本地抵扣。"},
                    {"state_id": "bucket", "invariant": "账龄桶总额可回溯。"},
                    {"state_id": "validated", "invariant": "风险输出等待 Validator。"},
                ],
                transitions=[
                    {
                        "from_state": "normalize",
                        "event": "INVOICES_READY",
                        "to_state": "apply_payments",
                        "guard": "发票列表非空",
                    },
                    {
                        "from_state": "apply_payments",
                        "event": "BALANCE_UPDATED",
                        "to_state": "bucket",
                        "guard": "余额均非负",
                    },
                    {
                        "from_state": "bucket",
                        "event": "AGING_READY",
                        "to_state": "validated",
                        "guard": "集中度阈值已应用",
                    },
                ],
                start_state="normalize",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence(
                    "08_receivable_aging",
                    steps=["step_01", "step_02", "step_03", "step_04"],
                    candidates=["candidate_validator_concentration"],
                ),
            ],
        ),
        _asset(
            asset_id="fsm.financial_report.management.summary_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="管理层财务摘要路由",
                summary="筛选重大财务指标并生成带证据引用的管理层摘要草稿。",
                positive=["管理层摘要", "重大性筛选", "证据引用摘要"],
                anti=["发布正式报告", "使用未经验证指标"],
                input_type="ManagementSummaryRequest",
                output_type="ManagementSummaryResult",
                keywords=["管理层", "摘要", "重大性", "引用", "草稿"],
            ),
            contract=_contract(
                goal="完成重大性筛选和证据化管理摘要草稿生成。",
                operation="financial_report.management.summary_route",
                input_schema=_schema(
                    "ManagementSummaryRequest",
                    {"metric_bundle": object_value, "materiality_threshold": number},
                    ["metric_bundle"],
                ),
                output_schema=_schema(
                    "ManagementSummaryResult",
                    {
                        "summary_text": string,
                        "material_items": array,
                        "citations": array,
                        "human_review_required": boolean,
                    },
                    ["summary_text", "material_items", "citations"],
                ),
                preconditions=["输入指标已经过上游计算或验证"],
                effects=["只生成管理摘要草稿，不发布正式报告"],
                side_effect=SideEffect.NONE,
                failure_modes=["MATERIALITY_EMPTY", "CITATION_MISSING"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成财务重大性筛选和管理层摘要草稿。",
                states=[
                    {"state_id": "metrics_ready", "invariant": "指标包带有证据引用。"},
                    {"state_id": "filter", "invariant": "重大性阈值来自固定策略。"},
                    {"state_id": "compose", "invariant": "摘要仅引用已筛选指标。"},
                    {"state_id": "validated", "invariant": "摘要等待 Validator。"},
                ],
                transitions=[
                    {
                        "from_state": "metrics_ready",
                        "event": "METRICS_VALID",
                        "to_state": "filter",
                        "guard": "指标包含变动幅度",
                    },
                    {
                        "from_state": "filter",
                        "event": "MATERIAL_ITEMS_SELECTED",
                        "to_state": "compose",
                        "guard": "至少一个重大项目或明确无重大项目",
                    },
                    {
                        "from_state": "compose",
                        "event": "SUMMARY_DRAFTED",
                        "to_state": "validated",
                        "guard": "摘要带有引用",
                    },
                ],
                start_state="metrics_ready",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence(
                    "10_management_summary",
                    steps=["step_01", "step_02", "step_03"],
                    candidates=["candidate_fs_materiality_v1", "candidate_tool_summary_gen_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.financial_report.reconciliation.balance_sheet",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="资产负债表勾稽 Validator",
                summary="验证勾稽结果是否包含状态、差额和失败时的人工复核边界。",
                positive=["验证勾稽结果", "检查差额字段", "检查人工复核"],
                anti=["计算差额", "修改报表"],
                input_type="BalanceSheetReconciliationResult",
                output_type="ValidationResult",
                keywords=["Validator", "勾稽", "资产负债表", "差异"],
            ),
            contract=_contract(
                goal="独立验证资产负债表勾稽结果是否结构完整且可治理。",
                operation="financial_report.validator.balance_sheet_reconciliation",
                input_schema=_schema(
                    "BalanceSheetReconciliationResult", {"payload": object_value}, ["payload"]
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自勾稽 FSM 或测试 fixture"],
                effects=["只返回验证结果和失败码"],
                side_effect=SideEffect.NONE,
                failure_modes=["RECONCILIATION_STATUS_MISSING", "VARIANCE_MISSING"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="BalanceSheetReconciliationResult",
                rules=[
                    {
                        "field": "payload.reconciliation_status",
                        "operator": "EXISTS",
                        "failure_code": "RECONCILIATION_STATUS_MISSING",
                    },
                    {
                        "field": "payload.variance_amount",
                        "operator": "EXISTS",
                        "failure_code": "VARIANCE_MISSING",
                    },
                    {
                        "field": "payload.human_review_required",
                        "operator": "EXISTS",
                        "failure_code": "REVIEW_ROUTE_MISSING",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "01_balance_sheet_reconcile",
                    steps=["step_03"],
                    candidates=["candidate_02_reconciliation_validator"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.financial_report.performance.analysis",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="经营表现分析 Validator",
                summary="验证同比、分部或预算分析结果是否含分析项、风险等级和复核路由。",
                positive=["验证同比分析", "验证预算偏差", "验证分部排名"],
                anti=["生成摘要文本", "计算原始公式"],
                input_type="PerformanceAnalysisResult",
                output_type="ValidationResult",
                keywords=["Validator", "同比", "分部", "预算", "风险"],
            ),
            contract=_contract(
                goal="独立验证经营表现分析输出是否完整且风险等级受控。",
                operation="financial_report.validator.performance_analysis",
                input_schema=_schema(
                    "PerformanceAnalysisResult", {"payload": object_value}, ["payload"]
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自经营表现 FSM 或测试 fixture"],
                effects=["只返回验证结果和失败码"],
                side_effect=SideEffect.NONE,
                failure_modes=["ANALYSIS_ITEMS_MISSING", "RISK_LEVEL_INVALID"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="PerformanceAnalysisResult",
                rules=[
                    {
                        "field": "payload.analysis_kind",
                        "operator": "EXISTS",
                        "failure_code": "ANALYSIS_KIND_MISSING",
                    },
                    {
                        "field": "payload.analysis_items",
                        "operator": "EXISTS",
                        "failure_code": "ANALYSIS_ITEMS_MISSING",
                    },
                    {
                        "field": "payload.risk_level",
                        "operator": "IN",
                        "expected": ["LOW", "MEDIUM", "HIGH"],
                        "failure_code": "RISK_LEVEL_INVALID",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "02_income_yoy",
                    steps=["step_04"],
                    candidates=["candidate_fsm_report_builder_v1"],
                ),
                _evidence(
                    "07_budget_variance",
                    steps=["step_03"],
                    candidates=["candidate_validator_thresh_02"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.financial_report.cashflow.anomaly",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="现金流异常 Validator",
                summary="验证异常评分、风险标签和人工复核路由是否一致。",
                positive=["验证现金流异常", "检查异常分数", "检查人工复核"],
                anti=["修改现金流分类", "生成融资建议"],
                input_type="CashflowAnomalyResult",
                output_type="ValidationResult",
                keywords=["Validator", "现金流", "异常", "评分"],
            ),
            contract=_contract(
                goal="独立验证现金流异常结果是否在评分范围内且风险路由一致。",
                operation="financial_report.validator.cashflow_anomaly",
                input_schema=_schema(
                    "CashflowAnomalyResult", {"payload": object_value}, ["payload"]
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自现金流异常 FSM 或测试 fixture"],
                effects=["只返回验证结果和失败码"],
                side_effect=SideEffect.NONE,
                failure_modes=["SCORE_OUT_OF_RANGE", "ANOMALY_FLAGS_MISSING"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="CashflowAnomalyResult",
                rules=[
                    {
                        "field": "payload.anomaly_score",
                        "operator": "GTE",
                        "expected": 0,
                        "failure_code": "SCORE_OUT_OF_RANGE",
                    },
                    {
                        "field": "payload.anomaly_flags",
                        "operator": "EXISTS",
                        "failure_code": "ANOMALY_FLAGS_MISSING",
                    },
                    {
                        "field": "payload.human_review_required",
                        "operator": "EXISTS",
                        "failure_code": "REVIEW_ROUTE_MISSING",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "03_cashflow_anomaly",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_02_anomaly_fsm"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.financial_report.receivable.aging",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="应收账龄 Validator",
                summary="验证账龄桶、总额、集中度和风险标签是否一致。",
                positive=["验证账龄报告", "验证集中度风险", "检查逾期桶"],
                anti=["核销应收", "修改客户信用额度"],
                input_type="ReceivableAgingResult",
                output_type="ValidationResult",
                keywords=["Validator", "应收", "账龄", "集中度"],
            ),
            contract=_contract(
                goal="独立验证应收账龄分析输出是否完整且风险标签受控。",
                operation="financial_report.validator.receivable_aging",
                input_schema=_schema(
                    "ReceivableAgingResult", {"payload": object_value}, ["payload"]
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自应收账龄 FSM 或测试 fixture"],
                effects=["只返回验证结果和失败码"],
                side_effect=SideEffect.NONE,
                failure_modes=["AGING_BUCKETS_MISSING", "CONCENTRATION_INVALID"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="ReceivableAgingResult",
                rules=[
                    {
                        "field": "payload.aging_buckets",
                        "operator": "EXISTS",
                        "failure_code": "AGING_BUCKETS_MISSING",
                    },
                    {
                        "field": "payload.total_receivable",
                        "operator": "GTE",
                        "expected": 0,
                        "failure_code": "TOTAL_INVALID",
                    },
                    {
                        "field": "payload.risk_level",
                        "operator": "IN",
                        "expected": ["LOW", "MEDIUM", "HIGH"],
                        "failure_code": "RISK_LEVEL_INVALID",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "08_receivable_aging",
                    steps=["step_03", "step_04"],
                    candidates=["candidate_validator_concentration"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.financial_report.management.summary",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="管理摘要 Validator",
                summary="验证管理层摘要草稿是否包含文本、引用和重大项目列表。",
                positive=["验证管理层摘要", "检查证据引用", "检查重大性项目"],
                anti=["生成摘要", "发布报告"],
                input_type="ManagementSummaryResult",
                output_type="ValidationResult",
                keywords=["Validator", "管理摘要", "引用", "重大性"],
            ),
            contract=_contract(
                goal="独立验证管理层财务摘要草稿是否可追溯且结构完整。",
                operation="financial_report.validator.management_summary",
                input_schema=_schema(
                    "ManagementSummaryResult", {"payload": object_value}, ["payload"]
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自管理摘要 FSM 或测试 fixture"],
                effects=["只返回验证结果和失败码"],
                side_effect=SideEffect.NONE,
                failure_modes=["SUMMARY_EMPTY", "CITATION_MISSING"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="ManagementSummaryResult",
                rules=[
                    {
                        "field": "payload.summary_text",
                        "operator": "EXISTS",
                        "failure_code": "SUMMARY_EMPTY",
                    },
                    {
                        "field": "payload.citations",
                        "operator": "EXISTS",
                        "failure_code": "CITATION_MISSING",
                    },
                    {
                        "field": "payload.material_items",
                        "operator": "EXISTS",
                        "failure_code": "MATERIAL_ITEMS_MISSING",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "10_management_summary",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_fs_materiality_v1", "candidate_tool_summary_gen_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="skeleton.financial_report.analysis_daef",
            kind=AssetKind.WORKFLOW_SKELETON,
            recall_policy=RecallPolicy.PLANNING_PRIOR,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="财报分析 DAEF",
                summary="用于财报分析任务的信息读取、视图归一、计算决策、报告草稿和验证阶段先验。",
                positive=["规划财报分析执行流", "财报 DAEF 骨架", "报表验证先验"],
                anti=["直接执行具体公式", "绑定具体资产版本"],
                input_type="FinancialReportObjective",
                output_type="FinancialReportDaefPrior",
                keywords=["DAEF", "财报", "分析", "规划先验", "验证"],
            ),
            contract=_contract(
                goal="提供财报分析任务可复用的 DAEF 宏观规划先验，不作为执行图。",
                operation="financial_report.daef.analysis",
                input_schema=_schema(
                    "FinancialReportObjective",
                    {"objective": string, "risk_level": string, "constraints": array},
                    ["objective"],
                ),
                output_schema=_schema(
                    "FinancialReportDaefPrior",
                    {"stages": array, "directly_executable": boolean},
                    ["stages", "directly_executable"],
                ),
                preconditions=["只用于规划先验读取"],
                effects=["返回宏观阶段，不绑定具体资产版本"],
                side_effect=SideEffect.NONE,
                failure_modes=["DAEF_STAGE_INVALID"],
            ),
            body=_skeleton_body(
                kind=AssetKind.WORKFLOW_SKELETON,
                stages=[
                    {
                        "stage": "INFORMATION",
                        "expected_state": "财务快照、期间口径和风险约束已读取。",
                        "required_invariants": ["只使用合成或已脱敏数据"],
                    },
                    {
                        "stage": "TRANSFORM",
                        "expected_state": "原始报表视图已转换为标准分析 Contract。",
                        "required_invariants": ["Extractor 候选只能沉淀为 Tool 或 FSM 内部逻辑"],
                    },
                    {
                        "stage": "DECISION",
                        "expected_state": "公式、重大性和风险阈值由固定策略决定。",
                        "required_invariants": ["高风险输出保留人工复核"],
                    },
                    {
                        "stage": "ACTION",
                        "expected_state": "只生成分析结果、差异报告或摘要草稿。",
                        "required_invariants": ["不修改真实报表、预算或应收系统"],
                    },
                    {
                        "stage": "VALIDATION",
                        "expected_state": "完成状态必须由独立 Validator 验证。",
                        "required_invariants": ["模型不能自报 validated=true 绕过检查"],
                    },
                ],
            ),
            evidence=[
                _evidence("01_balance_sheet_reconcile", steps=["step_01", "step_04"]),
                _evidence("03_cashflow_anomaly", steps=["step_01", "step_03"]),
                _evidence("08_receivable_aging", steps=["step_01", "step_04"]),
                _evidence("10_management_summary", steps=["step_01", "step_03"]),
            ],
        ),
    ]
    return assets


def build_financial_report_edges(
    assets: list[AssetDefinition],
) -> list[CapabilityEdge]:
    """Build explicit one-hop dependencies for reusable financial_report routes."""
    refs = {asset.asset_id: asset.asset_ref for asset in assets}
    return [
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.reconciliation.balance_sheet_route"],
            to_ref=refs["adapter.financial_report.normalization.report_view"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="勾稽路由需要标准化资产、负债和权益字段。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.reconciliation.balance_sheet_route"],
            to_ref=refs["tool.financial_report.calc.formula_batch"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="勾稽差额由通用公式批处理 Tool 计算。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.reconciliation.balance_sheet_route"],
            to_ref=refs["validator.financial_report.reconciliation.balance_sheet"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="勾稽结果必须验证状态、差额和复核边界。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.performance.analysis_route"],
            to_ref=refs["tool.financial_report.snapshot.metric_loader"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="经营表现分析需要加载本地财务指标快照。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.performance.analysis_route"],
            to_ref=refs["tool.financial_report.calc.formula_batch"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="同比、比率和预算偏差依赖通用公式计算。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.performance.analysis_route"],
            to_ref=refs["tool.financial_report.consolidation.intercompany_eliminate"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="分部表现分析需要内部交易抵销后的合并数据。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.performance.analysis_route"],
            to_ref=refs["validator.financial_report.performance.analysis"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="经营表现分析结果必须验证分析项和风险等级。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.cashflow.anomaly_route"],
            to_ref=refs["tool.financial_report.snapshot.metric_loader"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="现金流异常识别需要现金流指标快照。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.cashflow.anomaly_route"],
            to_ref=refs["validator.financial_report.cashflow.anomaly"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="现金流异常输出必须验证评分范围和复核路由。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.receivable.aging_route"],
            to_ref=refs["adapter.financial_report.normalization.report_view"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="应收账龄分析需要发票客户和余额归一。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.receivable.aging_route"],
            to_ref=refs["tool.financial_report.snapshot.metric_loader"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="应收账龄分析需要应收发票和回款快照。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.receivable.aging_route"],
            to_ref=refs["validator.financial_report.receivable.aging"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="应收账龄输出必须验证账龄桶和风险等级。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.management.summary_route"],
            to_ref=refs["tool.financial_report.summary.evidence_text_compose"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="管理摘要路由依赖证据化摘要草稿生成 Tool。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.financial_report.management.summary_route"],
            to_ref=refs["validator.financial_report.management.summary"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="管理摘要必须验证文本、引用和重大项目。",
        ),
    ]
