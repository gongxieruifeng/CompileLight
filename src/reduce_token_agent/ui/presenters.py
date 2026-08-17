"""Human-readable HTML projections for Blueprint, execution, and audit evidence."""

from __future__ import annotations

import html
import json
from typing import Any

from reduce_token_agent.application.view_models import TaskRunView

_KIND_LABELS = {
    "TOOL": "受控工具",
    "FSM": "FSM 能力",
    "VALIDATOR": "独立校验",
    "ADAPTER": "数据适配",
    "REASON": "System2 推理",
    "EXTRACT": "信息抽取",
    "HUMAN": "人工确认",
    "DM_DIRECT": "DM 机器人",
}
_STATUS_LABELS = {
    "SUCCEEDED": "已完成",
    "SUCCESS": "已完成",
    "FAILED": "失败",
    "PARTIAL": "等待继续",
    "WAITING_HUMAN": "等待人工",
    "WAITING_USER_INPUT": "等待用户",
    "PLACEHOLDER": "占位",
    "READY": "已编译",
}
_KEY_LABELS = {
    "receipts": "票据",
    "match_keys": "匹配字段",
    "lodging_items": "住宿明细",
    "policy_limits": "政策限额",
    "duplicate_groups": "重复票据组",
    "has_duplicates": "存在重复票据",
    "policy_violations": "政策偏差",
    "human_review_required": "需要人工复核",
    "route": "处理路由",
    "valid": "验证通过",
    "failure_codes": "失败码",
    "summary": "结论",
    "status": "状态",
    "capability_code": "命中能力",
    "conversation_action": "会话动作",
    "outbound_message_count": "机器人消息",
    "last_message_cursor": "消息游标",
    "waiting_user_input": "等待用户输入",
    "terminated": "对话已终止",
    "handoff_required": "需要转人工",
}


def render_task_flow(view: TaskRunView) -> str:
    """Render the actual runtime journey, keeping sequencing and dependency distinct."""
    steps = _blueprint_steps(view)
    if not steps and view.route == "DM_DIRECT":
        steps = [
            {
                "step_id": "dm_direct",
                "step_type": "DM_DIRECT",
                "goal": "Robot 353 直接处理单一客服目标",
                "asset_ref": "Robot Nexus · R8976-BVPYV",
                "depends_on": [],
            }
        ]
    if not steps:
        return _empty_panel(
            "任务流尚未形成",
            "执行后将在这里展示编译后的能力节点、依赖关系和验证状态。",
        )

    ordered = _ordered_runtime_steps(view, steps)
    cards: list[str] = []
    previous_step_id: str | None = None
    for index, (step, result) in enumerate(ordered, start=1):
        if index > 1:
            cards.append(_runtime_handoff(step, result, previous_step_id))
        cards.append(_journey_step(index=index, step=step, result=result))
        previous_step_id = str(step.get("step_id", result.get("step_id", "")))

    validated = "业务验证已通过" if view.business_validated else "业务验证待完成"
    terminal_class = "success" if view.status == "SUCCEEDED" else _status_class(view.status)
    return (
        '<section class="rta-flow-board">'
        '<div class="rta-flow-head">'
        '<div><span class="rta-kicker">ACTUAL EXECUTION JOURNEY</span>'
        "<h3>本次任务如何一步步完成</h3>"
        "<p>从上到下是实际运行顺序；每一步明确展示数据来源、执行能力、输出与验证。</p></div>"
        f'<div class="rta-flow-outcome"><span>{html.escape(view.mode)}</span>'
        f"<strong>{html.escape(validated)}</strong></div></div>"
        '<div class="rta-journey-start"><span>任务入口</span>'
        "<strong>用户目标与权威业务事实已完成规范化</strong>"
        "<small>箭头表示执行先后；是否使用上一步数据由连接说明明确标注。</small></div>"
        f'<div class="rta-journey">{"".join(cards)}</div>'
        f'<div class="rta-journey-finish status-{html.escape(terminal_class)}">'
        "<span>最终交付</span>"
        f"<strong>{html.escape(_STATUS_LABELS.get(view.status, view.status))}</strong>"
        f"<p>{html.escape(_truncate(view.answer, 220))}</p></div>"
        "</section>"
    )


