#!/usr/bin/env python3
"""Run one real user question through Control Plane, System2, and LangGraph."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from reduce_token_agent.application.facade import ApplicationFacade
from reduce_token_agent.domain.control import ControlPlatformResult
from reduce_token_agent.domain.task import TaskRequest


def main() -> int:
    args = parse_args()
    facade = ApplicationFacade(args.project_root.resolve())
    try:
        result = facade.plan_task(
            TaskRequest(
                query=args.question,
                tenant_id=args.tenant_id,
                principal_id=args.principal_id,
                scopes=args.scope,
                acceptance_criteria=args.acceptance,
            )
        )
    except Exception as exc:
        trace_match = re.search(r"trace_ref=(trace://\S+)", str(exc))
        _emit(
            {
                "event": "agent_task_failed",
                "status": "FAILED",
                "error": str(exc),
                "trace_ref": trace_match.group(1) if trace_match else None,
            }
        )
        return 1

    _print_compiled_flow(result)
    _print_task_state(result, event="agent_task_initial_state")

    while _execution_status(result) == "PARTIAL":
        pending = _pending_human_steps(result)
        if not pending:
            break
        if args.human_mode == "wait":
            _emit(
                {
                    "event": "agent_task_waiting_human",
                    "run_id": result.run_id,
                    "pending_step_ids": pending,
                    "trace_ref": result.trace_ref,
                }
            )
            return 2
        answers = _read_human_answers(result, pending)
        if answers is None:
            _emit(
                {
                    "event": "agent_task_waiting_human",
                    "run_id": result.run_id,
                    "pending_step_ids": pending,
                    "trace_ref": result.trace_ref,
                }
            )
            return 2
        result = facade.resume_human(result, human_answers=answers)
        _print_task_state(result, event="agent_task_resumed_state")

    final_response = result.structured_output.get("final_response") or {}
    print("\n=== 最终回复 ===")
    print(final_response.get("answer") or "没有生成可展示的最终回复。")
    print("\n=== 任务状态 ===")
    _emit(
        {
            "event": "agent_task_completed",
            "run_id": result.run_id,
            "mode": result.routing.mode.value,
            "status": _execution_status(result),
            "business_validated": final_response.get("business_validated"),
            "trace_ref": result.trace_ref,
        }
    )
    return 0 if _execution_status(result) == "SUCCEEDED" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", help="要交给本地 Agent 系统处理的真实业务问题")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--tenant-id", default="local")
    parser.add_argument("--principal-id", default="principal-a")
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument(
        "--human-mode",
        choices=("interactive", "wait"),
        default="interactive",
        help="interactive 在 HUMAN 节点等待终端输入；wait 保存 PARTIAL 后退出。",
    )
    return parser.parse_args()


def _print_compiled_flow(result: ControlPlatformResult) -> None:
    compiled = (
        result.compile_result.compiled_blueprint
        if result.compile_result is not None
        and result.compile_result.success
        else None
    )
    steps = []
    if compiled is not None:
        steps = [
            {
                "order": index,
                "step_id": step.step_id,
                "step_type": step.step_type.value,
                "goal": step.goal,
                "asset_ref": step.asset_ref,
                "depends_on": step.depends_on,
                "human_gate": step.human_gate,
                "reason_code": step.reason_code,
            }
            for index, step in enumerate(compiled.steps, start=1)
        ]
    print("\n=== 编译后的执行流程 ===")
    _emit(
        {
            "event": "compiled_execution_flow",
            "run_id": result.run_id,
            "blueprint_id": compiled.blueprint_id if compiled is not None else None,
            "compile_success": compiled is not None,
            "mode": result.routing.mode.value,
            "destinations": [
                destination.value
                for destination in result.routing.destinations
            ],
            "coverage": result.routing.coverage.model_dump(mode="json"),
            "steps": steps,
        }
    )


def _print_task_state(result: ControlPlatformResult, *, event: str) -> None:
    final_response = result.structured_output.get("final_response") or {}
    _emit(
        {
            "event": event,
            "run_id": result.run_id,
            "status": _execution_status(result),
            "mode": result.routing.mode.value,
            "pending_step_ids": final_response.get("pending_step_ids", []),
            "answer": final_response.get("answer"),
            "trace_ref": result.trace_ref,
        }
    )


def _read_human_answers(
    result: ControlPlatformResult,
    pending: list[str],
) -> dict[str, dict[str, Any]] | None:
    _emit(
        {
            "event": "human_input_required",
            "run_id": result.run_id,
            "pending_step_ids": pending,
            "instruction": (
                "请输入确认意见。可以输入普通文本，也可以输入 JSON，"
                '例如 {"confirmed": true, "decision": "按高风险处理"}。'
            ),
            "trace_ref": result.trace_ref,
        }
    )
    try:
        raw = input("人工确认> ").strip()
    except EOFError:
        return None
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {"confirmed": True, "decision": raw}
    if not isinstance(parsed, dict):
        parsed = {"confirmed": True, "decision": str(parsed)}
    parsed.setdefault("source", "interactive_user")
    return {step_id: dict(parsed) for step_id in pending}


def _pending_human_steps(result: ControlPlatformResult) -> list[str]:
    response = result.structured_output.get("final_response") or {}
    pending = response.get("pending_step_ids", [])
    if isinstance(pending, list) and pending:
        return [str(item) for item in pending]
    if result.proposal is None:
        return []
    return [
        step.step_id
        for step in result.proposal.steps
        if step.step_type.value == "HUMAN"
    ]


def _execution_status(result: ControlPlatformResult) -> str:
    return str(result.structured_output.get("execution_status", "UNKNOWN"))


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
