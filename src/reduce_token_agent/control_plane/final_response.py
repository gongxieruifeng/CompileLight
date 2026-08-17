"""Grounded, traceable user-response synthesis from execution facts."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from reduce_token_agent.domain.blueprint import BlueprintProposal, StepType
from reduce_token_agent.domain.control import HandoffReceipt, RoutingDecision
from reduce_token_agent.domain.task import ClarificationRequest, TaskContext
from reduce_token_agent.llm.base import StructuredModel, StructuredUsage

_EXTERNAL_WRITE_CLAIM = re.compile(
    r"(?:已经|已)(?:成功)?(?:提交|发送|通知|创建|注册|更新|归档|冻结|修改|写入|移交)"
    r"|(?:正式提交|完成提交)"
)
_EXTERNAL_WRITE_REQUEST = re.compile(
    r"(?:提交|发送|通知|创建|注册|更新|归档|冻结|修改|写入|移交)"
)
_CAPABILITY_QUERY = re.compile(
    r"(?:introduce\s+(?:your|the)\s+(?:ability|capabilit)|what\s+can\s+you\s+do|"
    r"介绍.{0,8}(?:能力|功能)|你能做什么|你会做什么)",
    re.IGNORECASE,
)
_INTERNAL_RESPONSE_MARKER = re.compile(
    r"(?:artifact://|trace://|step_[a-z0-9_]+|\b(?:REUSE|HYBRID|NEW)\b)"
)

_FIELD_LABELS = {
    "intent_category": "业务意图",
    "route_family": "建议处理流程",
    "risk_level": "风险等级",
    "human_review_hint": "是否建议人工复核",
    "human_review_required": "是否需要人工复核",
    "route": "处理结论",
    "blocked": "是否阻断",
    "valid": "校验结果",
    "normalized_summary": "请求摘要",
    "amount": "金额",
    "due_date": "到期日",
    "payment_date": "扣款日期",
    "repayment_amount": "应还金额",
}
_VALUE_LABELS = {
    "LOW": "低",
    "MEDIUM": "中",
    "HIGH": "高",
    "billing_answer": "账务查询答复",
    "repayment_inquiry": "还款信息查询",
    "PASS": "通过",
    "NORMAL": "正常处理",
    "HUMAN_REVIEW": "转人工复核",
    "REJECT": "拒绝",
}


class FinalResponseDraft(BaseModel):
    """Untrusted model synthesis before evidence and policy checks."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=20, max_length=3000)
    evidence_step_ids: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=10)


