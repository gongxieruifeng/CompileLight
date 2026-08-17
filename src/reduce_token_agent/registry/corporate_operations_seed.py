"""Curated Kind assets extracted from corporate_operations synthetic traces."""

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

SUITE_REF: Literal[
    "suite.corporate_operations.kind_contract@1.0.0"
] = "suite.corporate_operations.kind_contract@1.0.0"


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
    side_effect: SideEffect = SideEffect.NONE,
    failure_modes: list[str],
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
    scenario_id = f"corporate_operations_{scenario_suffix}"
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
        owner="corporate_operations_poc",
        domain="corporate_operations",
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


def build_corporate_operations_assets() -> list[AssetDefinition]:
    """Return a deliberately small set of Blueprint-oriented assets."""
    string = {"type": "string"}
    number = {"type": "number"}
    boolean = {"type": "boolean"}
    array = {"type": "array"}
    object_value = {"type": "object"}

    assets = [
        _asset(
            asset_id="tool.corporate_ops.expense.duplicate_receipt_check",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.LOW,
            header=_header(
                name="重复票据检测",
                summary="对结构化报销票据执行凭证号及时间地点组合键的确定性重复检查。",
                positive=["检查报销票据是否重复", "识别重复凭证号"],
                anti=["提取发票图片字段", "批准或支付报销款"],
                input_type="ReceiptCollection",
                output_type="DuplicateReceiptAssessment",
                keywords=["报销", "票据", "重复", "凭证号"],
            ),
            contract=_contract(
                goal="对已结构化票据集合执行单一、可重复的重复性检查。",
                operation="corporate_ops.expense.duplicate_receipt_check",
                input_schema=_schema(
                    "ReceiptCollection",
                    {"receipts": array, "match_keys": array},
                    ["receipts", "match_keys"],
                ),
                output_schema=_schema(
                    "DuplicateReceiptAssessment",
                    {"duplicate_groups": array, "has_duplicates": boolean},
                    ["duplicate_groups", "has_duplicates"],
                ),
                preconditions=["票据已完成结构化且每条记录具有稳定标识"],
                effects=["只产生重复分组结果，不修改报销单"],
                side_effect=SideEffect.READ_ONLY,
                failure_modes=["RECEIPT_SCHEMA_INVALID", "DUPLICATE_KEY_MISSING"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.tools.corporate_ops:"
                    "duplicate_receipt_check"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "01_expense_reimbursement",
                    steps=["step_02"],
                    candidates=["candidate_dup_checker_v1"],
                )
            ],
        ),
        _asset(
            asset_id="tool.corporate_ops.procurement.vendor_status_lookup",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.LOW,
            header=_header(
                name="供应商状态查询",
                summary="按供应商标识读取合成供应商的准入与尽调完成状态，不执行审批写入。",
                positive=["查询供应商是否完成尽调", "采购前检查供应商状态"],
                anti=["创建供应商", "直接批准采购申请"],
                input_type="VendorStatusQuery",
                output_type="VendorStatusSnapshot",
                keywords=["采购", "供应商", "尽调", "准入"],
            ),
            contract=_contract(
                goal="读取供应商当前准入和尽调状态，作为采购路由的事实输入。",
                operation="corporate_ops.procurement.vendor_status_lookup",
                input_schema=_schema(
                    "VendorStatusQuery",
                    {"vendor_id": string},
                    ["vendor_id"],
                ),
                output_schema=_schema(
                    "VendorStatusSnapshot",
                    {
                        "vendor_id": string,
                        "status": string,
                        "due_diligence_complete": boolean,
                    },
                    ["vendor_id", "status", "due_diligence_complete"],
                ),
                preconditions=["供应商标识非空且属于合成数据集"],
                effects=["返回只读状态快照"],
                side_effect=SideEffect.READ_ONLY,
                failure_modes=["VENDOR_NOT_FOUND", "VENDOR_STATUS_UNAVAILABLE"],
                required_scopes=["vendor:read"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.tools.corporate_ops:"
                    "vendor_status_lookup"
                ),
                invocation="FUNCTION",
            ),
            evidence=[
                _evidence(
                    "02_procurement_approval",
                    steps=["step_02"],
                    candidates=["candidate_vendor_checker"],
                )
            ],
        ),
        _asset(
            asset_id="tool.corporate_ops.leave.business_calendar_lookup",
            kind=AssetKind.PRIMITIVE_TOOL,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.LOW,
            header=_header(
                name="工作日历查询",
                summary="按日期区间和地区查询合成节假日与应扣工作日，为请假核算提供只读事实。",
                positive=["查询请假区间的工作日", "跨月请假包含法定节假日"],
                anti=["扣减员工假期余额", "批准请假"],
                input_type="CalendarRangeQuery",
                output_type="BusinessCalendarSnapshot",
                keywords=["请假", "工作日", "节假日", "跨月"],
            ),
            contract=_contract(
                goal="查询指定日期区间内的工作日和法定节假日事实。",
                operation="corporate_ops.leave.business_calendar_lookup",
                input_schema=_schema(
                    "CalendarRangeQuery",
                    {"start_date": string, "end_date": string, "region": string},
                    ["start_date", "end_date", "region"],
                ),
                output_schema=_schema(
                    "BusinessCalendarSnapshot",
                    {"working_days": array, "holidays": array, "deductible_days": number},
                    ["working_days", "holidays", "deductible_days"],
                ),
                preconditions=["开始日期不晚于结束日期"],
                effects=["返回只读日历快照"],
                side_effect=SideEffect.READ_ONLY,
                failure_modes=["DATE_RANGE_INVALID", "CALENDAR_REGION_UNSUPPORTED"],
                required_scopes=["calendar:read"],
            ),
            body=PrimitiveToolBody(
                kind=AssetKind.PRIMITIVE_TOOL,
                handler_ref=(
                    "python://reduce_token_agent.tools.corporate_ops:"
                    "business_calendar_lookup"
                ),
                invocation="FUNCTION",
            ),
            evidence=[_evidence("04_leave_workflow", steps=["step_02"])],
        ),
        _asset(
            asset_id="fsm.corporate_ops.expense.pre_audit",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="费用报销预审",
                summary="完成重复票据检查、住宿标准校验和人工复核路由这一可独立验证的预审子目标。",
                positive=["预审差旅报销", "检查重复票据和住宿超标"],
                anti=["执行报销付款", "只提取发票文字"],
                input_type="ExpenseClaimFacts",
                output_type="ExpensePreAuditDecision",
                keywords=["费用", "报销", "预审", "住宿标准", "重复票据"],
            ),
            contract=_contract(
                goal="形成可验证的费用预审结论与后续处理路由，不执行付款。",
                operation="corporate_ops.expense.pre_audit",
                input_schema=_schema(
                    "ExpenseClaimFacts",
                    {"receipts": array, "lodging_items": array, "policy_limits": object_value},
                    ["receipts", "lodging_items", "policy_limits"],
                ),
                output_schema=_schema(
                    "ExpensePreAuditDecision",
                    {
                        "duplicate_groups": array,
                        "policy_violations": array,
                        "route": string,
                        "human_review_required": boolean,
                    },
                    [
                        "duplicate_groups",
                        "policy_violations",
                        "route",
                        "human_review_required",
                    ],
                ),
                preconditions=["费用事实和适用政策版本已固定"],
                effects=["形成预审结论和路由建议，不改变财务状态"],
                failure_modes=["DUPLICATE_CHECK_FAILED", "POLICY_VERSION_MISSING"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成费用报销预审并输出可验证的人工或正常处理路由。",
                states=[
                    {"state_id": "received", "invariant": "费用事实和政策版本已经固定"},
                    {"state_id": "duplicates_checked", "invariant": "重复票据结果已经形成"},
                    {"state_id": "policy_checked", "invariant": "住宿标准已经逐项校验"},
                    {"state_id": "routed", "invariant": "输出只包含路由建议而非付款动作"},
                ],
                transitions=[
                    {
                        "from_state": "received",
                        "event": "CHECK_DUPLICATES",
                        "to_state": "duplicates_checked",
                        "guard": "票据列表非空",
                    },
                    {
                        "from_state": "duplicates_checked",
                        "event": "CHECK_POLICY",
                        "to_state": "policy_checked",
                        "guard": "政策版本可用",
                    },
                    {
                        "from_state": "policy_checked",
                        "event": "ROUTE_REVIEW",
                        "to_state": "routed",
                        "guard": "检查结果完整",
                    },
                ],
                start_state="received",
                terminal_states=["routed"],
            ),
            evidence=[
                _evidence(
                    "01_expense_reimbursement",
                    steps=["step_02", "step_03", "step_04"],
                )
            ],
        ),
        _asset(
            asset_id="fsm.corporate_ops.procurement.approval_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="采购审批路由",
                summary="依据金额阈值、附件完整性和供应商状态形成采购审批路径或人工阻断。",
                positive=["生成采购审批路径", "检查金额和供应商状态"],
                anti=["创建最终采购订单", "执行供应商准入"],
                input_type="ProcurementRequestFacts + VendorStatusSnapshot",
                output_type="ProcurementApprovalRoute",
                keywords=["采购", "审批", "金额阈值", "附件", "供应商"],
            ),
            contract=_contract(
                goal="形成采购申请的确定性审批路径并暴露缺失依赖。",
                operation="corporate_ops.procurement.approval_route",
                input_schema=_schema(
                    "ProcurementRoutingInput",
                    {
                        "amount": number,
                        "category": string,
                        "attachments_complete": boolean,
                        "vendor_status": object_value,
                    },
                    ["amount", "category", "attachments_complete", "vendor_status"],
                ),
                output_schema=_schema(
                    "ProcurementApprovalRoute",
                    {
                        "route_levels": array,
                        "blocked": boolean,
                        "block_reasons": array,
                        "human_review_required": boolean,
                    },
                    ["route_levels", "blocked", "block_reasons", "human_review_required"],
                ),
                preconditions=["金额、品类、附件状态和供应商状态均有明确来源"],
                effects=["只形成审批路径，不创建采购订单"],
                failure_modes=["THRESHOLD_POLICY_MISSING", "VENDOR_STATUS_UNAVAILABLE"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成采购申请依赖检查和审批层级路由。",
                states=[
                    {"state_id": "received", "invariant": "采购申请字段已经结构化"},
                    {"state_id": "dependencies_checked", "invariant": "附件与供应商状态已经检查"},
                    {"state_id": "threshold_routed", "invariant": "金额阈值映射为审批层级"},
                    {"state_id": "route_ready", "invariant": "阻断原因和审批路径不可同时缺失"},
                ],
                transitions=[
                    {
                        "from_state": "received",
                        "event": "CHECK_DEPENDENCIES",
                        "to_state": "dependencies_checked",
                        "guard": "供应商状态快照存在",
                    },
                    {
                        "from_state": "dependencies_checked",
                        "event": "APPLY_THRESHOLD",
                        "to_state": "threshold_routed",
                        "guard": "金额阈值政策版本存在",
                    },
                    {
                        "from_state": "threshold_routed",
                        "event": "BUILD_ROUTE",
                        "to_state": "route_ready",
                        "guard": "依赖与阈值结果均已形成",
                    },
                ],
                start_state="received",
                terminal_states=["route_ready"],
            ),
            evidence=[
                _evidence(
                    "02_procurement_approval",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_approval_fsm"],
                )
            ],
        ),
        _asset(
            asset_id="fsm.corporate_ops.onboarding.task_plan",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="员工入职任务计划",
                summary="根据规范化岗位和工作模式选择任务清单并排序依赖，仅生成计划而不创建账号或设备。",
                positive=["生成远程员工入职任务计划", "安排入职任务依赖"],
                anti=["立即创建员工账号", "直接采购或发放设备"],
                input_type="NormalizedRoleProfile + OnboardingContext",
                output_type="OnboardingTaskPlan",
                keywords=["入职", "任务清单", "岗位", "依赖", "远程"],
            ),
            contract=_contract(
                goal="生成依赖有序且可验证的入职任务计划，不执行外部资源创建。",
                operation="corporate_ops.onboarding.task_plan",
                input_schema=_schema(
                    "OnboardingPlanningInput",
                    {
                        "role_profile": object_value,
                        "work_mode": string,
                        "policy_version": string,
                    },
                    ["role_profile", "work_mode", "policy_version"],
                ),
                output_schema=_schema(
                    "OnboardingTaskPlan",
                    {
                        "tasks": array,
                        "dependency_order": array,
                        "human_gates": array,
                        "estimated_duration_hours": number,
                    },
                    ["tasks", "dependency_order", "human_gates"],
                ),
                preconditions=["岗位已规范化且入职政策版本已固定"],
                effects=["只生成任务计划，不创建账号、设备或培训记录"],
                failure_modes=["ROLE_PROFILE_INVALID", "TASK_DEPENDENCY_CYCLE"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="选择入职任务清单并形成无环依赖计划。",
                states=[
                    {"state_id": "role_ready", "invariant": "岗位代码与工作模式已经确定"},
                    {"state_id": "checklist_selected", "invariant": "清单来源和政策版本可追溯"},
                    {
                        "state_id": "dependencies_ordered",
                        "invariant": "任务依赖图已经确认无环",
                    },
                    {"state_id": "plan_ready", "invariant": "高风险动作均保留人工 Gate"},
                ],
                transitions=[
                    {
                        "from_state": "role_ready",
                        "event": "SELECT_CHECKLIST",
                        "to_state": "checklist_selected",
                        "guard": "角色和工作模式受支持",
                    },
                    {
                        "from_state": "checklist_selected",
                        "event": "ORDER_DEPENDENCIES",
                        "to_state": "dependencies_ordered",
                        "guard": "任务定义均具有稳定标识",
                    },
                    {
                        "from_state": "dependencies_ordered",
                        "event": "FINALIZE_PLAN",
                        "to_state": "plan_ready",
                        "guard": "依赖图无环且人工 Gate 完整",
                    },
                ],
                start_state="role_ready",
                terminal_states=["plan_ready"],
            ),
            evidence=[
                _evidence(
                    "03_employee_onboarding",
                    steps=["step_02", "step_03"],
                    candidates=["candidate_fsm_onboard_flow"],
                )
            ],
        ),
        _asset(
            asset_id="fsm.corporate_ops.leave.eligibility_route",
            kind=AssetKind.FSM_SHARD,
            recall_policy=RecallPolicy.ORDINARY,
            risk=RiskLevel.MEDIUM,
            header=_header(
                name="请假资格与审批路由",
                summary="结合日期、节假日和余额事实计算可扣天数，并形成通过、补充或人工审批路径。",
                positive=["检查年假余额并确定审批路径", "处理跨月含节假日请假"],
                anti=["直接扣减员工余额", "写入最终考勤记录"],
                input_type="LeaveRequestFacts + BusinessCalendarSnapshot",
                output_type="LeaveEligibilityRoute",
                keywords=["请假", "年假", "余额", "审批路由", "节假日"],
            ),
            contract=_contract(
                goal="形成请假资格检查结果与审批路由，不修改员工余额。",
                operation="corporate_ops.leave.eligibility_route",
                input_schema=_schema(
                    "LeaveEligibilityInput",
                    {
                        "leave_type": string,
                        "start_date": string,
                        "end_date": string,
                        "available_balance": number,
                        "calendar_snapshot": object_value,
                    },
                    [
                        "leave_type",
                        "start_date",
                        "end_date",
                        "available_balance",
                        "calendar_snapshot",
                    ],
                ),
                output_schema=_schema(
                    "LeaveEligibilityRoute",
                    {
                        "deductible_days": number,
                        "projected_balance": number,
                        "eligible": boolean,
                        "route": string,
                    },
                    ["deductible_days", "projected_balance", "eligible", "route"],
                ),
                preconditions=["日期区间、余额和日历快照均已验证"],
                effects=["只产生资格和路由结论，不扣减余额"],
                failure_modes=["DATE_RANGE_INVALID", "INSUFFICIENT_BALANCE"],
            ),
            body=_fsm_body(
                kind=AssetKind.FSM_SHARD,
                subgoal="完成请假可扣天数、余额和审批路径的联合判断。",
                states=[
                    {"state_id": "request_ready", "invariant": "假期类型和日期区间完整"},
                    {"state_id": "calendar_resolved", "invariant": "节假日和工作日事实已固定"},
                    {"state_id": "balance_checked", "invariant": "预计余额不被隐式写回"},
                    {"state_id": "route_ready", "invariant": "资格结论和审批路径已经形成"},
                ],
                transitions=[
                    {
                        "from_state": "request_ready",
                        "event": "RESOLVE_CALENDAR",
                        "to_state": "calendar_resolved",
                        "guard": "日期区间有效",
                    },
                    {
                        "from_state": "calendar_resolved",
                        "event": "CHECK_BALANCE",
                        "to_state": "balance_checked",
                        "guard": "应扣天数已确定",
                    },
                    {
                        "from_state": "balance_checked",
                        "event": "BUILD_ROUTE",
                        "to_state": "route_ready",
                        "guard": "资格结论可验证",
                    },
                ],
                start_state="request_ready",
                terminal_states=["route_ready"],
            ),
            evidence=[_evidence("04_leave_workflow", steps=["step_01", "step_02", "step_03"])],
        ),
        _asset(
            asset_id="adapter.corporate_ops.onboarding.role_profile",
            kind=AssetKind.ADAPTER,
            recall_policy=RecallPolicy.GRAPH_ONLY,
            risk=RiskLevel.LOW,
            header=_header(
                name="入职岗位规范化 Adapter",
                summary="把外部岗位描述确定性映射为内部岗位代码、培训类别和工作模式字段。",
                positive=["岗位描述转换为入职规划输入"],
                anti=["判断候选人是否录用", "生成入职任务计划"],
                input_type="RawRoleDescription",
                output_type="NormalizedRoleProfile",
                keywords=["岗位", "角色代码", "字段映射", "入职"],
            ),
            contract=_contract(
                goal="在原始岗位描述与入职计划输入之间执行确定性字段转换。",
                operation="corporate_ops.onboarding.role_profile_adapter",
                input_schema=_schema(
                    "RawRoleDescription",
                    {"job_title": string, "department": string, "work_mode": string},
                    ["job_title", "department", "work_mode"],
                ),
                output_schema=_schema(
                    "NormalizedRoleProfile",
                    {
                        "role_code": string,
                        "training_categories": array,
                        "work_mode": string,
                    },
                    ["role_code", "training_categories", "work_mode"],
                ),
                preconditions=["岗位映射表版本已固定"],
                effects=["仅转换字段，不做录用决策或外部写入"],
                failure_modes=["ROLE_MAPPING_NOT_FOUND", "WORK_MODE_UNSUPPORTED"],
            ),
            body=_adapter_body(
                kind=AssetKind.ADAPTER,
                from_schema="RawRoleDescription",
                to_schema="NormalizedRoleProfile",
                mappings=[
                    {
                        "source": "job_title",
                        "target": "role_code",
                        "transform": "NORMALIZE_ENUM",
                    },
                    {
                        "source": "department",
                        "target": "training_categories",
                        "transform": "NORMALIZE_ENUM",
                    },
                    {
                        "source": "work_mode",
                        "target": "work_mode",
                        "transform": "COPY",
                    },
                ],
            ),
            evidence=[
                _evidence(
                    "03_employee_onboarding",
                    steps=["step_01"],
                    candidates=["candidate_adapt_role_norm"],
                )
            ],
        ),
        _validator_asset(
            asset_id="validator.corporate_ops.expense.pre_audit",
            name="费用预审结果 Validator",
            summary="证明重复票据结果、政策违规项和处理路由均已形成。",
            schema_name="ExpensePreAuditDecision",
            rules=[
                {
                    "field": "duplicate_groups",
                    "operator": "EXISTS",
                    "failure_code": "DUPLICATE_RESULT_MISSING",
                },
                {
                    "field": "route",
                    "operator": "IN",
                    "expected": ["NORMAL", "HUMAN_REVIEW", "REJECT"],
                    "failure_code": "REVIEW_ROUTE_INVALID",
                },
            ],
            evidence=_evidence("01_expense_reimbursement", steps=["step_03", "step_04"]),
            keywords=["报销", "预审", "验证"],
        ),
        _validator_asset(
            asset_id="validator.corporate_ops.procurement.approval_route",
            name="采购审批路由 Validator",
            summary="证明采购路由包含金额阈值结果、供应商依赖结论和必要人工 Gate。",
            schema_name="ProcurementApprovalRoute",
            rules=[
                {
                    "field": "route_levels",
                    "operator": "EXISTS",
                    "failure_code": "APPROVAL_ROUTE_MISSING",
                },
                {
                    "field": "block_reasons",
                    "operator": "EXISTS",
                    "failure_code": "DEPENDENCY_RESULT_MISSING",
                },
            ],
            evidence=_evidence("02_procurement_approval", steps=["step_02", "step_03"]),
            keywords=["采购", "审批路径", "验证"],
        ),
        _validator_asset(
            asset_id="validator.corporate_ops.onboarding.task_plan",
            name="入职任务计划 Validator",
            summary="证明入职任务依赖无环、人工 Gate 完整且计划未执行外部写操作。",
            schema_name="OnboardingTaskPlan",
            rules=[
                {
                    "field": "dependency_order",
                    "operator": "EXISTS",
                    "failure_code": "DEPENDENCY_ORDER_MISSING",
                },
                {
                    "field": "human_gates",
                    "operator": "EXISTS",
                    "failure_code": "HUMAN_GATE_MISSING",
                },
            ],
            evidence=_evidence("03_employee_onboarding", steps=["step_02", "step_03"]),
            keywords=["入职", "依赖", "计划验证"],
        ),
        _validator_asset(
            asset_id="validator.corporate_ops.leave.eligibility_route",
            name="请假资格路由 Validator",
            summary="证明应扣天数和预计余额非负，并且资格结论具有明确审批路由。",
            schema_name="LeaveEligibilityRoute",
            rules=[
                {
                    "field": "deductible_days",
                    "operator": "NON_NEGATIVE",
                    "failure_code": "DEDUCTIBLE_DAYS_INVALID",
                },
                {
                    "field": "projected_balance",
                    "operator": "NON_NEGATIVE",
                    "failure_code": "INSUFFICIENT_BALANCE",
                },
                {
                    "field": "route",
                    "operator": "EXISTS",
                    "failure_code": "APPROVAL_ROUTE_MISSING",
                },
            ],
            evidence=_evidence("04_leave_workflow", steps=["step_03"]),
            keywords=["请假", "余额", "审批", "验证"],
        ),
        _asset(
            asset_id="skeleton.corporate_ops.review_and_route_daef",
            kind=AssetKind.WORKFLOW_SKELETON,
            recall_policy=RecallPolicy.PLANNING_PRIOR,
            risk=RiskLevel.LOW,
            header=_header(
                name="信息规范化—规则决策—行动—验证 DAEF",
                summary=(
                    "用于企业管理审查与路由任务的领域无关宏观阶段先验，"
                    "不绑定任何具体 Tool 或 FSM。"
                ),
                positive=["需要构建审查与路由类宏观计划", "信息经过规则判断后形成行动"],
                anti=["请求直接执行某个已知函数", "只需要字段格式转换"],
                input_type="GenericBusinessRequest",
                output_type="DAEFPlanningPrior",
                keywords=["DAEF", "信息", "转换", "决策", "行动", "验证"],
            ),
            contract=_contract(
                goal="为审查和路由类任务提供不绑定具体资产的宏观阶段规划先验。",
                operation="corporate_ops.daef.review_and_route",
                input_schema=_schema(
                    "GenericBusinessRequest",
                    {"request": object_value, "constraints": array},
                    ["request", "constraints"],
                ),
                output_schema=_schema(
                    "DAEFPlanningPrior",
                    {"stages": array, "required_invariants": array},
                    ["stages", "required_invariants"],
                ),
                preconditions=["任务包含可验证的目标和约束"],
                effects=["只提供规划先验，不产生可执行计划或业务副作用"],
                failure_modes=["TASK_GOAL_UNCLEAR", "CONSTRAINTS_MISSING"],
            ),
            body=_skeleton_body(
                kind=AssetKind.WORKFLOW_SKELETON,
                stages=[
                    {
                        "stage": "INFORMATION",
                        "expected_state": "请求、上下文和约束已经收集并具有来源",
                        "required_invariants": ["不在本阶段做业务批准"],
                    },
                    {
                        "stage": "TRANSFORM",
                        "expected_state": "输入已转换为下游可使用的类型化事实",
                        "required_invariants": ["转换不引入外部副作用"],
                    },
                    {
                        "stage": "DECISION",
                        "expected_state": "规则、依赖和风险已经形成结构化决策",
                        "required_invariants": ["关键歧义必须进入人工或澄清"],
                    },
                    {
                        "stage": "ACTION",
                        "expected_state": "允许的行动或处理路由已经完成",
                        "required_invariants": ["写操作必须经过权限和幂等检查"],
                    },
                    {
                        "stage": "VALIDATION",
                        "expected_state": "独立 Validator 已证明目标完成或给出失败码",
                        "required_invariants": ["模型不能批准自己的输出"],
                    },
                ],
            ),
            evidence=[
                _evidence("01_expense_reimbursement", steps=["step_01", "step_04"]),
                _evidence("02_procurement_approval", steps=["step_01", "step_03"]),
                _evidence("03_employee_onboarding", steps=["step_01", "step_03"]),
                _evidence("04_leave_workflow", steps=["step_01", "step_03"]),
            ],
        ),
    ]
    return assets


