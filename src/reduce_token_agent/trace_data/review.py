"""Human-readable review reports for real runtime traces."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from reduce_token_agent.trace_data.runtime_models import RuntimeTraceEnvelope


class RuntimeTraceReviewWriter:
    """Write one stable JSON review projection and one detailed Markdown report."""

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def write(self, envelope: RuntimeTraceEnvelope) -> tuple[Path, Path]:
        trace_dir = self.output_root / envelope.trace_id
        trace_dir.mkdir(parents=True, exist_ok=True)
        json_path = trace_dir / "TRACE_REVIEW.json"
        markdown_path = trace_dir / "TRACE_REVIEW.md"
        _atomic_write(
            json_path,
            json.dumps(
                envelope.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        _atomic_write(markdown_path, render_markdown(envelope))
        return markdown_path, json_path


def render_markdown(trace: RuntimeTraceEnvelope) -> str:
    """Render a review-first report with data-flow and blueprint evolution."""
    outcome = trace.outcome
    extraction = trace.extraction_evidence
    eligible = trace.governance.eligible_for_candidate_extraction
    lines = [
        f"# Runtime Trace 审查报告：`{trace.trace_id}`",
        "",
        f"- Run ID：`{trace.run_id}`",
        f"- Schema：`{trace.schema_version}`",
        f"- 运行状态：`{outcome.status}`",
        f"- 控制模式：`{outcome.mode or 'UNSET'}`",
        f"- 业务执行状态：`{outcome.execution_status}`",
        f"- 业务验证通过：`{str(outcome.business_validated).lower()}`",
        f"- 可进入资产候选抽取：`{str(eligible).lower()}`",
        f"- 候选资格：`{extraction.candidate_hint_status}`",
        "",
        "## 1. 审查结论",
        "",
        outcome.summary,
        "",
    ]
    if not eligible:
        lines.extend(
            [
                "> 当前 Trace 可以用于运行审计、失败分析和候选边界研究，但不能直接",
                "> 证明新资产具备可执行性。只有真实执行完成且独立 Validator 通过的",
                "> Trace 才能进入 SOP 的候选抽取阶段；进入后仍只能生成 DRAFT。",
                "",
            ]
        )
    lines.extend(
        [
            "## 2. 任务与安全上下文",
            "",
            "| 字段 | 内容 |",
            "| --- | --- |",
            f"| Task ID | `{trace.task.task_id or 'UNSET'}` |",
            f"| Tenant | `{trace.task.tenant_id or 'UNSET'}` |",
            f"| Principal | `{trace.task.principal_ref}` |",
            f"| Domain | {_cell(', '.join(trace.task.domains) or 'UNSET')} |",
            f"| Data Classification | `{trace.task.data_classification or 'UNSET'}` |",
            f"| Risk | `{trace.task.risk_level or 'UNSET'}` |",
            f"| 安全任务摘要 | {_cell(trace.task.query_preview)} |",
            f"| 验收条件 | {_cell('；'.join(trace.task.acceptance_criteria) or '无')} |",
            "",
            "身份只保存摘要引用；敏感键、邮箱和长号码在写入前脱敏；不保存完整思维链。",
            "",
            "## 3. 结果与失败原因",
            "",
            f"- Destinations：`{', '.join(outcome.destinations) or 'NONE'}`",
            f"- Failed Stage：`{outcome.failed_stage or 'NONE'}`",
            f"- Failure Codes：`{', '.join(outcome.failure_codes) or 'NONE'}`",
            f"- Repair Attempts：`{trace.plan.repair_attempts}`",
            "",
            "## 3.1 Token 消耗",
            "",
            *_render_token_usage(trace),
            "",
            "## 3.2 最终用户回复",
            "",
            *_render_final_response(trace),
            "",
            "## 4. 运行时间线",
            "",
            "| # | Stage | Event | 状态 | Failure Codes | Asset Refs | 时间 |",
            "| ---: | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for event in trace.timeline:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(event.sequence),
                    _cell(event.stage),
                    _cell(event.event_type),
                    event.status,
                    _cell(", ".join(event.failure_codes) or "-"),
                    _cell(", ".join(event.asset_refs) or "-"),
                    event.created_at.isoformat(),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 5. Blueprint 与编译",
            "",
            "### 5.0 粗拆初始图（SAD 前）",
            "",
            *_render_coarse_graph(trace),
            "",
            "### 5.1 SAD 后的候选图",
            "",
            *_render_sad_graph(trace),
            "",
            "### 5.2 Blueprint 演化与编译尝试",
            "",
            *_render_blueprint_history(trace),
            "",
            "### 5.3 最终 Blueprint 结构",
            "",
            *_render_blueprint_structure(trace),
            "",
            "### 5.4 Registry View",
            "",
            _json_block(trace.plan.registry_view),
            "",
            "### 5.5 最终 Proposal",
            "",
            _json_block(trace.plan.proposal),
            "",
            "### 5.6 最终 Compile Result",
            "",
            _json_block(trace.plan.compile_result),
            "",
            "## 6. 阶段输入/输出数据流",
            "",
            *_render_stage_dataflow(trace),
            "",
            "## 7. 执行平台步骤输入/输出",
            "",
            *_render_execution_steps(trace),
            "",
            "## 8. 资产抽取证据投影",
            "",
            f"- Observed Assets：`{', '.join(extraction.observed_asset_refs) or 'NONE'}`",
            f"- Validated Assets：`{', '.join(extraction.validated_asset_refs) or 'NONE'}`",
            f"- Successful Stages：`{', '.join(extraction.successful_stages) or 'NONE'}`",
            f"- Failed Stages：`{', '.join(extraction.failed_stages) or 'NONE'}`",
            f"- Quality Flags：`{', '.join(extraction.quality_flags) or 'NONE'}`",
            "",
            "SOP 后台程序必须只把 `validated_asset_refs` 和对应成功执行/Validator 证据",
            "作为可抽取输入。`observed_asset_refs` 仅表示规划或运行中出现过，不能证明可用。",
            "",
            "## 9. 完整结构化事件",
            "",
        ]
    )
    for event in trace.timeline:
        lines.extend(
            [
                f"### {event.sequence}. `{event.stage}/{event.event_type}`",
                "",
                _json_block(event.payload),
                "",
            ]
        )
    lines.extend(
        [
            "## 10. Governance",
            "",
            _json_block(trace.governance.model_dump(mode="json")),
            "",
        ]
    )
    return "\n".join(lines)


def _render_final_response(trace: RuntimeTraceEnvelope) -> list[str]:
    responses = [
        event.payload
        for event in trace.timeline
        if event.stage == "final_response"
        and event.event_type == "completed"
    ]
    if not responses:
        return ["> 当前 Trace 没有记录最终用户回复。"]
    latest = responses[-1]
    answer = latest.get("answer")
    return [
        f"- 生成方式：`{latest.get('generation_method', 'UNKNOWN')}`",
        f"- 用户输入已落到执行参数：`{latest.get('user_input_grounded', 'UNKNOWN')}`",
        f"- 执行了外部写操作：`{latest.get('external_write_executed', 'UNKNOWN')}`",
        f"- 业务验证通过：`{latest.get('business_validated', 'UNKNOWN')}`",
        f"- Evidence Step IDs：`{', '.join(latest.get('evidence_step_ids', [])) or 'NONE'}`",
        f"- 限制：{_cell('；'.join(latest.get('limitations', [])) or '无')}",
        "",
        str(answer) if isinstance(answer, str) else "未生成文本回复。",
        "",
        "结构化回复：",
        _json_block(latest),
    ]


def _render_stage_dataflow(trace: RuntimeTraceEnvelope) -> list[str]:
    """Show what each control stage consumed and emitted without CoT."""
    lines = [
        "下面的“输入”是 Trace 中可确认的输入来源或字段摘要；未持久化的",
        "LLM 请求体会明确标注为“未保存”，不会用推断内容冒充真实输入。",
        "",
        "| # | 阶段 | 输入来源/关键数据 | 输出数据 | 状态 |",
        "| ---: | --- | --- | --- | --- |",
    ]
    meaningful = [
        event for event in trace.timeline if event.event_type != "llm_usage"
    ]
    for event in meaningful:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(event.sequence),
                    _cell(event.stage),
                    _cell(_stage_input_summary(trace, event)),
                    _cell(_payload_summary(event.payload)),
                    event.status,
                ]
            )
            + " |"
        )
    lines.append("")
    for event in meaningful:
        lines.extend(
            [
                f"#### {event.sequence}. `{event.stage}/{event.event_type}` 的数据",
                "",
                f"- 输入：{_stage_input_summary(trace, event)}",
                f"- 输出：{_payload_summary(event.payload)}",
                "",
                "输入数据（可还原部分）：",
                _json_block(_stage_input_payload(trace, event)),
                "",
                "输出数据：",
                _json_block(event.payload),
                "",
            ]
        )
    return lines


def _render_token_usage(trace: RuntimeTraceEnvelope) -> list[str]:
    usage_events = [
        event
        for event in trace.timeline
        if event.event_type == "llm_usage"
    ]
    if not usage_events:
        return ["> 当前 Trace 没有 LLM 用量事件。"]
    lines = [
        "以下是 Trace 中实际记录的结构化模型用量。`input_tokens` 与",
        "`output_tokens` 是每个阶段最后一次成功/兼容调用返回的计数；",
        "如果该阶段发生格式重试，`attempts` 会显示次数，但旧版本没有逐次",
        "保存每次失败尝试的 token 计数，因此合计可能是保守下界。",
        "",
        "| 阶段 | 模型 | Attempts | Input Tokens | Output Tokens | Recorded Total | 状态 |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    total_input = 0
    total_output = 0
    known_input = True
    known_output = True
    for event in usage_events:
        payload = event.payload
        input_tokens = _numeric_usage(payload.get("input_tokens"))
        output_tokens = _numeric_usage(payload.get("output_tokens"))
        total_duration = _numeric_usage(payload.get("total_duration_ns"))
        if input_tokens is None:
            known_input = False
        else:
            total_input += input_tokens
        if output_tokens is None:
            known_output = False
        else:
            total_output += output_tokens
        recorded_total = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{event.stage}`",
                    _cell(str(payload.get("model", "-"))),
                    str(payload.get("attempts", "-")),
                    _count_cell(input_tokens, payload.get("input_tokens")),
                    _count_cell(output_tokens, payload.get("output_tokens")),
                    _count_cell(recorded_total, recorded_total),
                    (
                        f"{event.status}; duration_ns={total_duration}"
                        if total_duration is not None
                        else event.status
                    ),
                ]
            )
            + " |"
        )
    total_label = (
        f"{total_input + total_output} "
        f"(input={total_input}, output={total_output})"
        if known_input and known_output
        else "UNAVAILABLE_REDACTED"
    )
    lines.extend(
        [
            "",
            f"- 本次 Trace 记录的总 token：`{total_label}`",
            (
                "- 统计状态：完整"
                if known_input and known_output
                else "- 统计状态：部分字段已在历史 Trace 落盘时脱敏，无法从当前文件恢复"
            ),
        ]
    )
    return lines


def _numeric_usage(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _count_cell(number: int | None, raw: Any) -> str:
    if number is not None:
        return str(number)
    if raw == "[REDACTED]":
        return "REDACTED"
    return "UNAVAILABLE"


def _stage_input_summary(trace: RuntimeTraceEnvelope, event: Any) -> str:
    stage = event.stage
    if stage == "normalize":
        return (
            "TaskRequest.query、tenant_id、principal_id、scopes、"
            "environment、时间基准（调用身份按摘要引用保存）"
        )
    if stage == "decompose":
        return "Normalize 输出的 TaskContext（实体、领域、验收条件、风险）"
    if stage == "retrieve_initial":
        return (
            "TaskContext + 粗拆子目标；按 tenant/ACL/environment/"
            "data_classification/risk 进行硬过滤"
        )
    if stage == "sad_align":
        return (
            "粗拆子目标 + Initial Retrieval 的 Header/Contract 摘要；"
            "本 Trace 未保存完整 LLM 请求副本"
        )
    if stage == "contract_rerank":
        return (
            "SAD 对齐子目标 + 每个子目标的二次召回结果；"
            "Contract、Runtime Binding 和 Capability Graph"
        )
    if stage in {"plan_propose", "plan_repair"}:
        return (
            "SAD 对齐结果 + Rerank 候选白名单 + Registry View + Blueprint Budget；"
            "本 Trace 只保存模型用量，不保存完整 Prompt"
        )
    if stage == "route_guard":
        return "Proposal、CompileResult、ModeRouter 路由结果和 Handoff 回执"
    if stage == "execution":
        return "LangGraph/System2 执行器触发条件、上游 Artifact 和绑定参数"
    return "前一阶段成功输出（具体输入未单独持久化）"


def _stage_input_payload(trace: RuntimeTraceEnvelope, event: Any) -> dict[str, Any]:
    """Reconstruct only input data that is actually present in the trace."""
    events = trace.timeline

    def completed(stage: str) -> dict[str, Any]:
        match = next(
            (
                item
                for item in events
                if item.stage == stage and item.event_type == "completed"
            ),
            None,
        )
        return match.payload if match is not None else {}

    if event.stage == "normalize":
        return trace.task.model_dump(mode="json")
    if event.stage == "decompose":
        return completed("normalize")
    if event.stage == "retrieve_initial":
        return {
            "normalized_task": completed("normalize"),
            "coarse_subgoals": completed("decompose").get("subgoals", []),
        }
    if event.stage == "sad_align":
        return {
            "coarse_subgoals": completed("decompose").get("subgoals", []),
            "initial_retrieval_candidates": completed("retrieve_initial").get(
                "candidates", []
            ),
            "note": "完整 SAD Prompt 未保存",
        }
    if event.stage == "contract_rerank":
        return {
            "sad_alignment": completed("sad_align"),
            "note": "每个 SAD 子目标的二次召回原始结果未单独写入事件；"
            "Rerank 输出见当前事件",
        }
    if event.stage in {"plan_propose", "plan_repair"}:
        return {
            "sad_alignment": completed("sad_align"),
            "reranked_candidates": completed("contract_rerank"),
            "registry_view": trace.plan.registry_view,
            "note": "完整 Blueprint Prompt 未保存",
        }
    if event.stage == "route_guard":
        return {
            "proposal": trace.plan.proposal,
            "compile_result": trace.plan.compile_result,
        }
    if event.stage == "execution":
        payload = dict(event.payload)
        return {
            "input_refs": payload.get("input_refs", []),
            "input_safe_summary": payload.get("input_safe_summary", {}),
            "asset_ref": payload.get("asset_ref"),
            "validator_ref": payload.get("validator_ref"),
        }
    return {"note": "该阶段输入未单独持久化"}


def _payload_summary(payload: Any) -> str:
    if not payload:
        return "空对象"
    if not isinstance(payload, dict):
        return str(payload)[:120]
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, list):
            parts.append(f"{key}[{len(value)}]")
        elif isinstance(value, dict):
            parts.append(f"{key}{{{len(value)} fields}}")
        else:
            text = str(value)
            parts.append(f"{key}={text[:80]}")
    return "；".join(parts[:10])


def _render_execution_steps(trace: RuntimeTraceEnvelope) -> list[str]:
    events = [
        event
        for event in trace.timeline
        if event.stage == "execution"
        and event.event_type
        in {"step_started", "step_succeeded", "step_failed", "step_waiting_human"}
    ]
    if not events:
        return [
            "> 当前 Trace 没有执行平台步骤事件。控制平台已完成规划和交接，",
            "> 但 LangGraph/System2 仍是占位实现，因此没有真实的 Step 输入、输出、",
            "> Validator 结果或业务 Artifact。该状态不会被判定为资产执行成功。",
        ]
    lines = [
        "| 事件 | Step | Executor | Asset | 输入摘要 | 输出摘要 | 验证资产 | "
        "验证 | Tokens | Duration(ns) | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for event in events:
        payload = event.payload
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{event.event_type}`",
                    f"`{payload.get('step_id', '-')}`",
                    str(payload.get("executor_kind", "-")),
                    _cell(str(payload.get("asset_ref") or "-")),
                    _cell(_payload_summary(payload.get("input_safe_summary", {}))),
                    _cell(_payload_summary(payload.get("output_safe_summary", {}))),
                    _cell(
                        ", ".join(payload.get("validated_asset_refs", [])) or "-"
                    ),
                    str(payload.get("validation_status", "-")),
                    str(
                        int(payload.get("input_tokens", 0))
                        + int(payload.get("output_tokens", 0))
                    ),
                    str(payload.get("duration_ns", 0)),
                    event.status,
                ]
            )
            + " |"
        )
    lines.extend(["", "### 执行步骤完整安全摘要", ""])
    for event in events:
        lines.extend(
            [
                f"#### `{event.payload.get('step_id', 'UNKNOWN')}` / `{event.event_type}`",
                "",
                _json_block(event.payload),
                "",
            ]
        )
    return lines


def _render_sad_graph(trace: RuntimeTraceEnvelope) -> list[str]:
    alignment_event = next(
        (
            event
            for event in trace.timeline
            if event.stage == "sad_align" and event.event_type == "completed"
        ),
        None,
    )
    rerank_event = next(
        (
            event
            for event in trace.timeline
            if event.stage == "contract_rerank" and event.event_type == "completed"
        ),
        None,
    )
    if alignment_event is None:
        return ["> 未找到 SAD 完成事件。"]
    aligned = alignment_event.payload.get("aligned_subgoals", [])
    lines = [
        "SAD 输出保留的子目标与候选能力边界如下：",
        "",
        "| 子目标 | SAD 状态 | Covered Hints | Rerank 主候选 | Graph Validator/Adapter |",
        "| --- | --- | --- | --- | --- |",
    ]
    candidate_sets = {
        item.get("subgoal", {}).get("subgoal_id"): item
        for item in (rerank_event.payload.get("candidate_sets", []) if rerank_event else [])
    }
    for item in aligned:
        subgoal_id = str(item.get("subgoal_id", "-"))
        candidate_set = candidate_sets.get(subgoal_id, {})
        primary = [
            str(candidate.get("candidate", {}).get("asset_ref", "-"))
            for candidate in candidate_set.get("primary", [])
        ]
        closure = [
            str(candidate.get("candidate", {}).get("asset_ref", "-"))
            for candidate in candidate_set.get("graph_closure", [])
        ]
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{subgoal_id}`",
                    f"{item.get('alignment_code', '-')} / "
                    f"uncovered={str(item.get('uncovered', False)).lower()}",
                    _cell(", ".join(item.get("covered_hint_refs", [])) or "-"),
                    _cell(", ".join(primary) or "-"),
                    _cell(", ".join(closure) or "-"),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "```mermaid",
            "graph TD",
        ]
    )
    for index, item in enumerate(aligned, start=1):
        subgoal_id = str(item.get("subgoal_id", f"subgoal_{index}"))
        node_id = f"sg_{index}"
        label = _mermaid_label(
            f"{subgoal_id}\\n{item.get('alignment_code', '-')}"
        )
        lines.append(f'  {node_id}["{label}"]')
        candidate_set = candidate_sets.get(subgoal_id, {})
        for asset_index, candidate in enumerate(
            candidate_set.get("primary", []), start=1
        ):
            asset_ref = str(candidate.get("candidate", {}).get("asset_ref", "-"))
            asset_node = f"{node_id}_a{asset_index}"
            lines.append(f'  {asset_node}["{_mermaid_label(asset_ref)}"]')
            lines.append(f"  {node_id} --> {asset_node}")
    lines.extend(["```", ""])
    return lines


def _render_coarse_graph(trace: RuntimeTraceEnvelope) -> list[str]:
    event = next(
        (
            item
            for item in trace.timeline
            if item.stage == "decompose" and item.event_type == "completed"
        ),
        None,
    )
    if event is None:
        return ["> 未找到粗拆完成事件。"]
    subgoals = event.payload.get("subgoals", [])
    if not subgoals:
        return ["> 粗拆没有产生子目标。"]
    lines = [
        "| 子目标 | 目标 | 期望中间状态 | 验收条件 |",
        "| --- | --- | --- | --- |",
    ]
    for item in subgoals:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{item.get('subgoal_id', '-')}`",
                    _cell(str(item.get("goal", "-"))),
                    _cell(str(item.get("expected_state", "-"))),
                    _cell("；".join(item.get("acceptance_criteria", [])) or "-"),
                ]
            )
            + " |"
        )
    lines.extend(["", "```mermaid", "graph TD"])
    for index, item in enumerate(subgoals, start=1):
        node_id = f"coarse_{index}"
        label = _mermaid_label(
            f"{item.get('subgoal_id', node_id)}\\n{item.get('goal', '-')}"
        )
        lines.append(f'  {node_id}["{label}"]')
        if index > 1:
            lines.append(f"  coarse_{index - 1} -.-> {node_id}")
    lines.extend(["```", ""])
    return lines


def _render_blueprint_history(trace: RuntimeTraceEnvelope) -> list[str]:
    proposal = trace.plan.proposal
    compile_result = trace.plan.compile_result
    if proposal is None and compile_result is None:
        return [
            "#### 第一次提议/编译",
            "",
            "> 当前 Trace 没有 Blueprint Proposal/Compile 记录。",
        ]
    lines: list[str] = []
    blueprint_events = [
        event
        for event in trace.timeline
        if event.stage in {"blueprint", "compile"}
        or "proposal" in event.payload
        or "compile_result" in event.payload
    ]
    if trace.plan.repair_attempts:
        lines.extend(
            [
                "#### 第一次提议/编译",
                "",
                "> 该 Trace 的数据库投影只保留最终 Proposal 与 CompileResult，",
                "> 没有保存第一次提议的完整 JSON，因此不能从事后报告还原第一版图。",
                "> 下方会明确展示可确认的修复次数、最终提议和编译结果，不伪造第一版内容。",
                "",
            ]
        )
    else:
        lines.extend(["#### 第一次提议/编译", "", "本次未发生修复尝试。", ""])
    if blueprint_events:
        lines.extend(["#### Trace 中记录的 Blueprint 事件", ""])
        for event in blueprint_events:
            lines.extend(
                [
                    f"- `{event.sequence} {event.stage}/{event.event_type}`："
                    f"{_payload_summary(event.payload)}",
                ]
            )
        lines.append("")
    lines.extend(
        [
            f"- `repair_attempts={trace.plan.repair_attempts}`",
            "- 最终 Proposal：见下方“5.5 最终 Proposal”。",
            "- 最终 CompileResult：见下方“5.6 最终 Compile Result”。",
        ]
    )
    return lines


def _render_blueprint_structure(trace: RuntimeTraceEnvelope) -> list[str]:
    compile_result = trace.plan.compile_result or {}
    compiled = compile_result.get("compiled_blueprint")
    proposal = trace.plan.proposal or {}
    steps = (
        compiled.get("steps", [])
        if isinstance(compiled, dict)
        else proposal.get("steps", [])
    )
    if not steps:
        return ["> 没有可展示的 Blueprint Step。"]
    lines = [
        "| Step | Subgoal | 类型 | Asset | Depends On | 副作用 | Reason |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for step in steps:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{step.get('step_id', '-')}`",
                    f"`{step.get('subgoal_id', '-')}`",
                    str(step.get("step_type", "-")),
                    _cell(str(step.get("asset_ref") or "-")),
                    _cell(", ".join(step.get("depends_on", [])) or "-"),
                    str(step.get("side_effect", "-")),
                    _cell(str(step.get("reason_code", "-"))),
                ]
            )
            + " |"
        )
    lines.extend(["", "```mermaid", "graph TD"])
    for step in steps:
        step_id = str(step.get("step_id", "step_unknown"))
        label = _mermaid_label(
            f"{step_id}\\n{step.get('step_type', '-')}"
            f"\\n{step.get('asset_ref') or step.get('reason_code', '-')}"
        )
        lines.append(f'  {step_id}["{label}"]')
    for step in steps:
        for dependency in step.get("depends_on", []):
            lines.append(f"  {dependency} --> {step.get('step_id')}")
    lines.extend(["```", ""])
    return lines


def _mermaid_label(value: str) -> str:
    return value.replace('"', "'").replace("\n", " ")[:180]


def _json_block(value: Any) -> str:
    return (
        "```json\n"
        + json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n```"
    )


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)
