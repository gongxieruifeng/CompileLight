"""Deterministic local handlers for the corporate_operations asset set."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
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


class CorporateOperationsRuntime:
    """Execute the small, deterministic corporate_operations capability set."""

    EXPENSE_POLICY_VERSION = "expense-policy.synthetic.cn.v1"
    PROCUREMENT_POLICY_VERSION = "procurement-policy.synthetic.v1"
    ONBOARDING_POLICY_VERSION = "onboarding-policy.synthetic.v1"
    LEAVE_POLICY_VERSION = "leave-policy.synthetic.cn.v1"

    POLICY_CATALOG: dict[str, dict[str, Any]] = {
        EXPENSE_POLICY_VERSION: {
            "currency": "CNY",
            "duplicate_match_keys": ["receipt_number"],
            "lodging_limits": {
                "CN-SH": 800.0,
                "CN-BJ": 750.0,
                "DEFAULT": 600.0,
            },
            "review_when": ["DUPLICATE_RECEIPT", "LODGING_LIMIT_EXCEEDED"],
            "synthetic": True,
        },
        PROCUREMENT_POLICY_VERSION: {
            "currency": "CNY",
            "approval_thresholds": [
                {"max_amount": 10000.0, "levels": ["LINE_MANAGER"]},
                {
                    "max_amount": 50000.0,
                    "levels": ["LINE_MANAGER", "FINANCE"],
                },
                {
                    "max_amount": None,
                    "levels": ["LINE_MANAGER", "FINANCE", "DIRECTOR"],
                },
            ],
            "supported_categories": ["SOFTWARE", "EQUIPMENT", "SERVICES"],
            "vendor_due_diligence_required": True,
            "attachments_required": True,
            "synthetic": True,
        },
        ONBOARDING_POLICY_VERSION: {
            "supported_role_codes": [
                "ROLE_CUSTOMER_SUPPORT",
                "ROLE_FINANCE_ANALYST",
            ],
            "supported_work_modes": ["REMOTE", "ONSITE"],
            "mandatory_human_gates": [
                "identity_review",
                "manager_confirmation",
            ],
            "external_resource_creation": False,
            "synthetic": True,
        },
        LEAVE_POLICY_VERSION: {
            "supported_regions": ["CN-SH", "CN-BJ"],
            "weekend_deductible": False,
            "public_holiday_deductible": False,
            "manager_review_above_days": 5.0,
            "negative_balance_allowed": False,
            "balance_write_back": False,
            "synthetic": True,
        },
        "daef-v1": {
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
        "expense": (
            "LOAD_FIXED_POLICY",
            "CHECK_DUPLICATE_RECEIPTS",
            "CHECK_LODGING_LIMITS",
            "BUILD_REVIEW_ROUTE",
            "VALIDATE_PRE_AUDIT_DECISION",
        ),
        "procurement": (
            "LOAD_FIXED_POLICY",
            "LOOKUP_VENDOR_STATUS",
            "CHECK_ATTACHMENTS",
            "APPLY_AMOUNT_THRESHOLDS",
            "VALIDATE_APPROVAL_ROUTE",
        ),
        "onboarding": (
            "NORMALIZE_ROLE_PROFILE",
            "SELECT_FIXED_CHECKLIST",
            "ORDER_DEPENDENCIES",
            "PRESERVE_HUMAN_GATES",
            "VALIDATE_TASK_PLAN",
        ),
        "leave": (
            "LOOKUP_FIXED_CALENDAR",
            "CALCULATE_DEDUCTIBLE_DAYS",
            "CHECK_PROJECTED_BALANCE",
            "BUILD_APPROVAL_ROUTE",
            "VALIDATE_ELIGIBILITY_RESULT",
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
            "tool.corporate_ops.expense.duplicate_receipt_check@1.0.0": (
                self.duplicate_receipt_check
            ),
            "tool.corporate_ops.procurement.vendor_status_lookup@1.0.0": (
                self.vendor_status_lookup
            ),
            "tool.corporate_ops.leave.business_calendar_lookup@1.0.0": (
                self.business_calendar_lookup
            ),
            "fsm.corporate_ops.expense.pre_audit@1.0.0": self.expense_pre_audit,
            "fsm.corporate_ops.procurement.approval_route@1.0.0": (
                self.procurement_approval_route
            ),
            "fsm.corporate_ops.onboarding.task_plan@1.0.0": self.onboarding_task_plan,
            "fsm.corporate_ops.leave.eligibility_route@1.0.0": (
                self.leave_eligibility_route
            ),
            "adapter.corporate_ops.onboarding.role_profile@1.0.0": (
                self.role_profile_adapter
            ),
            "validator.corporate_ops.expense.pre_audit@1.0.0": (
                self.validate_expense_pre_audit
            ),
            "validator.corporate_ops.procurement.approval_route@1.0.0": (
                self.validate_procurement_route
            ),
            "validator.corporate_ops.onboarding.task_plan@1.0.0": (
                self.validate_onboarding_plan
            ),
            "validator.corporate_ops.leave.eligibility_route@1.0.0": (
                self.validate_leave_route
            ),
        }
        self._planning_priors = {
            "skeleton.corporate_ops.review_and_route_daef@1.0.0": {
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
            **{
                "tool.corporate_ops.expense.duplicate_receipt_check@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "duplicate_receipt_check",
                    "EXECUTABLE",
                    self.EXPENSE_POLICY_VERSION,
                    ("同一凭证号不得重复报销", "相同日期与商户组合不得重复报销"),
                    "READ_ONLY",
                ),
                "tool.corporate_ops.procurement.vendor_status_lookup@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "vendor_status_lookup",
                    "EXECUTABLE",
                    self.PROCUREMENT_POLICY_VERSION,
                    ("尽调未完成不得生成最终采购订单",),
                    "READ_ONLY",
                ),
                "tool.corporate_ops.leave.business_calendar_lookup@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "business_calendar_lookup",
                    "EXECUTABLE",
                    self.LEAVE_POLICY_VERSION,
                    ("周末和法定节假日不计入应扣工作日",),
                    "READ_ONLY",
                ),
                "fsm.corporate_ops.expense.pre_audit@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "expense_pre_audit",
                    "EXECUTABLE",
                    self.EXPENSE_POLICY_VERSION,
                    ("重复票据或住宿超标必须进入人工复核",),
                    "NONE",
                ),
                "fsm.corporate_ops.procurement.approval_route@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "procurement_approval_route",
                    "EXECUTABLE",
                    self.PROCUREMENT_POLICY_VERSION,
                    ("金额阈值决定审批层级", "供应商尽调未完成时阻断"),
                    "NONE",
                ),
                "fsm.corporate_ops.onboarding.task_plan@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "onboarding_task_plan",
                    "EXECUTABLE",
                    self.ONBOARDING_POLICY_VERSION,
                    ("任务依赖必须无环", "高风险任务保留人工 Gate"),
                    "NONE",
                ),
                "fsm.corporate_ops.leave.eligibility_route@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "leave_eligibility_route",
                    "EXECUTABLE",
                    self.LEAVE_POLICY_VERSION,
                    ("预计余额不得为负数", "跨月日期按工作日计算"),
                    "NONE",
                ),
                "adapter.corporate_ops.onboarding.role_profile@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "role_profile_adapter",
                    "EXECUTABLE",
                    self.ONBOARDING_POLICY_VERSION,
                    ("岗位代码来自固定合成映射表",),
                    "NONE",
                ),
                "validator.corporate_ops.expense.pre_audit@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "validate_expense_pre_audit",
                    "EXECUTABLE",
                    self.EXPENSE_POLICY_VERSION,
                    ("路由和重复检测结果必须存在",),
                    "NONE",
                ),
                "validator.corporate_ops.procurement.approval_route@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "validate_procurement_route",
                    "EXECUTABLE",
                    self.PROCUREMENT_POLICY_VERSION,
                    ("审批层级和阻断原因字段必须存在",),
                    "NONE",
                ),
                "validator.corporate_ops.onboarding.task_plan@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "validate_onboarding_plan",
                    "EXECUTABLE",
                    self.ONBOARDING_POLICY_VERSION,
                    ("依赖顺序必须覆盖所有任务",),
                    "NONE",
                ),
                "validator.corporate_ops.leave.eligibility_route@1.0.0": RuntimeMetadata(
                    "python://reduce_token_agent.assets_runtime.corporate_operations:"
                    "validate_leave_route",
                    "EXECUTABLE",
                    self.LEAVE_POLICY_VERSION,
                    ("预计余额和审批路由必须可验证",),
                    "NONE",
                ),
            },
            "skeleton.corporate_ops.review_and_route_daef@1.0.0": RuntimeMetadata(
                "daef://corporate_ops/review_and_route",
                "PLANNING_ONLY",
                "daef-v1",
                ("阶段顺序固定为信息、转换、决策、行动、验证",),
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
        expense_receipts = [
            {
                "receipt_id": "receipt_001",
                "receipt_number": "RCP-2026-0001",
                "merchant": "上海示例酒店",
                "transaction_date": "2026-01-05",
            },
            {
                "receipt_id": "receipt_002",
                "receipt_number": "RCP-2026-0001",
                "merchant": "上海示例酒店",
                "transaction_date": "2026-01-05",
            },
        ]
        expense_policy_limits = dict(
            self.POLICY_CATALOG[self.EXPENSE_POLICY_VERSION]["lodging_limits"]
        )
        vendor_status = {
            "vendor_id": "V001",
            "status": "APPROVED",
            "due_diligence_complete": True,
        }
        onboarding_role_profile = {
            "role_code": "ROLE_CUSTOMER_SUPPORT",
            "training_categories": ["SECURITY_AWARENESS", "SERVICE_TRAINING"],
            "work_mode": "REMOTE",
        }
        leave_calendar = {
            "working_days": ["2026-01-02", "2026-01-05"],
            "holidays": ["2026-01-01"],
            "deductible_days": 2.0,
        }
        expense_decision = {
            "duplicate_groups": [
                {
                    "match_key": ["RCP-2026-0001"],
                    "receipt_ids": ["receipt_001", "receipt_002"],
                }
            ],
            "policy_violations": [
                {
                    "receipt_id": "receipt_001",
                    "city": "CN-SH",
                    "amount": 920.0,
                    "limit": 800.0,
                    "excess_amount": 120.0,
                }
            ],
            "route": "HUMAN_REVIEW",
            "human_review_required": True,
        }
        procurement_route = {
            "route_levels": ["LINE_MANAGER", "FINANCE", "DIRECTOR"],
            "blocked": False,
            "block_reasons": [],
            "human_review_required": True,
        }
        onboarding_plan = {
            "tasks": [
                {"task_id": "identity_review", "depends_on": []},
                {"task_id": "account_request", "depends_on": ["identity_review"]},
                {
                    "task_id": "remote_equipment_shipping",
                    "depends_on": ["identity_review"],
                },
                {"task_id": "equipment_request", "depends_on": ["identity_review"]},
                {"task_id": "training_assignment", "depends_on": ["account_request"]},
            ],
            "dependency_order": [
                "identity_review",
                "account_request",
                "equipment_request",
                "remote_equipment_shipping",
                "training_assignment",
            ],
            "human_gates": ["identity_review", "manager_confirmation"],
            "estimated_duration_hours": 16.0,
        }
        leave_route = {
            "deductible_days": 2.0,
            "projected_balance": 8.0,
            "eligible": True,
            "route": "AUTO_APPROVE",
        }
        return {
            "tool.corporate_ops.expense.duplicate_receipt_check@1.0.0": {
                "receipts": expense_receipts,
                "match_keys": ["receipt_number"],
            },
            "tool.corporate_ops.procurement.vendor_status_lookup@1.0.0": {
                "vendor_id": "V001",
            },
            "tool.corporate_ops.leave.business_calendar_lookup@1.0.0": {
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "region": "CN-SH",
            },
            "fsm.corporate_ops.expense.pre_audit@1.0.0": {
                "receipts": expense_receipts,
                "lodging_items": [
                    {"receipt_id": "receipt_001", "city": "CN-SH", "amount": 920.0},
                ],
                "policy_limits": expense_policy_limits,
            },
            "fsm.corporate_ops.procurement.approval_route@1.0.0": {
                "amount": 52000.0,
                "category": "SOFTWARE",
                "attachments_complete": True,
                "vendor_status": vendor_status,
            },
            "fsm.corporate_ops.onboarding.task_plan@1.0.0": {
                "role_profile": onboarding_role_profile,
                "work_mode": "REMOTE",
                "policy_version": self.ONBOARDING_POLICY_VERSION,
            },
            "fsm.corporate_ops.leave.eligibility_route@1.0.0": {
                "leave_type": "ANNUAL",
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
                "available_balance": 10.0,
                "calendar_snapshot": leave_calendar,
            },
            "adapter.corporate_ops.onboarding.role_profile@1.0.0": {
                "job_title": "客户支持专员",
                "department": "客服中心",
                "work_mode": "REMOTE",
            },
            "validator.corporate_ops.expense.pre_audit@1.0.0": {
                "payload": expense_decision,
            },
            "validator.corporate_ops.procurement.approval_route@1.0.0": {
                "payload": procurement_route,
            },
            "validator.corporate_ops.onboarding.task_plan@1.0.0": {
                "payload": onboarding_plan,
            },
            "validator.corporate_ops.leave.eligibility_route@1.0.0": {
                "payload": leave_route,
            },
            "skeleton.corporate_ops.review_and_route_daef@1.0.0": {
                "request": {
                    "domain": "corporate_operations",
                    "intent": "review_and_route",
                },
                "constraints": ["policy_bound", "no_direct_execution"],
            },
        }

    def sample_payload(self, asset_ref: str) -> dict[str, Any]:
        """Return the canonical success payload for one exact asset ref."""
        try:
            return dict(self.sample_payloads()[asset_ref])
        except KeyError as exc:
            raise RuntimeExecutionError("SAMPLE_PAYLOAD_NOT_FOUND", asset_ref) from exc

    def duplicate_receipt_check(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Detect duplicate synthetic receipts by stable configured keys."""
        receipts = _list_of_dicts(payload, "receipts")
        match_keys = _string_list(payload, "match_keys")
        if not match_keys:
            raise RuntimeExecutionError("DUPLICATE_KEY_MISSING", "match_keys is empty")
        groups: dict[tuple[Any, ...], list[str]] = {}
        for receipt in receipts:
            receipt_id = _required_string(receipt, "receipt_id")
            try:
                key = tuple(receipt[key_name] for key_name in match_keys)
            except KeyError as exc:
                raise RuntimeExecutionError(
                    "RECEIPT_SCHEMA_INVALID",
                    f"receipt is missing key {exc.args[0]}",
                ) from exc
            groups.setdefault(key, []).append(receipt_id)
        duplicate_groups = [
            {"match_key": list(key), "receipt_ids": ids}
            for key, ids in groups.items()
            if len(ids) > 1
        ]
        return {
            "duplicate_groups": duplicate_groups,
            "has_duplicates": bool(duplicate_groups),
        }

    def vendor_status_lookup(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Read one entry from the local synthetic vendor policy catalog."""
        vendor_id = _required_string(payload, "vendor_id")
        catalog = {
            "V001": {"status": "APPROVED", "due_diligence_complete": True},
            "V002": {"status": "PENDING_REVIEW", "due_diligence_complete": False},
            "V003": {"status": "SUSPENDED", "due_diligence_complete": False},
        }
        try:
            status = catalog[vendor_id]
        except KeyError as exc:
            raise RuntimeExecutionError("VENDOR_NOT_FOUND", vendor_id) from exc
        return {"vendor_id": vendor_id, **status}

    def business_calendar_lookup(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Return synthetic China working days and holidays for a date range."""
        start = _parse_date(payload, "start_date")
        end = _parse_date(payload, "end_date")
        if start > end:
            raise RuntimeExecutionError("DATE_RANGE_INVALID", "start_date is after end_date")
        region = _required_string(payload, "region")
        if region not in {"CN-SH", "CN-BJ"}:
            raise RuntimeExecutionError("CALENDAR_REGION_UNSUPPORTED", region)
        holidays_by_region = {
            "CN-SH": {"2026-01-01", "2026-05-01"},
            "CN-BJ": {"2026-01-01", "2026-10-01"},
        }
        holiday_set = holidays_by_region[region]
        working_days: list[str] = []
        holidays: list[str] = []
        current = start
        while current <= end:
            iso = current.isoformat()
            if current.weekday() >= 5 or iso in holiday_set:
                if iso in holiday_set:
                    holidays.append(iso)
            else:
                working_days.append(iso)
            current += timedelta(days=1)
        return {
            "working_days": working_days,
            "holidays": holidays,
            "deductible_days": float(len(working_days)),
        }

    def expense_pre_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run duplicate and lodging-policy checks, then route for review."""
        expense_policy = self.POLICY_CATALOG[self.EXPENSE_POLICY_VERSION]
        supplied_limits = payload.get("policy_limits")
        expected_limits = expense_policy["lodging_limits"]
        if supplied_limits != expected_limits:
            raise RuntimeExecutionError(
                "POLICY_VERSION_MISSING",
                "policy_limits must match the registered synthetic policy",
            )
        duplicate_result = self.duplicate_receipt_check(
            {
                "receipts": payload.get("receipts", []),
                "match_keys": expense_policy["duplicate_match_keys"],
            }
        )
        lodging_items = _list_of_dicts(payload, "lodging_items")
        policy_limits = expected_limits
        violations: list[dict[str, Any]] = []
        for item in lodging_items:
            city = _required_string(item, "city")
            amount = _number(item, "amount")
            limit_value = policy_limits.get(city, policy_limits.get("DEFAULT"))
            if not isinstance(limit_value, (int, float)):
                raise RuntimeExecutionError("POLICY_VERSION_MISSING", city)
            if amount > limit_value:
                violations.append(
                    {
                        "receipt_id": _required_string(item, "receipt_id"),
                        "city": city,
                        "amount": amount,
                        "limit": limit_value,
                        "excess_amount": round(amount - limit_value, 2),
                    }
                )
        human_review_required = bool(
            duplicate_result["has_duplicates"] or violations
        )
        return {
            "duplicate_groups": duplicate_result["duplicate_groups"],
            "policy_violations": violations,
            "route": "HUMAN_REVIEW" if human_review_required else "NORMAL",
            "human_review_required": human_review_required,
        }

    def procurement_approval_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Apply synthetic amount/vendor/attachment policy to an approval route."""
        policy = self.POLICY_CATALOG[self.PROCUREMENT_POLICY_VERSION]
        amount = _number(payload, "amount")
        category = _required_string(payload, "category")
        attachments_complete = payload.get("attachments_complete")
        vendor_status = payload.get("vendor_status")
        if not isinstance(attachments_complete, bool) or not isinstance(vendor_status, dict):
            raise RuntimeExecutionError("PROCUREMENT_INPUT_INVALID", "route input is incomplete")
        route_levels: list[str] = []
        for threshold in policy["approval_thresholds"]:
            max_amount = threshold["max_amount"]
            if max_amount is None or amount <= max_amount:
                route_levels = list(threshold["levels"])
                break
        block_reasons: list[str] = []
        if not attachments_complete:
            block_reasons.append("ATTACHMENTS_INCOMPLETE")
        if vendor_status.get("due_diligence_complete") is not True:
            block_reasons.append("VENDOR_NOT_VERIFIED")
        if category not in set(policy["supported_categories"]):
            block_reasons.append("CATEGORY_UNSUPPORTED")
        blocked = bool(block_reasons)
        return {
            "route_levels": route_levels,
            "blocked": blocked,
            "block_reasons": block_reasons,
            "human_review_required": blocked or amount > 50000,
        }

    def onboarding_task_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Create a deterministic, dependency-ordered synthetic onboarding plan."""
        role_profile = payload.get("role_profile")
        work_mode = _required_string(payload, "work_mode")
        policy_version = _required_string(payload, "policy_version")
        if not isinstance(role_profile, dict) or not policy_version:
            raise RuntimeExecutionError("ROLE_PROFILE_INVALID", "role_profile is required")
        if policy_version != self.ONBOARDING_POLICY_VERSION:
            raise RuntimeExecutionError("POLICY_VERSION_MISSING", policy_version)
        role_code = _required_string(role_profile, "role_code")
        task_sets = {
            "ROLE_CUSTOMER_SUPPORT": [
                ("identity_review", []),
                ("account_request", ["identity_review"]),
                ("equipment_request", ["identity_review"]),
                ("training_assignment", ["account_request"]),
            ],
            "ROLE_FINANCE_ANALYST": [
                ("identity_review", []),
                ("account_request", ["identity_review"]),
                ("finance_access_review", ["account_request"]),
                ("training_assignment", ["finance_access_review"]),
            ],
        }
        try:
            task_specs = task_sets[role_code]
        except KeyError as exc:
            raise RuntimeExecutionError("ROLE_PROFILE_INVALID", role_code) from exc
        tasks = [
            {"task_id": task_id, "depends_on": dependencies}
            for task_id, dependencies in task_specs
        ]
        if work_mode == "REMOTE":
            tasks.insert(
                2,
                {"task_id": "remote_equipment_shipping", "depends_on": ["identity_review"]},
            )
        dependency_order = _topological_order(tasks)
        return {
            "tasks": tasks,
            "dependency_order": dependency_order,
            "human_gates": list(
                self.POLICY_CATALOG[self.ONBOARDING_POLICY_VERSION][
                    "mandatory_human_gates"
                ]
            ),
            "estimated_duration_hours": float(16 if work_mode == "REMOTE" else 12),
        }

    def leave_eligibility_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Calculate leave deduction and route without mutating the balance."""
        _required_string(payload, "leave_type")
        start = _parse_date(payload, "start_date")
        end = _parse_date(payload, "end_date")
        balance = _number(payload, "available_balance")
        snapshot = payload.get("calendar_snapshot")
        if not isinstance(snapshot, dict):
            raise RuntimeExecutionError("CALENDAR_SNAPSHOT_MISSING", "snapshot is required")
        deductible_days = snapshot.get("deductible_days")
        if not isinstance(deductible_days, (int, float)) or start > end:
            raise RuntimeExecutionError("DATE_RANGE_INVALID", "invalid leave facts")
        projected = round(balance - float(deductible_days), 2)
        eligible = projected >= 0
        manager_threshold = self.POLICY_CATALOG[self.LEAVE_POLICY_VERSION][
            "manager_review_above_days"
        ]
        if not eligible:
            route = "HUMAN_REVIEW"
        elif deductible_days > manager_threshold:
            route = "MANAGER_REVIEW"
        else:
            route = "AUTO_APPROVE"
        return {
            "deductible_days": float(deductible_days),
            "projected_balance": projected,
            "eligible": eligible,
            "route": route,
        }

    def role_profile_adapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Map a synthetic external role description to an internal profile."""
        job_title = _required_string(payload, "job_title")
        _required_string(payload, "department")
        work_mode = _required_string(payload, "work_mode")
        if work_mode not in {"REMOTE", "ONSITE"}:
            raise RuntimeExecutionError("WORK_MODE_UNSUPPORTED", work_mode)
        mappings = {
            "客户支持专员": ("ROLE_CUSTOMER_SUPPORT", ["SECURITY_AWARENESS", "SERVICE_TRAINING"]),
            "财务分析师": ("ROLE_FINANCE_ANALYST", ["FINANCE_POLICY", "DATA_PROTECTION"]),
        }
        try:
            role_code, training_categories = mappings[job_title]
        except KeyError as exc:
            raise RuntimeExecutionError("ROLE_MAPPING_NOT_FOUND", job_title) from exc
        return {
            "role_code": role_code,
            "training_categories": training_categories,
            "work_mode": work_mode,
        }

    def validate_expense_pre_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Independently validate expense pre-audit completion."""
        subject = _validator_subject(payload)
        failures: list[str] = []
        if not isinstance(subject.get("duplicate_groups"), list):
            failures.append("DUPLICATE_RESULT_MISSING")
        if subject.get("route") not in {"NORMAL", "HUMAN_REVIEW", "REJECT"}:
            failures.append("REVIEW_ROUTE_INVALID")
        if subject.get("human_review_required") is not (
            subject.get("route") == "HUMAN_REVIEW"
        ):
            failures.append("REVIEW_GATE_INCONSISTENT")
        return {"valid": not failures, "failure_codes": failures}

    def validate_procurement_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Independently validate procurement route fields and blocking policy."""
        subject = _validator_subject(payload)
        failures: list[str] = []
        if not isinstance(subject.get("route_levels"), list):
            failures.append("APPROVAL_ROUTE_MISSING")
        if not isinstance(subject.get("block_reasons"), list):
            failures.append("DEPENDENCY_RESULT_MISSING")
        if subject.get("blocked") is True and subject.get("human_review_required") is not True:
            failures.append("HUMAN_GATE_MISSING")
        return {"valid": not failures, "failure_codes": failures}

    def validate_onboarding_plan(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Independently validate onboarding tasks and dependency order."""
        subject = _validator_subject(payload)
        failures: list[str] = []
        tasks = subject.get("tasks")
        order = subject.get("dependency_order")
        gates = subject.get("human_gates")
        if not isinstance(tasks, list) or not isinstance(order, list):
            failures.append("DEPENDENCY_ORDER_MISSING")
        else:
            task_ids = {task.get("task_id") for task in tasks if isinstance(task, dict)}
            if task_ids != set(order):
                failures.append("DEPENDENCY_ORDER_INCOMPLETE")
        if not isinstance(gates, list) or not gates:
            failures.append("HUMAN_GATE_MISSING")
        return {"valid": not failures, "failure_codes": failures}

    def validate_leave_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Independently validate leave balance and approval route."""
        subject = _validator_subject(payload)
        failures: list[str] = []
        deductible = subject.get("deductible_days")
        projected = subject.get("projected_balance")
        if not isinstance(deductible, (int, float)) or deductible < 0:
            failures.append("DEDUCTIBLE_DAYS_INVALID")
        if not isinstance(projected, (int, float)) or projected < 0:
            failures.append("INSUFFICIENT_BALANCE")
        if not isinstance(subject.get("route"), str) or not subject["route"]:
            failures.append("APPROVAL_ROUTE_MISSING")
        return {"valid": not failures, "failure_codes": failures}


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeExecutionError("INPUT_SCHEMA_INVALID", f"{field} is required")
    return value.strip()


def _string_list(payload: dict[str, Any], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeExecutionError("INPUT_SCHEMA_INVALID", f"{field} must be string list")
    return value


def _list_of_dicts(payload: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RuntimeExecutionError("INPUT_SCHEMA_INVALID", f"{field} must be object list")
    return value


def _number(payload: dict[str, Any], field: str) -> float:
    value = payload.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RuntimeExecutionError("INPUT_SCHEMA_INVALID", f"{field} must be numeric")
    return float(value)


def _parse_date(payload: dict[str, Any], field: str) -> date:
    value = _required_string(payload, field)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeExecutionError("DATE_RANGE_INVALID", value) from exc


def _topological_order(tasks: list[dict[str, Any]]) -> list[str]:
    """Produce a stable topological ordering or reject a dependency cycle."""
    by_id = {task["task_id"]: task for task in tasks}
    resolved: list[str] = []
    remaining = set(by_id)
    while remaining:
        ready = sorted(
            task_id
            for task_id in remaining
            if set(by_id[task_id].get("depends_on", [])).issubset(resolved)
        )
        if not ready:
            raise RuntimeExecutionError("TASK_DEPENDENCY_CYCLE", "dependency graph has a cycle")
        resolved.extend(ready)
        remaining.difference_update(ready)
    return resolved


def _flow_key(asset_ref: str) -> str:
    if ".expense." in asset_ref:
        return "expense"
    if ".procurement." in asset_ref:
        return "procurement"
    if ".onboarding." in asset_ref:
        return "onboarding"
    if ".leave." in asset_ref:
        return "leave"
    if asset_ref.startswith("skeleton."):
        return "daef"
    raise RuntimeExecutionError("ASSET_METADATA_INVALID", asset_ref)


def _validator_subject(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept either a wrapped contract payload or the raw validation body."""
    subject = payload.get("payload")
    if isinstance(subject, dict):
        return subject
    return payload