def _validator_asset(
    *,
    asset_id: str,
    name: str,
    summary: str,
    schema_name: str,
    rules: list[dict[str, Any]],
    evidence: SourceEvidence,
    keywords: list[str],
) -> AssetDefinition:
    return _asset(
        asset_id=asset_id,
        kind=AssetKind.VALIDATOR,
        recall_policy=RecallPolicy.GRAPH_ONLY,
        risk=RiskLevel.MEDIUM,
        header=_header(
            name=name,
            summary=summary,
            positive=[f"验证 {schema_name} 完成状态"],
            anti=["生成业务数据", "代替人工审批"],
            input_type=schema_name,
            output_type=f"ValidationResult<{schema_name}>",
            keywords=keywords,
        ),
        contract=_contract(
            goal=f"独立验证 {schema_name} 是否达到可接受的完成状态。",
            operation=asset_id.replace("validator.", "") + ".validate",
            input_schema=_schema(
                schema_name,
                {"payload": {"type": "object"}},
                ["payload"],
            ),
            output_schema=_schema(
                f"{schema_name}ValidationResult",
                {"valid": {"type": "boolean"}, "failure_codes": {"type": "array"}},
                ["valid", "failure_codes"],
            ),
            preconditions=["待验证输出已经通过基础 JSON Schema 校验"],
            effects=["只返回验证结果和类型化失败码"],
            failure_modes=["VALIDATOR_INPUT_INVALID", "VALIDATION_RULE_FAILED"],
        ),
        body=_validator_body(
            kind=AssetKind.VALIDATOR,
            validates_schema=schema_name,
            rules=rules,
            executor="DECLARATIVE_RULESET",
        ),
        evidence=[evidence],
    )