def compose_final_response(
    *,
    run_id: str,
    routing: RoutingDecision,
    execution_status: str,
    proposal: BlueprintProposal | None,
    langgraph_receipt: HandoffReceipt | None,
    system2_receipt: HandoffReceipt | None,
    task_context: TaskContext | None = None,
    clarification: ClarificationRequest | None = None,
    model: StructuredModel | None = None,
) -> tuple[dict[str, Any], StructuredUsage | None]:
    """Create one coherent answer while treating execution output as evidence."""
    if clarification is not None:
        return (
            _base_payload(
                run_id=run_id,
                status="CLARIFY",
                mode=routing.mode.value,
                answer=clarification.message,
                generation_method="DETERMINISTIC_STATUS",
            ),
            None,
        )

    execution = _execution(langgraph_receipt, system2_receipt)
    pending_step_ids = (
        list(execution.placeholder_step_ids) if execution is not None else []
    )
    failure_code = execution.failure_code if execution is not None else None
    business_validated = (
        execution.business_validated if execution is not None else False
    )
    goals = {
        step.step_id: step.goal
        for step in (proposal.steps if proposal is not None else [])
    }
    step_types = {
        step.step_id: step.step_type
        for step in (proposal.steps if proposal is not None else [])
    }
    result_items: list[dict[str, Any]] = []
    if execution is not None:
        for step in execution.step_results:
            if step_types.get(step.step_id) is StepType.VALIDATOR:
                continue
            result_items.append(
                {
                    "step_id": step.step_id,
                    "goal": goals.get(step.step_id, step.subgoal_id),
                    "status": step.status,
                    "validation_status": step.validation_status,
                    "business_validated": step.business_validated,
                    "input_source": step.input_source,
                    "summary": _output_summary(step.output_summary),
                    "artifact_refs": list(step.artifact_refs),
                }
            )
    user_input_grounded = not any(
        "SAMPLE" in str(item["input_source"])
        for item in result_items
    )
    external_write_executed = bool(
        proposal is not None
        and any(
            step.side_effect.value == "LOCAL_WRITE"
            for step in proposal.steps
        )
    )
    external_write_requested = bool(
        task_context is not None
        and (
            task_context.irreversible_action_requested
            or _EXTERNAL_WRITE_REQUEST.search(task_context.query)
        )
    )
    policy_limitations = _policy_limitations(
        business_validated=business_validated,
        user_input_grounded=user_input_grounded,
        external_write_executed=external_write_executed,
        external_write_requested=external_write_requested,
    )

    if execution_status != "SUCCEEDED":
        answer = _status_answer(
            execution_status=execution_status,
            pending_goals=[
                goals.get(step_id, "需要人工确认的事项")
                for step_id in pending_step_ids
            ],
            failure_code=failure_code,
        )
        return (
            {
                **_base_payload(
                    run_id=run_id,
                    status=execution_status,
                    mode=routing.mode.value,
                    answer=answer,
                    generation_method="DETERMINISTIC_STATUS",
                ),
                "result_items": result_items,
                "pending_step_ids": pending_step_ids,
                "failure_code": failure_code,
                "business_validated": business_validated,
                "user_input_grounded": user_input_grounded,
                "external_write_executed": external_write_executed,
                "limitations": policy_limitations,
            },
            None,
        )

    if task_context is not None and _CAPABILITY_QUERY.search(task_context.query):
        answer = _capability_answer()
        return (
            {
                **_base_payload(
                    run_id=run_id,
                    status=execution_status,
                    mode=routing.mode.value,
                    answer=answer,
                    generation_method="DETERMINISTIC_CAPABILITY_ANSWER",
                ),
                "result_items": result_items,
                "pending_step_ids": pending_step_ids,
                "failure_code": failure_code,
                "business_validated": business_validated,
                "user_input_grounded": user_input_grounded,
                "external_write_executed": external_write_executed,
                "limitations": policy_limitations,
            },
            None,
        )

    answer_evidence = _deduplicated_evidence(
        result_items,
        grounded_only=True,
    )
    if not user_input_grounded:
        answer = _grounded_fallback_answer(
            task_context=task_context,
            result_items=result_items,
            limitations=policy_limitations,
        )
        return (
            {
                **_base_payload(
                    run_id=run_id,
                    status=execution_status,
                    mode=routing.mode.value,
                    answer=answer,
                    generation_method="DETERMINISTIC_UNGROUNDED_NOTICE",
                ),
                "result_items": result_items,
                "pending_step_ids": pending_step_ids,
                "failure_code": failure_code,
                "business_validated": business_validated,
                "user_input_grounded": False,
                "external_write_executed": external_write_executed,
                "limitations": policy_limitations,
            },
            None,
        )

    allowed_step_ids = {
        str(item["step_id"])
        for item in answer_evidence
    }
    draft: FinalResponseDraft | None = None
    usage: StructuredUsage | None = None
    rejection_code: str | None = None
    if model is not None:
        try:
            generated = model.generate_structured(
                stage="final_response",
                system_prompt=(
                    "你负责把已完成任务的结构化执行证据组织成一份面向最终用户的完整"
                    "回答。直接回答用户原问题，不要按执行步骤逐条机械拼接，不要解释"
                    "内部 REUSE/HYBRID/NEW 路由。只能使用 execution_evidence 中的事实；"
                    "不得把运行完成等同于业务事实已验证。若 user_input_grounded=false，"
                    "必须明确说明当前结果来自演示样例输入，不能作为用户真实业务结论。"
                    "若 external_write_executed=false，不得声称已提交、发送、通知、创建、"
                    "注册、更新、归档、冻结或修改外部系统。缺少原始合同、附件或权威数据"
                    "时，应给出当前能确认的内容、不能确认的内容和下一步所需材料。不要"
                    "输出思维链。evidence_step_ids 只能选择给定步骤 ID。"
                ),
                user_payload={
                    "task": {
                        "query": (
                            task_context.query
                            if task_context is not None
                            else "[QUERY_NOT_AVAILABLE]"
                        ),
                        "acceptance_criteria": (
                            task_context.acceptance_criteria
                            if task_context is not None
                            else []
                        ),
                    },
                    "execution_status": execution_status,
                    "business_validated": business_validated,
                    "user_input_grounded": user_input_grounded,
                    "external_write_executed": external_write_executed,
                    "policy_limitations": policy_limitations,
                    "execution_evidence": answer_evidence,
                    "allowed_evidence_step_ids": sorted(allowed_step_ids),
                },
                output_model=FinalResponseDraft,
            )
            draft = generated.value
            usage = generated.usage
            if not set(draft.evidence_step_ids).issubset(allowed_step_ids):
                rejection_code = "FINAL_RESPONSE_EVIDENCE_SCOPE_REJECTED"
            elif allowed_step_ids and not draft.evidence_step_ids:
                rejection_code = "FINAL_RESPONSE_EVIDENCE_REQUIRED"
            elif (
                not external_write_executed
                and _EXTERNAL_WRITE_CLAIM.search(draft.answer)
            ):
                rejection_code = "FINAL_RESPONSE_EXTERNAL_WRITE_CLAIM_REJECTED"
            elif _contains_machine_payload(draft.answer):
                rejection_code = "FINAL_RESPONSE_MACHINE_PAYLOAD_REJECTED"
        except Exception:
            rejection_code = "FINAL_RESPONSE_MODEL_FALLBACK"

    if draft is None or rejection_code is not None:
        answer = _grounded_fallback_answer(
            task_context=task_context,
            result_items=result_items,
            limitations=policy_limitations,
        )
        evidence_step_ids = sorted(allowed_step_ids)
        model_limitations: list[str] = []
        generation_method = "DETERMINISTIC_GROUNDED_FALLBACK"
    else:
        answer = draft.answer.strip()
        evidence_step_ids = list(draft.evidence_step_ids)
        model_limitations = list(draft.limitations)
        generation_method = "LLM_GROUNDED"
        missing_limitations = [
            item
            for item in policy_limitations
            if item.rstrip("。") not in answer
        ]
        if missing_limitations:
            answer += "\n\n说明：" + "；".join(missing_limitations)

    return (
        {
            **_base_payload(
                run_id=run_id,
                status=execution_status,
                mode=routing.mode.value,
                answer=answer,
                generation_method=generation_method,
            ),
            "result_items": result_items,
            "evidence_step_ids": evidence_step_ids,
            "pending_step_ids": pending_step_ids,
            "failure_code": failure_code,
            "business_validated": business_validated,
            "user_input_grounded": user_input_grounded,
            "external_write_executed": external_write_executed,
            "limitations": list(
                dict.fromkeys([*policy_limitations, *model_limitations])
            ),
            "generation_rejection_code": rejection_code,
        },
        usage,
    )