def render_step_evidence(view: TaskRunView) -> str:
    """Render Blueprint dependencies as a secondary, non-runtime view."""
    steps = _blueprint_steps(view)
    results = _step_result_map(view)
    if not steps and not results:
        return _empty_panel("暂无 Blueprint", "任务编译后将显示步骤间的真实依赖关系。")
    if not steps:
        steps = list(results.values())
    cards: list[str] = []
    for index, step in enumerate(steps, start=1):
        step_id = str(step.get("step_id", f"step_{index}"))
        result = results.get(step_id, {})
        kind = str(step.get("step_type", result.get("step_type", "UNKNOWN")))
        status = str(result.get("status", "READY"))
        goal = str(step.get("goal", result.get("goal", step_id)))
        asset = str(step.get("asset_ref") or result.get("asset_ref") or "平台内置步骤")
        validation = str(result.get("validation_status", "NOT_RUN"))
        dependencies = [str(item) for item in step.get("depends_on", [])]
        dependency_label = "任务入口（无上游步骤）" if not dependencies else "、".join(dependencies)
        side_effect = str(step.get("side_effect", result.get("side_effect", "未声明")))
        cards.append(
            '<article class="rta-blueprint-card">'
            "<header>"
            f'<div class="rta-step-index">{index:02d}</div>'
            '<div class="rta-step-title">'
            f'<div><span class="rta-kind kind-{html.escape(kind.lower())}">'
            f"{html.escape(_KIND_LABELS.get(kind, kind))}</span>"
            f'<span class="rta-run-status status-{html.escape(_status_class(status))}">'
            f"{html.escape(_STATUS_LABELS.get(status, status))}</span></div>"
            f'<h4>{html.escape(goal)}</h4><code title="{html.escape(asset)}">'
            f"{html.escape(_compact_asset(asset))}</code></div>"
            '<div class="rta-validation">编译状态'
            f"<strong>{html.escape(_STATUS_LABELS.get(status, status))}</strong></div>"
            "</header>"
            '<div class="rta-blueprint-meta">'
            f"<div><span>依赖步骤</span><strong>{html.escape(dependency_label)}</strong></div>"
            f"<div><span>副作用级别</span><strong>{html.escape(side_effect)}</strong></div>"
            f"<div><span>运行验证</span><strong>{html.escape(validation)}</strong></div>"
            "</div>"
            "</article>"
        )
    return (
        '<section class="rta-blueprint-board">'
        '<div class="rta-blueprint-intro"><span class="rta-kicker">COMPILED BLUEPRINT</span>'
        "<h3>Blueprint 依赖说明</h3>"
        "<p>这里只说明编译关系。无依赖的步骤可以读取同一份任务事实，但不会伪造彼此的数据传递。</p></div>"
        '<div class="rta-step-list">' + "".join(cards) + "</div></section>"
    )


def render_audit_summary(view: TaskRunView) -> str:
    audit = view.audit
    execution = view.execution or {}
    total_tokens = int(audit.get("total_tokens", execution.get("total_tokens", 0)) or 0)
    event_count = audit.get("event_count", "—")
    steps = list(execution.get("step_results", []))
    succeeded = sum(1 for step in steps if step.get("status") in {"SUCCEEDED", "SUCCESS"})
    trace_id = str(audit.get("trace_id") or _trace_id(view.trace_ref) or "—")
    source = "持久化 Trace" if audit.get("source") == "PERSISTED_TRACE" else "当前运行"
    failure = view.failure_code or "无"
    stages = [str(item) for item in audit.get("stages", [])]
    stage_html = (
        "".join(
            f'<span class="rta-stage-chip">{html.escape(_stage_label(stage))}</span>'
            for stage in stages
        )
        or '<span class="rta-stage-chip muted">当前视图未展开阶段时间线</span>'
    )
    return (
        '<section class="rta-audit-board">'
        '<div class="rta-audit-grid">'
        f"{_audit_metric('Run ID', view.run_id)}"
        f"{_audit_metric('Trace 来源', source)}"
        f"{_audit_metric('完成步骤', f'{succeeded}/{len(steps)}')}"
        f"{_audit_metric('总 Token', str(total_tokens))}"
        f"{_audit_metric('结构化事件', str(event_count))}"
        f"{_audit_metric('失败码', failure)}"
        "</div>"
        '<div class="rta-audit-section"><div><span class="rta-kicker">AUDIT TRAIL</span>'
        "<h3>可追溯阶段</h3></div>"
        f'<div class="rta-stage-rail">{stage_html}</div></div>'
        '<div class="rta-governance-strip">'
        f"<span>Trace <strong>{html.escape(trace_id)}</strong></span>"
        "<span>业务验证 "
        f"<strong>{'PASS' if view.business_validated else 'NOT PASS'}</strong></span>"
        "<span>敏感数据 "
        f"<strong>{'已脱敏' if audit.get('redacted', True) else '需检查'}</strong></span>"
        "<span>思维链 <strong>不保存</strong></span>"
        "</div></section>"
    )