def build_corporate_operations_edges(
    assets: list[AssetDefinition],
) -> list[CapabilityEdge]:
    """Build only explicit one-hop dependencies supported by the four traces."""
    refs = {asset.asset_id: asset.asset_ref for asset in assets}
    return [
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.expense.pre_audit"],
            to_ref=refs["tool.corporate_ops.expense.duplicate_receipt_check"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="费用预审 FSM 的重复票据状态依赖确定性重复检测 Tool。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.expense.pre_audit"],
            to_ref=refs["validator.corporate_ops.expense.pre_audit"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="费用预审完成状态必须由独立 Validator 证明。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.procurement.approval_route"],
            to_ref=refs["tool.corporate_ops.procurement.vendor_status_lookup"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="采购路由需要只读供应商状态快照。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.procurement.approval_route"],
            to_ref=refs["validator.corporate_ops.procurement.approval_route"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="采购路由必须验证阈值结果与依赖阻断。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.onboarding.task_plan"],
            to_ref=refs["adapter.corporate_ops.onboarding.role_profile"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="入职任务计划以规范化岗位 Profile 为输入。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.onboarding.task_plan"],
            to_ref=refs["validator.corporate_ops.onboarding.task_plan"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="入职计划必须验证依赖无环与人工 Gate。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.leave.eligibility_route"],
            to_ref=refs["tool.corporate_ops.leave.business_calendar_lookup"],
            edge_type=EdgeType.DEPENDS_ON,
            evidence="请假资格路由需要工作日历快照计算应扣天数。",
        ),
        CapabilityEdge(
            from_ref=refs["fsm.corporate_ops.leave.eligibility_route"],
            to_ref=refs["validator.corporate_ops.leave.eligibility_route"],
            edge_type=EdgeType.REQUIRES_VALIDATOR,
            evidence="请假资格结论必须验证非负余额与明确路由。",
        ),
    ]