def _base_payload(
    *,
    run_id: str,
    status: str,
    mode: str,
    answer: str,
    generation_method: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "mode": mode,
        "answer": answer,
        "generation_method": generation_method,
        "result_items": [],
        "evidence_step_ids": [],
        "pending_step_ids": [],
        "failure_code": None,
        "business_validated": False,
        "user_input_grounded": False,
        "external_write_executed": False,
        "limitations": [],
        "generation_rejection_code": None,
    }


def _execution(
    langgraph_receipt: HandoffReceipt | None,
    system2_receipt: HandoffReceipt | None,
) -> Any:
    if langgraph_receipt is not None and langgraph_receipt.execution is not None:
        return langgraph_receipt.execution
    if system2_receipt is not None:
        return system2_receipt.execution
    return None


def _status_answer(
    *,
    execution_status: str,
    pending_goals: list[str],
    failure_code: str | None,
) -> str:
    if execution_status == "PARTIAL":
        pending = "；".join(dict.fromkeys(pending_goals)) or "当前待确认事项"
        return (
            f"任务已暂停，等待你的确认后继续。需要你确认：{pending}。"
            "当前结果已保存，确认前不会执行后续操作。"
        )
    if execution_status == "FAILED":
        return (
            "任务执行失败，未生成可交付的业务结论。"
            f"失败码：{failure_code or 'UNKNOWN_FAILURE'}。"
        )
    return "任务尚未执行，需要补充必要信息后再继续。"


def _policy_limitations(
    *,
    business_validated: bool,
    user_input_grounded: bool,
    external_write_executed: bool,
    external_write_requested: bool,
) -> list[str]:
    limitations: list[str] = []
    if not user_input_grounded:
        limitations.append(
            "部分资产使用演示样例输入，本次结果不能作为用户真实业务结论。"
        )
    if user_input_grounded and not business_validated:
        limitations.append(
            "该结果尚未通过独立业务校验，正式使用前请核对。"
        )
    if external_write_requested and not external_write_executed:
        limitations.append("本次运行未修改或提交外部业务系统。")
    return limitations