def _blueprint_steps(view: TaskRunView) -> list[dict[str, Any]]:
    if not isinstance(view.blueprint, dict):
        return []
    steps = view.blueprint.get("steps", [])
    return [step for step in steps if isinstance(step, dict)]


def _step_result_map(view: TaskRunView) -> dict[str, dict[str, Any]]:
    if not isinstance(view.execution, dict):
        return {}
    steps = view.execution.get("step_results", [])
    return {
        str(step["step_id"]): step
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("step_id"), str)
    }


def _ordered_runtime_steps(
    view: TaskRunView,
    blueprint_steps: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Prefer receipt order because it is the order the fixed executor actually ran."""
    blueprint_by_id = {
        str(step.get("step_id")): step
        for step in blueprint_steps
        if isinstance(step.get("step_id"), str)
    }
    runtime_steps = []
    if isinstance(view.execution, dict):
        runtime_steps = [
            item
            for item in view.execution.get("step_results", [])
            if isinstance(item, dict) and isinstance(item.get("step_id"), str)
        ]
    if runtime_steps:
        ordered = [
            (blueprint_by_id.get(str(result["step_id"]), result), result)
            for result in runtime_steps
        ]
        completed_ids = {str(result["step_id"]) for result in runtime_steps}
        ordered.extend(
            (step, {}) for step in blueprint_steps if str(step.get("step_id")) not in completed_ids
        )
        return ordered
    return [(step, {}) for step in blueprint_steps]


def _journey_step(
    *,
    index: int,
    step: dict[str, Any],
    result: dict[str, Any],
) -> str:
    step_id = str(step.get("step_id", result.get("step_id", f"step_{index}")))
    kind = str(step.get("step_type", result.get("step_type", "UNKNOWN")))
    status = str(result.get("status", "READY"))
    validation = str(result.get("validation_status", "NOT_RUN"))
    goal = str(step.get("goal", result.get("goal", step_id)))
    asset = str(step.get("asset_ref") or result.get("asset_ref") or "平台内置步骤")
    source = _source_label(str(result.get("input_source", "TASK_CONTEXT")))
    dependencies = [str(item) for item in step.get("depends_on", [])]
    dependency = "任务入口" if not dependencies else "、".join(dependencies)
    token_count = int(result.get("input_tokens", 0) or 0) + int(result.get("output_tokens", 0) or 0)
    token_label = f"{token_count} Token" if token_count else "确定性执行 / 未单独计费"
    validation_label = "业务 Validator" if kind == "VALIDATOR" else "输出 Contract"
    decision = result.get("decision_summary")
    decision_html = f'<p class="rta-decision">{html.escape(str(decision))}</p>' if decision else ""
    return (
        f'<article class="rta-journey-step kind-border-{html.escape(kind.lower())} '
        f'node-{html.escape(_status_class(status))}">'
        '<header class="rta-journey-step-head">'
        f'<div class="rta-step-index">{index:02d}</div>'
        '<div class="rta-step-title">'
        f'<div><span class="rta-kind kind-{html.escape(kind.lower())}">'
        f"{html.escape(_KIND_LABELS.get(kind, kind))}</span>"
        f'<span class="rta-run-status status-{html.escape(_status_class(status))}">'
        f"{html.escape(_STATUS_LABELS.get(status, status))}</span></div>"
        f"<h4>{html.escape(goal)}</h4>"
        f'<code title="{html.escape(asset)}">{html.escape(_compact_asset(asset))}</code>'
        "</div>"
        '<div class="rta-step-id"><span>STEP ID</span>'
        f"<strong>{html.escape(step_id)}</strong></div>"
        "</header>"
        '<div class="rta-data-lane">'
        '<section class="rta-lane-panel input">'
        '<div class="rta-lane-title"><span>01</span><strong>输入</strong></div>'
        f'<div class="rta-source-chip">来源 · {html.escape(source)}</div>'
        f"{_fact_list(result.get('input_summary', {}))}"
        f'<p class="rta-dependency">Blueprint 上游：{html.escape(dependency)}</p>'
        "</section>"
        '<div class="rta-lane-arrow" aria-hidden="true"><span>→</span></div>'
        '<section class="rta-lane-panel action">'
        '<div class="rta-lane-title"><span>02</span><strong>执行能力</strong></div>'
        f'<div class="rta-capability-icon">{html.escape(_kind_icon(kind))}</div>'
        f'<strong class="rta-capability-name">{html.escape(_KIND_LABELS.get(kind, kind))}</strong>'
        f'<code title="{html.escape(asset)}">{html.escape(_compact_asset(asset))}</code>'
        f"<small>{html.escape(token_label)}</small>"
        "</section>"
        '<div class="rta-lane-arrow" aria-hidden="true"><span>→</span></div>'
        '<section class="rta-lane-panel output">'
        '<div class="rta-lane-title"><span>03</span><strong>输出与验证</strong></div>'
        f"{_fact_list(result.get('output_summary', {}))}"
        f"{decision_html}"
        f'<div class="rta-validator-box validator-{html.escape(validation.lower())}">'
        f"<span>{validation_label}</span><strong>{html.escape(validation)}</strong></div>"
        "</section></div>"
        f"{_technical_payload(result.get('input_summary', {}), result.get('output_summary', {}))}"
        "</article>"
    )


def _runtime_handoff(
    step: dict[str, Any],
    result: dict[str, Any],
    previous_step_id: str | None,
) -> str:
    dependencies = [str(item) for item in step.get("depends_on", [])]
    kind = str(step.get("step_type", "UNKNOWN"))
    source = str(result.get("input_source", "")).upper()
    reads_dependency = "DEPENDENCY" in source or "BLUEPRINT_BINDINGS" in source
    if previous_step_id and previous_step_id in dependencies and reads_dependency:
        label = "校验上一步输出" if kind == "VALIDATOR" else "读取上一步已验证输出"
        detail = f"{previous_step_id} → {step.get('step_id', '下一步')}"
        css_class = "dependent"
    elif dependencies and reads_dependency:
        label = "读取指定上游的已验证输出"
        detail = "、".join(dependencies)
        css_class = "dependent"
    elif dependencies:
        label = "等待上游完成后，读取任务事实"
        detail = f"执行依赖：{'、'.join(dependencies)}；本步没有消费其输出"
        css_class = "ordered"
    else:
        label = "独立读取权威任务事实"
        detail = "与上一步只有执行先后关系，没有数据依赖"
        css_class = "independent"
    return (
        f'<div class="rta-handoff {css_class}"><i></i><div><strong>{html.escape(label)}</strong>'
        f"<span>{html.escape(detail)}</span></div></div>"
    )


def _source_label(value: str) -> str:
    normalized = value.upper()
    if "SAMPLE" in normalized:
        return "资产演示样例（非真实业务事实）"
    return {
        "AUTHORITATIVE_TASK_ENTITIES": "权威任务事实",
        "TASK_CONTEXT": "规范化任务上下文",
        "TASK_CONTEXT_DM_TURN": "本轮用户消息",
        "DEPENDENCY_OUTPUT": "上游步骤输出",
        "DEPENDENCY_OUTPUT_DIRECT": "上游步骤类型化输出",
        "BLUEPRINT_BINDINGS": "Blueprint 指定数据绑定",
        "BLUEPRINT_BINDINGS_WITH_SAMPLE_DEFAULTS": "Blueprint 绑定与样例默认值",
        "USER_INPUT_DM_RESUME": "用户补充消息",
        "SYSTEM2_EXECUTOR": "System2 补齐结果",
        "SYSTEM2_FROZEN_CONTEXT": "System2 冻结上下文",
        "LIGHTWEIGHT_DETERMINISTIC": "轻量确定性逻辑",
        "PERSISTED_TRACE": "历史 Trace 安全摘要",
    }.get(normalized, value.replace("_", " ").title())


def _kind_icon(kind: str) -> str:
    return {
        "TOOL": "⌁",
        "FSM": "◇",
        "VALIDATOR": "✓",
        "ADAPTER": "↔",
        "REASON": "✦",
        "EXTRACT": "⌕",
        "HUMAN": "人",
        "DM_DIRECT": "DM",
    }.get(kind, "◆")


def _flow_terminal(title: str, subtitle: str, css_class: str, number: str) -> str:
    return (
        f'<div class="rta-flow-node terminal {css_class}">'
        f'<span class="rta-node-number">{number}</span>'
        f'<div class="rta-node-icon">{"✓" if css_class == "finish" else "◆"}</div>'
        f"<h4>{html.escape(title)}</h4><p>{html.escape(subtitle)}</p></div>"
    )


def _flow_node(
    *,
    index: int,
    kind: str,
    status: str,
    validation: str,
    goal: str,
    asset_ref: str,
    dependencies: list[str],
) -> str:
    dependency = " · ".join(dependencies) if dependencies else "入口就绪"
    return (
        f'<div class="rta-flow-node kind-border-{html.escape(kind.lower())} '
        f'node-{html.escape(_status_class(status))}">'
        f'<span class="rta-node-number">{index:02d}</span>'
        '<div class="rta-node-top">'
        f'<span class="rta-kind kind-{html.escape(kind.lower())}">'
        f"{html.escape(_KIND_LABELS.get(kind, kind))}</span>"
        f'<span class="rta-node-status">{html.escape(_STATUS_LABELS.get(status, status))}</span>'
        "</div>"
        f"<h4>{html.escape(goal)}</h4>"
        f'<code title="{html.escape(asset_ref)}">{html.escape(_compact_asset(asset_ref))}</code>'
        '<div class="rta-node-meta">'
        f'<span title="依赖">↳ {html.escape(dependency)}</span>'
        f'<strong class="validator-{html.escape(validation.lower())}">'
        f"✓ {html.escape(validation)}</strong>"
        "</div></div>"
    )


def _fact_list(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return '<p class="rta-empty-copy">暂无可展示信息</p>'
    rows: list[str] = []
    for key, item in list(value.items())[:8]:
        rows.append(
            '<div class="rta-fact-row">'
            f"<span>{html.escape(_KEY_LABELS.get(str(key), _readable_key(str(key))))}</span>"
            f"<strong>{html.escape(_display_value(item))}</strong></div>"
        )
    return '<div class="rta-facts">' + "".join(rows) + "</div>"


def _technical_payload(input_summary: Any, output_summary: Any) -> str:
    payload = json.dumps(
        {"input": input_summary, "output": output_summary},
        ensure_ascii=False,
        indent=2,
    )
    return (
        '<details class="rta-tech-detail"><summary>查看完整技术载荷</summary>'
        f"<pre>{html.escape(payload)}</pre></details>"
    )


def _display_value(value: Any) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list):
        if not value:
            return "无"
        if all(isinstance(item, (str, int, float)) for item in value):
            return "、".join(str(item) for item in value[:5])
        return f"{len(value)} 项记录"
    if isinstance(value, dict):
        if set(value).issubset({"CN-SH", "CN-BJ", "DEFAULT"}):
            return "，".join(f"{key}: {item}" for key, item in value.items())
        return f"{len(value)} 个字段"
    return str(value)


def _compact_asset(value: str) -> str:
    if value == "平台内置步骤" or value.startswith("Robot Nexus"):
        return value
    base = value.split("@", 1)[0]
    parts = base.split(".")
    short = ".".join(parts[-3:])
    version = "@" + value.split("@", 1)[1] if "@" in value else ""
    return short + version


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _status_class(status: str) -> str:
    if status in {"SUCCEEDED", "SUCCESS"}:
        return "success"
    if status == "FAILED":
        return "failed"
    if status.startswith("WAITING") or status == "PARTIAL":
        return "waiting"
    return "ready"


def _audit_metric(label: str, value: str) -> str:
    return (
        '<div class="rta-audit-metric">'
        f'<span>{html.escape(label)}</span><strong title="{html.escape(value)}">'
        f"{html.escape(value)}</strong></div>"
    )


def _trace_id(trace_ref: str | None) -> str | None:
    if not trace_ref:
        return None
    return trace_ref.split("?", 1)[0].removeprefix("trace://")


def _stage_label(value: str) -> str:
    return {
        "normalize": "规范化",
        "decompose": "任务拆分",
        "retrieve_initial": "混合召回",
        "sad_align": "SAD 对齐",
        "contract_rerank": "Contract 重排",
        "plan_repair": "计划修复",
        "system2": "System2",
        "system2_reason": "局部推理",
        "execution": "LangGraph 执行",
        "langgraph_execution": "执行用量",
        "route_guard": "安全门禁",
        "final_response": "最终答复",
        "dm_discovery": "DM 发现",
        "dm_direct_gate": "DM 门禁",
        "dm_runtime": "DM 执行",
    }.get(value, _readable_key(value))


def _readable_key(value: str) -> str:
    return value.replace("_", " ")


def _empty_panel(title: str, copy: str) -> str:
    return (
        '<div class="rta-empty-panel"><span>◇</span>'
        f"<h3>{html.escape(title)}</h3><p>{html.escape(copy)}</p></div>"
    )
