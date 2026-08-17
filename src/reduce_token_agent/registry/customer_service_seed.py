"""Curated Kind assets extracted from customer_service synthetic traces."""

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

DOMAIN: Literal["customer_service"] = "customer_service"
OWNER: Literal["customer_service_poc"] = "customer_service_poc"
SUITE_REF: Literal["suite.customer_service.kind_contract@1.0.0"] = (
    "suite.customer_service.kind_contract@1.0.0"
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


def build_customer_service_assets() -> list[AssetDefinition]:
    """Return reusable customer_service assets rather than one asset per Trace."""
    string = {"type": "string"}
    number = {"type": "number"}
    boolean = {"type": "boolean"}
    array = {"type": "array"}
    object_value = {"type": "object"}

    assets = [
        _asset(
            asset_id="tool.customer_service.dialogue.intent_normalize",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.LOW,
            header=_header(
                name="客服意图与风险归一",
                summary="把合成客服对话归一为意图、路由族、实体和初始风险提示。",
                positive=["识别客服对话意图", "归一客户请求", "提取客服任务实体"],
                anti=["生成最终客服回复", "修改客户资料", "创建真实工单"],
                input_type="CustomerDialogueInput",
                output_type="CustomerIntentProfile",
                keywords=["客服", "意图", "归一", "风险", "实体"],
            ),
            contract=_contract(
                goal="将客户自然语言请求转换为后续客服执行流可消费的稳定意图结构。",
                operation="customer_service.dialogue.intent_normalize",
                input_schema=_schema(
                    "CustomerDialogueInput",
                    {"source_text": string, "scenario_hint": string},
                    ["source_text"],
                ),
                output_schema=_schema(
                    "CustomerIntentProfile",
                    {
                        "intent_category": string,
                        "route_family": string,
                        "risk_level": string,
                        "entities": object_value,
                        "human_review_hint": boolean,
                    },
                    ["intent_category", "route_family", "risk_level", "entities"],
                ),
                preconditions=["输入文本来自合成客服 Trace 或测试样例"],
                effects=["只返回结构化意图，不写入会话或客户资料"],
                failure_modes=["INTENT_UNSUPPORTED", "SOURCE_TEXT_EMPTY"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.customer_service:intent_normalize"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence("01_repayment_inquiry", steps=["step_01"]),
                _evidence("03_rate_explanation", steps=["step_01"]),
                _evidence("04_prepayment_request", steps=["step_01"]),
                _evidence("05_fraud_report", steps=["step_01"]),
            ],
        ),
        _asset(
            asset_id="tool.customer_service.case.snapshot_lookup",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.LOW,
            header=_header(
                name="合成客服事实快照查询",
                summary="按稳定键读取账单、合同、支付、客户资料或证据包的合成快照。",
                positive=["查询账单快照", "读取合同利率片段", "读取证据包", "读取客户资料"],
                anti=["访问真实客户系统", "更新账单或征信记录"],
                input_type="CaseSnapshotLookup",
                output_type="CaseSnapshot",
                keywords=["快照", "账单", "合同", "证据", "客户资料"],
            ),
            contract=_contract(
                goal="从本地合成目录读取客服任务所需的事实快照，供后续确定性执行使用。",
                operation="customer_service.case.snapshot_lookup",
                input_schema=_schema(
                    "CaseSnapshotLookup",
                    {"lookup_key": string, "lookup_type": string},
                    ["lookup_key"],
                ),
                output_schema=_schema(
                    "CaseSnapshot",
                    {"lookup_key": string, "snapshot_type": string, "facts": object_value},
                    ["lookup_key", "snapshot_type", "facts"],
                ),
                preconditions=["lookup_key 来自合成 Trace 或测试 fixture"],
                effects=["只读取本地合成事实，不访问真实外部系统"],
                failure_modes=["SNAPSHOT_NOT_FOUND", "LOOKUP_KEY_EMPTY"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.customer_service:"
                    "case_snapshot_lookup"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "01_repayment_inquiry",
                    steps=["step_03"],
                    candidates=["candidate_01_bill_adapter"],
                ),
                _evidence(
                    "03_rate_explanation",
                    steps=["step_02"],
                    candidates=["candidate_rate_adapter_v1"],
                ),
                _evidence("07_profile_correction", steps=["step_02"]),
                _evidence(
                    "08_credit_dispute",
                    steps=["step_02"],
                    candidates=["candidate_evidence_validator_v2"],
                ),
            ],
        ),
        _asset(
            asset_id="tool.customer_service.claim.context_extract",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="客服主张事实抽取",
                summary="从合成客服文本中抽取支付主张、错误码、地址变更、欺诈或征信异议事实。",
                positive=["抽取客户主张", "提取支付错误码", "提取地址变更字段", "提取征信异议对象"],
                anti=["作为 EXTRACTOR kind 入库", "生成最终处置意见"],
                input_type="ClaimExtractionInput",
                output_type="CustomerServiceFacts",
                keywords=["主张", "错误码", "地址", "异议", "字段抽取"],
            ),
            contract=_contract(
                goal="把可复用的客服事实抽取沉淀为受控单函数，避免保留独立 EXTRACTOR kind。",
                operation="customer_service.claim.context_extract",
                input_schema=_schema(
                    "ClaimExtractionInput",
                    {"source_text": string, "extract_kind": string},
                    ["source_text", "extract_kind"],
                ),
                output_schema=_schema(
                    "CustomerServiceFacts",
                    {
                        "extract_kind": string,
                        "facts": object_value,
                        "confidence_score": number,
                    },
                    ["extract_kind", "facts", "confidence_score"],
                ),
                preconditions=["source_text 已脱敏或来自合成数据"],
                effects=["返回结构化事实，不修改源对话或工单"],
                failure_modes=["EXTRACT_KIND_UNSUPPORTED", "REQUIRED_FACT_MISSING"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.customer_service:"
                    "claim_context_extract"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "02_overdue_complaint",
                    steps=["step_01"],
                    candidates=["candidate_01_claim_parser"],
                ),
                _evidence(
                    "06_payment_failure",
                    steps=["step_01"],
                    candidates=["candidate_error_extractor_v1"],
                ),
                _evidence(
                    "07_profile_correction",
                    steps=["step_01"],
                    candidates=["candidate_01_address_extractor"],
                ),
                _evidence(
                    "08_credit_dispute",
                    steps=["step_01"],
                    candidates=["candidate_dispute_parser_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="tool.customer_service.risk.signal_score",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="客服风险信号评分",
                summary="对欺诈、资料变更、提前还款和征信异议等高敏客服场景计算本地风险路由。",
                positive=["计算客服风险评分", "判断是否人工升级", "识别安全团队路由"],
                anti=["直接冻结账户", "直接修改客户状态", "替代人工审批"],
                input_type="RiskSignalInput",
                output_type="RiskScoreDecision",
                keywords=["风险", "欺诈", "人工升级", "安全", "高敏"],
            ),
            contract=_contract(
                goal="根据合成风险信号给出确定性风险等级和人工路由建议。",
                operation="customer_service.risk.signal_score",
                input_schema=_schema(
                    "RiskSignalInput",
                    {
                        "case_kind": string,
                        "signals": array,
                        "amount": number,
                        "evidence_complete": boolean,
                    },
                    ["case_kind", "signals"],
                ),
                output_schema=_schema(
                    "RiskScoreDecision",
                    {
                        "risk_score": number,
                        "risk_band": string,
                        "recommended_route": string,
                        "human_review_required": boolean,
                        "blocking_signals": array,
                    },
                    ["risk_score", "risk_band", "recommended_route", "human_review_required"],
                ),
                preconditions=["风险信号来自合成上下文或已脱敏对话"],
                effects=["只输出风险分层，不执行账户写操作"],
                failure_modes=["CASE_KIND_UNSUPPORTED", "RISK_SIGNAL_INVALID"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.assets_runtime.customer_service:risk_signal_score"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "05_fraud_report",
                    steps=["step_01"],
                    candidates=["candidate_01_risk_scoring_tool"],
                ),
                _evidence(
                    "07_profile_correction",
                    steps=["step_02"],
                    candidates=["candidate_02_risk_policy_gate"],
                ),
                _evidence(
                    "08_credit_dispute", steps=["step_03"], candidates=["candidate_case_fsm_v1"]
                ),
            ],
        ),
        _asset(
            asset_id="adapter.customer_service.response.customer_projection",
            kind=AssetKind.ADAPTER,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.LOW,
            header=_header(
                name="客服回复事实投影 Adapter",
                summary="把内部账单或利率事实确定性投影为可验证的客户展示字段。",
                positive=["转换账单快照为回复字段", "转换利率条款为披露字段"],
                anti=["生成自由发挥文本", "决定是否审批"],
                input_type="CustomerSupportInternalFacts",
                output_type="CustomerFacingReplyFacts",
                keywords=["Adapter", "回复字段", "账单", "利率", "投影"],
            ),
            contract=_contract(
                goal="在内部客服事实和客户回复 Contract 之间做确定性字段映射。",
                operation="customer_service.response.customer_projection",
                input_schema=_schema(
                    "CustomerSupportInternalFacts",
                    {"projection_kind": string, "facts": object_value},
                    ["projection_kind", "facts"],
                ),
                output_schema=_schema(
                    "CustomerFacingReplyFacts",
                    {
                        "response_kind": string,
                        "response_draft": string,
                        "disclosure_items": array,
                        "sensitive_fields_removed": boolean,
                    },
                    ["response_kind", "response_draft", "disclosure_items"],
                ),
                preconditions=["输入事实已来自受控快照或受控抽取结果"],
                effects=["只做字段投影和模板填充，不生成新业务结论"],
                side_effect=SideEffect.NONE,
                failure_modes=["PROJECTION_KIND_UNSUPPORTED", "REQUIRED_FACT_MISSING"],
            ),
            body=_adapter_body(
                kind=AssetKind.ADAPTER,
                from_schema="CustomerSupportInternalFacts",
                to_schema="CustomerFacingReplyFacts",
                mappings=[
                    {
                        "source": "facts.next_due_amount",
                        "target": "response_draft.amount_due",
                        "transform": "COPY",
                    },
                    {
                        "source": "facts.due_date",
                        "target": "response_draft.due_date",
                        "transform": "COPY",
                    },
                    {
                        "source": "facts.base_rate_type",
                        "target": "response_draft.base_rate_type",
                        "transform": "COPY",
                    },
                    {
                        "source": "facts.repricing_rule",
                        "target": "response_draft.repricing_rule",
                        "transform": "COPY",
                    },
                ],
            ),
            evidence=[
                _evidence(
                    "01_repayment_inquiry",
                    steps=["step_03"],
                    candidates=["candidate_01_bill_adapter"],
                ),
                _evidence(
                    "03_rate_explanation",
                    steps=["step_02"],
                    candidates=["candidate_rate_adapter_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="fsm.customer_service.billing.answer_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="账务与利率咨询回复路由",
                summary="覆盖还款金额日期查询与利率构成解释的客服答复小状态图。",
                positive=["查询下期还款金额", "解释贷款利率", "说明重定价规则"],
                anti=["处理欺诈上报", "创建资料变更工单"],
                input_type="BillingAnswerRequest",
                output_type="BillingAnswerResult",
                keywords=["还款", "利率", "账单", "LPR", "客服回复"],
            ),
            contract=_contract(
                goal="把账务或利率咨询路由到可验证客户答复，不处理高风险写操作。",
                operation="customer_service.billing.answer_route",
                input_schema=_schema(
                    "BillingAnswerRequest",
                    {
                        "intent_profile": object_value,
                        "support_snapshot": object_value,
                        "projection_kind": string,
                    },
                    ["intent_profile", "support_snapshot", "projection_kind"],
                ),
                output_schema=_schema(
                    "BillingAnswerResult",
                    {
                        "answer_type": string,
                        "response_draft": string,
                        "disclosure_items": array,
                        "human_review_required": boolean,
                        "sensitive_fields_removed": boolean,
                    },
                    ["answer_type", "response_draft", "disclosure_items"],
                ),
                preconditions=["客户意图已归一，事实快照来自本地合成数据"],
                effects=["生成待验证回复草案，不发送消息"],
                side_effect=SideEffect.NONE,
                failure_modes=["BILLING_ROUTE_UNSUPPORTED", "DISCLOSURE_INCOMPLETE"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成账务咨询或利率解释的确定性客服答复路由。",
                states=[
                    {"state_id": "intake", "invariant": "客户问题已归一为受控意图。"},
                    {"state_id": "load_facts", "invariant": "账单或合同事实来自合成快照。"},
                    {"state_id": "project_reply", "invariant": "内部事实已投影为客户展示字段。"},
                    {"state_id": "validated", "invariant": "回复草案已等待独立 Validator 检查。"},
                ],
                transitions=[
                    {
                        "from_state": "intake",
                        "event": "INTENT_SUPPORTED",
                        "to_state": "load_facts",
                        "guard": "intent_category 属于还款咨询或利率解释",
                    },
                    {
                        "from_state": "load_facts",
                        "event": "FACTS_AVAILABLE",
                        "to_state": "project_reply",
                        "guard": "support_snapshot 含必需账单或利率字段",
                    },
                    {
                        "from_state": "project_reply",
                        "event": "REPLY_PROJECTED",
                        "to_state": "validated",
                        "guard": "输出包含披露要素且未暴露敏感字段",
                    },
                ],
                start_state="intake",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence("01_repayment_inquiry", steps=["step_01", "step_03", "step_04"]),
                _evidence("03_rate_explanation", steps=["step_01", "step_03", "step_04"]),
            ],
        ),
        _asset(
            asset_id="fsm.customer_service.case.investigation_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="支付异常与投诉调查路由",
                summary="覆盖逾期费用投诉和还款失败排障的只读调查状态图。",
                positive=["核查逾期费投诉", "定位扣款失败原因", "生成只读排障步骤"],
                anti=["调整费用", "重新发起扣款", "修改账单"],
                input_type="CaseInvestigationRequest",
                output_type="CaseInvestigationResult",
                keywords=["逾期", "投诉", "支付失败", "错误码", "排障"],
            ),
            contract=_contract(
                goal="对支付相关客服异常执行只读调查并给出解释或人工升级路由。",
                operation="customer_service.case.investigation_route",
                input_schema=_schema(
                    "CaseInvestigationRequest",
                    {
                        "case_type": string,
                        "claim_context": object_value,
                        "case_snapshot": object_value,
                    },
                    ["case_type", "claim_context", "case_snapshot"],
                ),
                output_schema=_schema(
                    "CaseInvestigationResult",
                    {
                        "resolution_route": string,
                        "cause_code": string,
                        "customer_message_draft": string,
                        "next_steps": array,
                        "side_effects_allowed": boolean,
                    },
                    ["resolution_route", "cause_code", "customer_message_draft"],
                ),
                preconditions=["支付主张或错误码已结构化，账单/日志快照已加载"],
                effects=["生成只读解释或人工升级建议，不修改账单"],
                side_effect=SideEffect.NONE,
                failure_modes=["CASE_TYPE_UNSUPPORTED", "PAYMENT_FACTS_INCOMPLETE"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成支付异常类客服问题的只读调查与路由。",
                states=[
                    {"state_id": "facts_ready", "invariant": "客户主张和系统快照已结构化。"},
                    {"state_id": "compare", "invariant": "声明时间、到账时间或错误码可比较。"},
                    {"state_id": "route", "invariant": "路由只能是解释、排障或人工复核。"},
                    {"state_id": "validated", "invariant": "结果等待独立 Validator 检查无写操作。"},
                ],
                transitions=[
                    {
                        "from_state": "facts_ready",
                        "event": "PAYMENT_FACTS_COMPLETE",
                        "to_state": "compare",
                        "guard": "包含支付金额、时间或错误码",
                    },
                    {
                        "from_state": "compare",
                        "event": "CAUSE_CLASSIFIED",
                        "to_state": "route",
                        "guard": "原因码来自固定枚举",
                    },
                    {
                        "from_state": "route",
                        "event": "ROUTE_BUILT",
                        "to_state": "validated",
                        "guard": "未产生账单修改或扣款动作",
                    },
                ],
                start_state="facts_ready",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence("02_overdue_complaint", steps=["step_01", "step_02", "step_03"]),
                _evidence("06_payment_failure", steps=["step_01", "step_02", "step_03"]),
            ],
        ),
        _asset(
            asset_id="fsm.customer_service.request.intake_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="高敏请求受理与工单草稿路由",
                summary="覆盖提前还款申请和客户资料更正的字段缺口、风险门禁与人工工单草稿。",
                positive=["受理提前还款申请", "受理地址修改", "识别缺失字段", "生成待人工处理工单"],
                anti=["直接修改客户资料", "直接提交真实还款申请"],
                input_type="RequestIntakeRequest",
                output_type="RequestIntakeResult",
                keywords=["提前还款", "资料更正", "缺失字段", "人工审核", "工单"],
            ),
            contract=_contract(
                goal="对高敏客服请求生成最小可审核草稿和缺失信息清单。",
                operation="customer_service.request.intake_route",
                input_schema=_schema(
                    "RequestIntakeRequest",
                    {
                        "request_type": string,
                        "extracted_facts": object_value,
                        "risk_decision": object_value,
                    },
                    ["request_type", "extracted_facts"],
                ),
                output_schema=_schema(
                    "RequestIntakeResult",
                    {
                        "route": string,
                        "missing_fields": array,
                        "draft_id": string,
                        "human_review_required": boolean,
                        "side_effects_allowed": boolean,
                    },
                    ["route", "missing_fields", "draft_id", "human_review_required"],
                ),
                preconditions=["请求事实已结构化，禁止真实写入客户系统"],
                effects=["生成本地草稿和人工处理提示，不提交真实申请"],
                side_effect=SideEffect.NONE,
                failure_modes=["REQUEST_TYPE_UNSUPPORTED", "REQUIRED_FIELDS_UNKNOWN"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成提前还款或资料更正类客服请求的可审核受理。",
                states=[
                    {"state_id": "extract", "invariant": "请求字段来自受控抽取。"},
                    {"state_id": "gap_check", "invariant": "缺失字段来自固定业务 Schema。"},
                    {"state_id": "risk_gate", "invariant": "高敏请求不得自动写入。"},
                    {"state_id": "draft_ticket", "invariant": "只生成本地草稿和人工下一步。"},
                    {"state_id": "validated", "invariant": "受理结果已等待 Validator 检查。"},
                ],
                transitions=[
                    {
                        "from_state": "extract",
                        "event": "FACTS_EXTRACTED",
                        "to_state": "gap_check",
                        "guard": "事实中包含 request_type",
                    },
                    {
                        "from_state": "gap_check",
                        "event": "GAPS_IDENTIFIED",
                        "to_state": "risk_gate",
                        "guard": "缺失字段只来自固定 Schema",
                    },
                    {
                        "from_state": "risk_gate",
                        "event": "RISK_ROUTED",
                        "to_state": "draft_ticket",
                        "guard": "高敏请求保留人工复核",
                    },
                    {
                        "from_state": "draft_ticket",
                        "event": "DRAFT_CREATED",
                        "to_state": "validated",
                        "guard": "未产生真实客户资料或贷款状态写入",
                    },
                ],
                start_state="extract",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence(
                    "04_prepayment_request",
                    steps=["step_01", "step_02", "step_03"],
                    candidates=["candidate_01_gap_analyzer"],
                ),
                _evidence(
                    "07_profile_correction",
                    steps=["step_01", "step_02", "step_03"],
                    candidates=["candidate_02_risk_policy_gate"],
                ),
            ],
        ),
        _asset(
            asset_id="fsm.customer_service.escalation.triage_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="欺诈与征信异议升级路由",
                summary="覆盖疑似欺诈和征信异议的脱敏、风险分层、工单与合规时限路由。",
                positive=["处理欺诈上报", "受理征信异议", "生成安全团队路由", "计算合规时限"],
                anti=["直接冻结账户", "直接修改征信记录", "索要密码验证码"],
                input_type="EscalationTriageRequest",
                output_type="EscalationTriageResult",
                keywords=["欺诈", "征信异议", "脱敏", "升级", "时限"],
            ),
            contract=_contract(
                goal="对高风险客服事件完成脱敏和人工升级路由，不执行真实账户或征信写入。",
                operation="customer_service.escalation.triage_route",
                input_schema=_schema(
                    "EscalationTriageRequest",
                    {
                        "case_type": string,
                        "case_facts": object_value,
                        "risk_decision": object_value,
                        "evidence_bundle": object_value,
                    },
                    ["case_type", "case_facts", "risk_decision"],
                ),
                output_schema=_schema(
                    "EscalationTriageResult",
                    {
                        "ticket_type": string,
                        "handoff_team": string,
                        "deadline_hours": number,
                        "masked_case_summary": string,
                        "human_review_required": boolean,
                        "sensitive_fields_removed": boolean,
                    },
                    ["ticket_type", "handoff_team", "deadline_hours", "masked_case_summary"],
                ),
                preconditions=["高风险事实已脱敏或来自合成输入"],
                effects=["只生成升级工单草稿和时限计划"],
                side_effect=SideEffect.NONE,
                failure_modes=["ESCALATION_TYPE_UNSUPPORTED", "SENSITIVE_DATA_UNMASKED"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成欺诈和征信异议类高风险事件的安全升级。",
                states=[
                    {"state_id": "signal_ready", "invariant": "风险信号和事实已结构化。"},
                    {"state_id": "mask", "invariant": "客户和交易敏感字段已脱敏。"},
                    {"state_id": "deadline", "invariant": "合规处理时限来自固定策略。"},
                    {"state_id": "handoff", "invariant": "只路由人工团队，不执行真实写入。"},
                    {"state_id": "validated", "invariant": "升级结果等待 Validator 检查。"},
                ],
                transitions=[
                    {
                        "from_state": "signal_ready",
                        "event": "HIGH_RISK_CONFIRMED",
                        "to_state": "mask",
                        "guard": "风险等级为 HIGH 或 case_type 强制人工",
                    },
                    {
                        "from_state": "mask",
                        "event": "MASKED",
                        "to_state": "deadline",
                        "guard": "输出不包含完整 ID、卡号或验证码",
                    },
                    {
                        "from_state": "deadline",
                        "event": "DEADLINE_ASSIGNED",
                        "to_state": "handoff",
                        "guard": "时限不超过固定政策上限",
                    },
                    {
                        "from_state": "handoff",
                        "event": "HANDOFF_READY",
                        "to_state": "validated",
                        "guard": "路由为人工团队且无真实写操作",
                    },
                ],
                start_state="signal_ready",
                terminal_states=["validated"],
            ),
            evidence=[
                _evidence(
                    "05_fraud_report",
                    steps=["step_01", "step_02", "step_03", "step_04"],
                    candidates=["candidate_02_fraud_fsm_state_machine"],
                ),
                _evidence(
                    "08_credit_dispute",
                    steps=["step_01", "step_02", "step_03", "step_04"],
                    candidates=["candidate_case_fsm_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.customer_service.billing.response",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="账务回复合规 Validator",
                summary="验证还款金额日期或利率解释回复是否包含必要披露且不泄露敏感信息。",
                positive=["验证账务客服回复", "检查利率披露", "检查敏感信息脱敏"],
                anti=["生成客服回复正文", "查询账单"],
                input_type="BillingAnswerResult",
                output_type="ValidationResult",
                keywords=["Validator", "账务回复", "利率披露", "脱敏"],
            ),
            contract=_contract(
                goal="独立验证账务咨询回复的完成状态和合规披露。",
                operation="customer_service.validator.billing_response",
                input_schema=_schema(
                    "BillingAnswerResult",
                    {"payload": object_value},
                    ["payload"],
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["待验证 payload 来自账务回复 FSM 或等价测试 fixture"],
                effects=["只返回验证结果和失败码"],
                side_effect=SideEffect.NONE,
                failure_modes=["DISCLOSURE_INCOMPLETE", "SENSITIVE_DATA_DETECTED"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="BillingAnswerResult",
                rules=[
                    {
                        "field": "payload.response_draft",
                        "operator": "EXISTS",
                        "failure_code": "RESPONSE_EMPTY",
                    },
                    {
                        "field": "payload.disclosure_items",
                        "operator": "EXISTS",
                        "failure_code": "DISCLOSURE_INCOMPLETE",
                    },
                    {
                        "field": "payload.sensitive_fields_removed",
                        "operator": "EQ",
                        "expected": True,
                        "failure_code": "SENSITIVE_DATA_DETECTED",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "01_repayment_inquiry",
                    steps=["step_04"],
                    candidates=["candidate_02_response_validator"],
                ),
                _evidence(
                    "03_rate_explanation",
                    steps=["step_03"],
                    candidates=["candidate_disclosure_validator_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.customer_service.case.investigation",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="支付调查结果 Validator",
                summary="验证投诉或支付失败调查结果是否只读、原因明确且包含下一步建议。",
                positive=["验证逾期费解释", "验证支付失败排障", "检查无写操作"],
                anti=["重新发起扣款", "修改费用"],
                input_type="CaseInvestigationResult",
                output_type="ValidationResult",
                keywords=["Validator", "逾期", "支付失败", "只读"],
            ),
            contract=_contract(
                goal="独立验证支付异常调查结果是否可安全交给客户或人工处理。",
                operation="customer_service.validator.case_investigation",
                input_schema=_schema(
                    "CaseInvestigationResult",
                    {"payload": object_value},
                    ["payload"],
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自支付调查 FSM 或测试 fixture"],
                effects=["只返回验证结果，不改变账务状态"],
                side_effect=SideEffect.NONE,
                failure_modes=["CAUSE_CODE_MISSING", "UNAUTHORIZED_WRITE"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="CaseInvestigationResult",
                rules=[
                    {
                        "field": "payload.resolution_route",
                        "operator": "EXISTS",
                        "failure_code": "ROUTE_MISSING",
                    },
                    {
                        "field": "payload.cause_code",
                        "operator": "EXISTS",
                        "failure_code": "CAUSE_CODE_MISSING",
                    },
                    {
                        "field": "payload.side_effects_allowed",
                        "operator": "EQ",
                        "expected": False,
                        "failure_code": "UNAUTHORIZED_WRITE",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "02_overdue_complaint",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_02_delay_validator"],
                ),
                _evidence(
                    "06_payment_failure",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_payment_fsm_v2"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.customer_service.request.intake",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="高敏请求受理 Validator",
                summary="验证提前还款和资料更正请求是否保留人工复核、缺失字段清晰且无真实写入。",
                positive=["验证提前还款申请草稿", "验证地址更正工单", "检查缺失字段"],
                anti=["直接提交申请", "直接更新地址"],
                input_type="RequestIntakeResult",
                output_type="ValidationResult",
                keywords=["Validator", "提前还款", "资料更正", "人工复核"],
            ),
            contract=_contract(
                goal="独立验证高敏客服请求是否只生成草稿和人工处理边界。",
                operation="customer_service.validator.request_intake",
                input_schema=_schema(
                    "RequestIntakeResult",
                    {"payload": object_value},
                    ["payload"],
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自高敏请求受理 FSM 或测试 fixture"],
                effects=["只返回验证结果，不提交业务申请"],
                side_effect=SideEffect.NONE,
                failure_modes=["HUMAN_REVIEW_REQUIRED", "UNAUTHORIZED_WRITE"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="RequestIntakeResult",
                rules=[
                    {
                        "field": "payload.draft_id",
                        "operator": "EXISTS",
                        "failure_code": "DRAFT_ID_MISSING",
                    },
                    {
                        "field": "payload.human_review_required",
                        "operator": "EQ",
                        "expected": True,
                        "failure_code": "HUMAN_REVIEW_REQUIRED",
                    },
                    {
                        "field": "payload.side_effects_allowed",
                        "operator": "EQ",
                        "expected": False,
                        "failure_code": "UNAUTHORIZED_WRITE",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "04_prepayment_request",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_02_approval_policy_validator"],
                ),
                _evidence(
                    "07_profile_correction",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_02_risk_policy_gate"],
                ),
            ],
        ),
        _asset(
            asset_id="validator.customer_service.escalation.triage",
            kind=AssetKind.VALIDATOR,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.HIGH,
            header=_header(
                name="欺诈征信升级 Validator",
                summary="验证欺诈和征信异议升级是否脱敏、人工移交且时限合规。",
                positive=["验证欺诈升级", "验证征信异议时限", "检查脱敏"],
                anti=["冻结账户", "修改征信数据库"],
                input_type="EscalationTriageResult",
                output_type="ValidationResult",
                keywords=["Validator", "欺诈", "征信", "脱敏", "时限"],
            ),
            contract=_contract(
                goal="独立验证高风险客服升级结果是否满足安全和合规边界。",
                operation="customer_service.validator.escalation_triage",
                input_schema=_schema(
                    "EscalationTriageResult",
                    {"payload": object_value},
                    ["payload"],
                ),
                output_schema=_schema(
                    "ValidationResult",
                    {"valid": boolean, "failure_codes": array},
                    ["valid", "failure_codes"],
                ),
                preconditions=["payload 来自升级路由 FSM 或测试 fixture"],
                effects=["只返回验证结果，不触发真实外部通知"],
                side_effect=SideEffect.NONE,
                failure_modes=["MASKING_REQUIRED", "DEADLINE_INVALID"],
            ),
            body=_validator_body(
                kind=AssetKind.VALIDATOR,
                validates_schema="EscalationTriageResult",
                rules=[
                    {
                        "field": "payload.human_review_required",
                        "operator": "EQ",
                        "expected": True,
                        "failure_code": "HUMAN_HANDOFF_REQUIRED",
                    },
                    {
                        "field": "payload.sensitive_fields_removed",
                        "operator": "EQ",
                        "expected": True,
                        "failure_code": "MASKING_REQUIRED",
                    },
                    {
                        "field": "payload.deadline_hours",
                        "operator": "LTE",
                        "expected": 24,
                        "failure_code": "DEADLINE_INVALID",
                    },
                ],
                executor="DECLARATIVE_RULESET",
            ),
            evidence=[
                _evidence(
                    "05_fraud_report",
                    steps=["step_03", "step_04"],
                    candidates=["candidate_02_fraud_fsm_state_machine"],
                ),
                _evidence(
                    "08_credit_dispute",
                    steps=["step_02", "step_04"],
                    candidates=["candidate_evidence_validator_v2", "candidate_case_fsm_v1"],
                ),
            ],
        ),
        _asset(
            asset_id="skeleton.customer_service.intake_resolution_daef",
            kind=AssetKind.WORKFLOW_SKELETON,
            recall_policy=RecallPolicy.PLANNING_PRIOR,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="客服受理到验证 DAEF",
                summary="用于客服任务的领域无关宏观阶段：信息受理、事实转换、路由决策、行动草案和验证。",
                positive=["规划客服执行流", "客服任务宏观骨架", "DAEF 阶段先验"],
                anti=["直接执行具体客服能力", "绑定具体资产版本"],
                input_type="CustomerServiceObjective",
                output_type="CustomerServiceDaefPrior",
                keywords=["DAEF", "客服", "规划先验", "受理", "验证"],
            ),
            contract=_contract(
                goal="提供客服任务可复用的 DAEF 宏观规划先验，不作为执行图。",
                operation="customer_service.daef.intake_resolution",
                input_schema=_schema(
                    "CustomerServiceObjective",
                    {"objective": string, "risk_level": string, "constraints": array},
                    ["objective"],
                ),
                output_schema=_schema(
                    "CustomerServiceDaefPrior",
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
                        "expected_state": "客户问题、风险等级和上下文资料已受理。",
                        "required_invariants": ["只使用合成或已脱敏输入"],
                    },
                    {
                        "stage": "TRANSFORM",
                        "expected_state": "非结构化对话已转换为标准意图和事实 Contract。",
                        "required_invariants": ["Extractor 候选只能沉淀为 Tool 或 FSM 内部逻辑"],
                    },
                    {
                        "stage": "DECISION",
                        "expected_state": "路由决策由固定政策、风险阈值和缺口检查决定。",
                        "required_invariants": ["高敏请求保留人工复核"],
                    },
                    {
                        "stage": "ACTION",
                        "expected_state": "只生成回复、草稿、排障建议或人工工单草稿。",
                        "required_invariants": ["不执行真实账户、账单或征信写入"],
                    },
                    {
                        "stage": "VALIDATION",
                        "expected_state": "完成状态必须由独立 Validator 验证。",
                        "required_invariants": ["模型不能自报 validated=true 绕过检查"],
                    },
                ],
            ),
            evidence=[
                _evidence("01_repayment_inquiry", steps=["step_01", "step_04"]),
                _evidence("04_prepayment_request", steps=["step_01", "step_03"]),
                _evidence("05_fraud_report", steps=["step_01", "step_04"]),
                _evidence("08_credit_dispute", steps=["step_01", "step_04"]),
            ],
        ),
    ]
    return assets


def build_customer_service_edges(
    assets: list[AssetDefinition],
) -> list[CapabilityEdge]:
    """Build explicit one-hop dependencies for reusable customer_service routes."""
    refs = {asset.asset_id: asset.asset_ref for asset in assets}
    return [
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.billing.answer_route"],
            to_ref=refs["tool.customer_service.dialogue.intent_normalize"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="账务回复路由依赖客户意图归一结果。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.billing.answer_route"],
            to_ref=refs["tool.customer_service.case.snapshot_lookup"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="账务回复路由需要账单或合同事实快照。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.billing.answer_route"],
            to_ref=refs["adapter.customer_service.response.customer_projection"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="账务或利率事实需投影为客户展示字段。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.billing.answer_route"],
            to_ref=refs["validator.customer_service.billing.response"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="账务回复完成状态必须经独立合规 Validator。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.case.investigation_route"],
            to_ref=refs["tool.customer_service.claim.context_extract"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="支付异常调查需要客户主张或错误码结构化事实。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.case.investigation_route"],
            to_ref=refs["tool.customer_service.case.snapshot_lookup"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="支付异常调查需要账单或支付日志快照。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.case.investigation_route"],
            to_ref=refs["validator.customer_service.case.investigation"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="支付调查结果必须验证只读边界和原因码。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.request.intake_route"],
            to_ref=refs["tool.customer_service.claim.context_extract"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="高敏请求受理需要从对话中抽取字段。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.request.intake_route"],
            to_ref=refs["tool.customer_service.risk.signal_score"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="高敏请求受理需要固定风险门禁。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.request.intake_route"],
            to_ref=refs["validator.customer_service.request.intake"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="请求受理结果必须验证草稿边界和人工复核。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.escalation.triage_route"],
            to_ref=refs["tool.customer_service.claim.context_extract"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="风险升级路由需要欺诈或异议事实抽取。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.escalation.triage_route"],
            to_ref=refs["tool.customer_service.risk.signal_score"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="风险升级路由依赖风险评分和人工路由建议。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.escalation.triage_route"],
            to_ref=refs["tool.customer_service.case.snapshot_lookup"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="征信异议或欺诈上报需要本地证据/告警快照。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.customer_service.escalation.triage_route"],
            to_ref=refs["validator.customer_service.escalation.triage"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="风险升级必须验证脱敏、人工移交和合规时限。",
        ),
    ]