def _grounded_fallback_answer(
    *,
    task_context: TaskContext | None,
    result_items: list[dict[str, Any]],
    limitations: list[str],
) -> str:
    user_input_grounded = not any(
        "SAMPLE" in str(item.get("input_source", ""))
        for item in result_items
    )
    if not user_input_grounded:
        subject = (
            f"“{task_context.query[:120]}”"
            if task_context is not None
            else "你的问题"
        )
        return (
            f"我暂时无法根据本次执行可靠回答{subject}。系统命中的能力使用了"
            "演示样例，而不是与你问题对应的权威业务数据，因此我没有把样例结果"
            "作为真实结论返回。请补充完成该任务所需的实际数据，或允许系统读取"
            "对应的业务记录后再试。"
        )

    conclusions = [
        str(item["summary"]).strip()
        for item in _deduplicated_evidence(result_items)
        if str(item.get("summary", "")).strip()
    ]
    if conclusions:
        answer = "根据本次执行结果，" + "；".join(conclusions[:4]) + "。"
    else:
        answer = "任务已执行完成，但没有形成可直接交付的业务结论。"
    if limitations:
        answer += "\n\n说明：" + "；".join(limitations)
    return answer[:3000]


def _output_summary(output: dict[str, Any]) -> str:
    summary = output.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()[:800]
    return _naturalize_output(output)


def _naturalize_output(output: dict[str, Any]) -> str:
    """Project structured output into short business-language facts."""
    facts: list[str] = []
    if isinstance(output.get("intent_category"), str):
        facts.append(
            "识别为"
            + _display_value(output["intent_category"])
        )
    if isinstance(output.get("route_family"), str):
        facts.append(
            "建议进入"
            + _display_value(output["route_family"])
            + "流程"
        )
    if isinstance(output.get("risk_level"), str):
        facts.append(
            "风险等级为"
            + _display_value(output["risk_level"])
        )
    if isinstance(output.get("human_review_hint"), bool):
        facts.append(
            "建议人工复核"
            if output["human_review_hint"]
            else "暂未发现必须人工复核的信号"
        )
    if isinstance(output.get("human_review_required"), bool):
        facts.append(
            "需要人工复核"
            if output["human_review_required"]
            else "无需人工复核"
        )
    duplicate_groups = output.get("duplicate_groups")
    if isinstance(duplicate_groups, list):
        facts.append(f"发现{len(duplicate_groups)}组可能重复记录")
    violations = output.get("policy_violations")
    if isinstance(violations, list):
        facts.append(f"发现{len(violations)}项政策偏差")

    if not facts:
        for key, value in output.items():
            if key in {"entities", "evidence_refs", "facts"}:
                continue
            if isinstance(value, (str, int, float, bool)):
                label = _FIELD_LABELS.get(key, _readable_key(key))
                facts.append(f"{label}为{_display_value(value)}")
            if len(facts) >= 4:
                break
    if not facts and isinstance(output.get("facts"), dict):
        return _naturalize_output(output["facts"])
    return "，".join(dict.fromkeys(facts)) or "没有形成可展示的业务事实"


def _deduplicated_evidence(
    result_items: list[dict[str, Any]],
    *,
    grounded_only: bool = False,
) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in result_items:
        if grounded_only and "SAMPLE" in str(item.get("input_source", "")):
            continue
        summary = re.sub(r"\s+", " ", str(item.get("summary", ""))).strip()
        if not summary or summary in seen:
            continue
        seen.add(summary)
        unique.append(item)
    return unique


def _contains_machine_payload(answer: str) -> bool:
    return (
        "{" in answer
        or "}" in answer
        or bool(_INTERNAL_RESPONSE_MARKER.search(answer))
    )


def _capability_answer() -> str:
    return (
        "你好，我是一个在本地运行的企业任务 Agent。当前可以处理费用报销和企业"
        "运营预审、客服对话归类与调查、财务报告分析等任务；系统会优先复用已经"
        "验证的工具和流程，遇到新问题时再调用受预算约束的推理能力。需要人工决定"
        "的步骤会先暂停并等待确认，所有执行过程、状态和最终回复都会记录到 Trace"
        " 中供审查。你可以直接告诉我具体业务问题和可用数据。"
    )


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    return _VALUE_LABELS.get(str(value), str(value))


def _readable_key(key: str) -> str:
    return key.replace("_", " ")
