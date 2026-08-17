"""Ollama-backed synthetic trace generator with validation and resumability."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import ollama
from pydantic import ValidationError

from reduce_token_agent.trace_data.catalog import ScenarioSpec
from reduce_token_agent.trace_data.models import (
    AssetKind,
    GeneratedTrace,
    GenerationProvenance,
    ScenarioRequirements,
    SyntheticTraceEnvelope,
    TraceGovernance,
)

SYSTEM_PROMPT = """你是企业 Agent Trace 数据生成器。
你必须生成完全虚构、可验证、结构化的中文任务执行 Trace。

硬约束：
1. 所有公司、人员、账户、合同、交易和金额均为合成示例，不得使用真实个人数据。
2. 不输出或保存思维链。decision_summary 只能写简短的证据化结论，reason_code 必须是稳定枚举式代码。
3. Trace 是原始合成经验，不是已批准资产。所有 candidate_assets.status 必须为 DRAFT。
4. 每个步骤都要明确输入/输出契约、证据、验证、失败码、后继和副作用。
5. 涉及金融、合规、权限或法律判断时，保留 Validator、Policy 或 Human Gate，
   不得把模型判断描述为最终授权。
6. candidate_assets 要便于后续抽离 Tool、FSM、Extractor、Adapter、Validator、
   Contract、Policy 或 Skeleton；候选边界应小而稳定。
7. 只返回符合 JSON Schema 的 JSON，不添加 Markdown、解释或额外字段。
"""

OUTPUT_SHAPE = """
输出必须严格使用以下字段结构。数组内的对象都必须包含列出的全部字段：
{
  "scenario_id": "与输入完全一致",
  "domain": "与输入完全一致",
  "task_family": "与输入完全一致",
  "task": {
    "title": "...", "user_request": "...", "objective": "...",
    "expected_mode": "REUSE|HYBRID|NEW|CLARIFY",
    "risk_level": "low|medium|high", "primary_language": "zh-CN"
  },
  "context_records": [{
    "record_id": "ctx_xxx",
    "record_type": "从允许的 record_type 枚举选择",
    "title": "...", "content": "...",
    "data_classification": "PUBLIC_SYNTHETIC|INTERNAL_SYNTHETIC"
  }],
  "constraints": [{
    "constraint_id": "constraint_xxx", "rule": "...",
    "enforcement_point": "COMPILER|GATEWAY|VALIDATOR|HUMAN",
    "violation_code": "UPPER_SNAKE_CASE"
  }],
  "steps": [{
    "step_id": "step_01", "ordinal": 1, "name": "...",
    "stage": "INTAKE|EXTRACT|NORMALIZE|DECIDE|ACT|VALIDATE|REPORT|HUMAN",
    "executor_kind_hint": "TOOL|FSM|EXTRACTOR|ADAPTER|VALIDATOR|CONTRACT|POLICY|SKELETON|HUMAN",
    "operation_key": "输入要求的稳定操作名", "goal": "...",
    "reason_code": "UPPER_SNAKE_CASE", "decision_summary": "只写证据化结论",
    "input_refs": ["ctx_xxx或前序artifact_xxx"],
    "action_name": "namespace.action", "action_arguments": {"key": "value"},
    "output_artifact": {
      "artifact_id": "artifact_xxx", "artifact_type": "UPPER_SNAKE_CASE",
      "schema_name": "PascalCase", "summary": "...",
      "payload": {"key": "value"}, "evidence_refs": ["ctx_xxx"]
    },
    "validation": {
      "check_id": "check_xxx", "rule": "...",
      "status": "PASS|FAIL|NEEDS_REVIEW",
      "evidence_refs": ["ctx_xxx或artifact_xxx"], "failure_code": null
    },
    "allowed_tools": [], "side_effect_class": "NONE|READ_ONLY|LOCAL_WRITE|HUMAN_HANDOFF",
    "idempotency_key_template": null,
    "possible_failure_codes": ["UPPER_SNAKE_CASE"],
    "on_success": "下一step_id或END",
    "on_failure": "SAFE_STOP|HUMAN_REVIEW|已有step_id"
  }],
  "outcome": {
    "status": "SUCCEEDED|PARTIAL|WAITING_HUMAN|REJECTED",
    "summary": "...", "final_artifact_refs": ["必须引用实际输出的artifact_id"],
    "unresolved_items": [], "validator_status": "PASS|FAIL|NEEDS_REVIEW"
  },
  "candidate_assets": [{
    "candidate_id": "candidate_xxx",
    "kind": "TOOL|FSM|EXTRACTOR|ADAPTER|VALIDATOR|CONTRACT|POLICY|SKELETON|HUMAN",
    "proposed_name": "namespace.asset_name",
    "derived_from_step_ids": ["已有step_id"], "purpose": "...",
    "input_contract": [{
      "name": "snake_case", "data_type": "string",
      "required": true, "description": "..."
    }],
    "output_contract": [{
      "name": "snake_case", "data_type": "string",
      "required": true, "description": "..."
    }],
    "preconditions": ["..."], "postconditions": ["..."], "invariants": ["..."],
    "failure_codes": ["UPPER_SNAKE_CASE"],
    "side_effect_class": "NONE|READ_ONLY|LOCAL_WRITE|HUMAN_HANDOFF",
    "deterministic": true, "evidence_refs": ["ctx_xxx或artifact_xxx"],
    "extraction_notes": "...", "status": "DRAFT"
  }],
  "extraction_tags": ["..."]
}
"""


@dataclass(frozen=True, slots=True)
class GenerationOptions:
    """Runtime options for one collection run."""

    model: str
    host: str
    temperature: float = 0.2
    seed: int = 20260727
    num_ctx: int = 8192
    num_predict: int = 5000
    max_retries: int = 2
    keep_alive: str = "30m"


@dataclass(frozen=True, slots=True)
class GenerationResult:
    """A generated record and its output location."""

    envelope: SyntheticTraceEnvelope
    output_path: Path
    skipped: bool


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scenario_prompt(scenario: ScenarioSpec, attempt: int, error: str | None) -> str:
    required_operations = ", ".join(scenario.required_operations)
    required_kinds = ", ".join(scenario.required_candidate_kinds)
    repair = ""
    if error:
        repair = (
            "\n上一次输出未通过校验。只修复结构和引用，不降低内容质量。"
            f"\n校验错误摘要：{error[:1200]}\n"
        )
    return f"""生成一条编号为 {scenario.scenario_id} 的合成 Trace。

领域：{scenario.domain}
任务族：{scenario.task_family}
标题：{scenario.title}
目标：{scenario.objective}
虚构上下文：{scenario.context_brief}
必须体现的稳定操作：{required_operations}
优先覆盖的候选资产 Kind：{required_kinds}
风险级别：{scenario.risk_level}

内容要求：
- 生成 1-2 个有实际字段和数值的 context_records，每条内容控制在 500 字以内；
- 生成 3-6 个按 ordinal 连续排列的步骤，step_id 使用 step_01、step_02 格式；
- 按“必须体现的稳定操作”每个操作生成一个步骤，不额外扩展步骤；
- 每个步骤输出一个带 payload 的 output_artifact 和一个 validation；
- 最终 Artifact 引用必须来自步骤实际输出；
- 生成 2-3 个 DRAFT candidate_assets，derived_from_step_ids 必须引用已有步骤；
- Candidate 的 input_contract/output_contract 只保留 1-3 个关键字段；
- action_arguments 和 Artifact payload 只保留支撑该步骤的关键字段；
- 至少包含一个 TOOL/FSM/EXTRACTOR/VALIDATOR 候选；
- on_success 写下一 step_id 或 END，on_failure 写 SAFE_STOP、HUMAN_REVIEW 或某个已有 step_id；
- 涉及写入时使用 LOCAL_WRITE 和幂等键；只读步骤使用 READ_ONLY 或 NONE；
- evidence_refs 使用 context record id 或前面步骤产生的 artifact id；
- 不输出思维过程，只记录 reason_code 和不超过两句的 decision_summary。

{OUTPUT_SHAPE}

当前生成尝试：{attempt}
{repair}"""


class SyntheticTraceGenerator:
    """Generate and persist validated synthetic traces through local Ollama."""

    def __init__(
        self,
        options: GenerationOptions,
        *,
        on_retry: Callable[[ScenarioSpec, int, Exception], None] | None = None,
    ) -> None:
        self.options = options
        self.on_retry = on_retry
        self.client = ollama.Client(host=options.host, timeout=600.0)

    def assert_model_available(self) -> None:
        """Fail early when the configured model is missing."""
        response = self.client.list()
        model_names = {model.model for model in response.models if model.model is not None}
        if self.options.model not in model_names:
            raise RuntimeError(
                f"Model {self.options.model!r} not found. Available models: {sorted(model_names)}"
            )

    def generate(
        self,
        scenario: ScenarioSpec,
        output_root: Path,
        *,
        resume: bool = True,
    ) -> GenerationResult:
        """Generate one scenario, validating references before atomic persistence."""
        trace_id = f"trace_syn_{scenario.scenario_id}"
        output_path = output_root / "records" / scenario.domain / f"{trace_id}.json"
        if resume and output_path.exists():
            envelope = SyntheticTraceEnvelope.model_validate_json(output_path.read_text("utf-8"))
            return GenerationResult(envelope=envelope, output_path=output_path, skipped=True)

        last_error: Exception | None = None
        error_summary: str | None = None
        for attempt in range(1, self.options.max_retries + 2):
            prompt = _scenario_prompt(scenario, attempt, error_summary)
            try:
                response = self.client.chat(
                    model=self.options.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    stream=False,
                    think=False,
                    format="json",
                    options={
                        "temperature": self.options.temperature,
                        "seed": self.options.seed + _scenario_seed_offset(scenario.scenario_id),
                        "num_ctx": self.options.num_ctx,
                        "num_predict": self.options.num_predict,
                    },
                    keep_alive=self.options.keep_alive,
                )
                if not isinstance(response, ollama.ChatResponse):
                    raise TypeError("Expected a non-streaming ChatResponse")
                content = response.message.content
                if not content:
                    raise ValueError("Ollama returned empty message content")
                canonical_payload, normalizations = _canonicalize_payload(
                    content,
                    scenario,
                )
                generated = GeneratedTrace.model_validate(canonical_payload)
                _validate_scenario_alignment(generated, scenario)
                envelope = _build_envelope(
                    trace_id=trace_id,
                    generated=generated,
                    scenario=scenario,
                    normalizations=normalizations,
                    response=response,
                    prompt=prompt,
                    options=self.options,
                    attempt=attempt,
                )
                _atomic_write_json(output_path, envelope.model_dump(mode="json"))
                return GenerationResult(
                    envelope=envelope,
                    output_path=output_path,
                    skipped=False,
                )
            except (
                ValidationError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
                ollama.ResponseError,
            ) as exc:
                last_error = exc
                error_summary = str(exc)
                if attempt <= self.options.max_retries and self.on_retry is not None:
                    self.on_retry(scenario, attempt, exc)

        raise RuntimeError(
            f"Failed to generate {scenario.scenario_id} after retries: {last_error}"
        ) from last_error


def _scenario_seed_offset(scenario_id: str) -> int:
    return int(_digest(scenario_id)[:8], 16) % 1_000_000


def _canonicalize_payload(
    content: str,
    scenario: ScenarioSpec,
) -> tuple[dict[str, Any], list[str]]:
    """Normalize model formatting variants without changing domain facts."""
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("Ollama JSON response must be an object")
    normalizations: list[str] = []

    _set_canonical(payload, "scenario_id", scenario.scenario_id, "scenario_id", normalizations)
    _set_canonical(payload, "domain", scenario.domain, "domain", normalizations)
    _set_canonical(payload, "task_family", scenario.task_family, "task_family", normalizations)

    record_type_aliases = {
        "DOCUMENT_CONTENT": "contract_excerpt",
        "DOCUMENT_SNAPSHOT": "structured_record",
        "CONTRACT": "contract_excerpt",
        "REPORT_TABLE": "financial_table",
        "DIALOGUE": "customer_dialogue",
        "EMAIL": "internal_message",
        "NOTICE": "internal_message",
        "POLICY": "policy_excerpt",
        "FORM": "application_form",
        "TRANSACTIONS": "transaction_summary",
    }
    default_record_types = {
        "loan_contract": "contract_excerpt",
        "financial_report": "financial_table",
        "customer_service": "customer_dialogue",
        "internal_communication": "internal_message",
        "risk_compliance": "structured_record",
        "corporate_operations": "structured_record",
    }
    allowed_record_types = {
        "contract_excerpt",
        "financial_table",
        "customer_dialogue",
        "internal_message",
        "policy_excerpt",
        "application_form",
        "transaction_summary",
        "structured_record",
    }
    contexts = payload.get("context_records", [])
    context_id_map: dict[str, str] = {}
    used_context_ids: set[str] = set()
    for index, record in enumerate(contexts if isinstance(contexts, list) else [], start=1):
        if isinstance(record, dict):
            old_record_id = _string_value(record.get("record_id"))
            new_record_id = _canonical_prefixed_id(
                old_record_id,
                target_prefix="ctx",
                aliases=("context", "record", "source", "doc", "input"),
                index=index,
                used=used_context_ids,
                max_suffix_length=80,
            )
            _set_canonical(
                record,
                "record_id",
                new_record_id,
                f"context_records[{index - 1}].record_id",
                normalizations,
            )
            if old_record_id:
                context_id_map.setdefault(old_record_id, new_record_id)

            record_type = record.get("record_type")
            if isinstance(record_type, str):
                canonical_record_type = record_type_aliases.get(
                    record_type.upper(),
                    record_type.lower(),
                )
                if canonical_record_type not in allowed_record_types:
                    canonical_record_type = default_record_types[scenario.domain]
                _set_canonical(
                    record,
                    "record_type",
                    canonical_record_type,
                    f"context_records[{index - 1}].record_type",
                    normalizations,
                )
            _set_canonical(
                record,
                "data_classification",
                _canonical_data_classification(record.get("data_classification")),
                f"context_records[{index - 1}].data_classification",
                normalizations,
            )

    constraints = payload.get("constraints", [])
    if isinstance(constraints, list) and not constraints:
        constraints.append(
            {
                "constraint_id": "constraint_synthetic_only",
                "rule": "只允许使用完全合成的数据，不得用于真实金融决策。",
                "enforcement_point": "VALIDATOR",
                "violation_code": "SYNTHETIC_DATA_REQUIRED",
            }
        )
        normalizations.append("constraints:added_code_owned_synthetic_constraint")

    used_constraint_ids: set[str] = set()
    for index, constraint in enumerate(
        constraints if isinstance(constraints, list) else [],
        start=1,
    ):
        if isinstance(constraint, dict):
            old_constraint_id = _string_value(constraint.get("constraint_id"))
            new_constraint_id = _canonical_prefixed_id(
                old_constraint_id,
                target_prefix="constraint",
                aliases=("cst", "constr", "const", "rule", "policy"),
                index=index,
                used=used_constraint_ids,
                max_suffix_length=80,
            )
            _set_canonical(
                constraint,
                "constraint_id",
                new_constraint_id,
                f"constraints[{index - 1}].constraint_id",
                normalizations,
            )
            _set_canonical(
                constraint,
                "enforcement_point",
                _canonical_enforcement_point(constraint.get("enforcement_point")),
                f"constraints[{index - 1}].enforcement_point",
                normalizations,
            )
            _set_canonical(
                constraint,
                "violation_code",
                _canonical_code(constraint.get("violation_code"), "POLICY_VIOLATION"),
                f"constraints[{index - 1}].violation_code",
                normalizations,
            )

    steps = payload.get("steps", [])
    step_id_map: dict[str, str] = {}
    artifact_id_map: dict[str, str] = {}
    used_artifact_ids: set[str] = set()
    for index, step in enumerate(steps if isinstance(steps, list) else [], start=1):
        if isinstance(step, dict):
            old_step_id = _string_value(step.get("step_id"))
            new_step_id = f"step_{index:02d}"
            _set_canonical(
                step,
                "step_id",
                new_step_id,
                f"steps[{index - 1}].step_id",
                normalizations,
            )
            if old_step_id:
                step_id_map.setdefault(old_step_id, new_step_id)
            _set_canonical(
                step,
                "ordinal",
                index,
                f"steps[{index - 1}].ordinal",
                normalizations,
            )
            fallback_operation = scenario.required_operations[
                min(index - 1, len(scenario.required_operations) - 1)
            ]
            _set_canonical(
                step,
                "operation_key",
                _canonical_snake(step.get("operation_key"), fallback_operation, 80),
                f"steps[{index - 1}].operation_key",
                normalizations,
            )
            _set_canonical(
                step,
                "stage",
                _canonical_stage(step.get("stage")),
                f"steps[{index - 1}].stage",
                normalizations,
            )
            _set_canonical(
                step,
                "executor_kind_hint",
                _canonical_asset_kind(step.get("executor_kind_hint"), "FSM"),
                f"steps[{index - 1}].executor_kind_hint",
                normalizations,
            )
            _set_canonical(
                step,
                "reason_code",
                _canonical_code(step.get("reason_code"), "STEP_DECISION"),
                f"steps[{index - 1}].reason_code",
                normalizations,
            )
            _set_canonical(
                step,
                "action_name",
                _canonical_dotted_name(
                    step.get("action_name"),
                    f"synthetic.{fallback_operation}",
                ),
                f"steps[{index - 1}].action_name",
                normalizations,
            )
            _set_canonical(
                step,
                "side_effect_class",
                _canonical_side_effect(step.get("side_effect_class")),
                f"steps[{index - 1}].side_effect_class",
                normalizations,
            )
            failure_codes = step.get("possible_failure_codes")
            if isinstance(failure_codes, list):
                step["possible_failure_codes"] = [
                    _canonical_code(code, "OPERATION_FAILED") for code in failure_codes
                ] or ["OPERATION_FAILED"]

            artifact = step.get("output_artifact")
            if isinstance(artifact, dict):
                old_artifact_id = _string_value(artifact.get("artifact_id"))
                new_artifact_id = _canonical_prefixed_id(
                    old_artifact_id,
                    target_prefix="artifact",
                    aliases=("art", "output", "result"),
                    index=index,
                    used=used_artifact_ids,
                    max_suffix_length=80,
                )
                _set_canonical(
                    artifact,
                    "artifact_id",
                    new_artifact_id,
                    f"steps[{index - 1}].output_artifact.artifact_id",
                    normalizations,
                )
                if old_artifact_id:
                    artifact_id_map.setdefault(old_artifact_id, new_artifact_id)
                _set_canonical(
                    artifact,
                    "artifact_type",
                    _canonical_code(artifact.get("artifact_type"), "STEP_ARTIFACT"),
                    f"steps[{index - 1}].output_artifact.artifact_type",
                    normalizations,
                )
                _set_canonical(
                    artifact,
                    "schema_name",
                    _canonical_schema_name(artifact.get("schema_name")),
                    f"steps[{index - 1}].output_artifact.schema_name",
                    normalizations,
                )

            validation = step.get("validation")
            if isinstance(validation, dict):
                old_check_id = _string_value(validation.get("check_id"))
                new_check_id = _canonical_prefixed_id(
                    old_check_id,
                    target_prefix="check",
                    aliases=("chk", "val", "validation"),
                    index=index,
                    used=set(),
                    max_suffix_length=80,
                )
                _set_canonical(
                    validation,
                    "check_id",
                    new_check_id,
                    f"steps[{index - 1}].validation.check_id",
                    normalizations,
                )
                _set_canonical(
                    validation,
                    "status",
                    _canonical_validation_status(validation.get("status")),
                    f"steps[{index - 1}].validation.status",
                    normalizations,
                )
                failure_code = validation.get("failure_code")
                if failure_code not in (None, "", "NONE", "N/A"):
                    validation["failure_code"] = _canonical_code(
                        failure_code,
                        "VALIDATION_FAILED",
                    )
                else:
                    validation["failure_code"] = None

    candidates = payload.get("candidate_assets", [])
    used_candidate_ids: set[str] = set()
    for index, candidate in enumerate(
        candidates if isinstance(candidates, list) else [],
        start=1,
    ):
        if isinstance(candidate, dict):
            old_candidate_id = _string_value(candidate.get("candidate_id"))
            new_candidate_id = _canonical_prefixed_id(
                old_candidate_id,
                target_prefix="candidate",
                aliases=("cand", "asset", "proposal"),
                index=index,
                used=used_candidate_ids,
                max_suffix_length=100,
            )
            _set_canonical(
                candidate,
                "candidate_id",
                new_candidate_id,
                f"candidate_assets[{index - 1}].candidate_id",
                normalizations,
            )
            _set_canonical(
                candidate,
                "kind",
                _canonical_asset_kind(candidate.get("kind"), "SKELETON"),
                f"candidate_assets[{index - 1}].kind",
                normalizations,
            )
            _set_canonical(
                candidate,
                "proposed_name",
                _canonical_dotted_name(
                    candidate.get("proposed_name"),
                    f"synthetic.{scenario.task_family}.candidate_{index:02d}",
                ),
                f"candidate_assets[{index - 1}].proposed_name",
                normalizations,
            )
            candidate["status"] = "DRAFT"
            _set_canonical(
                candidate,
                "side_effect_class",
                _canonical_side_effect(candidate.get("side_effect_class")),
                f"candidate_assets[{index - 1}].side_effect_class",
                normalizations,
            )
            failure_codes = candidate.get("failure_codes")
            if isinstance(failure_codes, list):
                candidate["failure_codes"] = [
                    _canonical_code(code, "CANDIDATE_FAILED") for code in failure_codes
                ] or ["CANDIDATE_FAILED"]
            for contract_name in ("input_contract", "output_contract"):
                fields = candidate.get(contract_name, [])
                for field_index, field in enumerate(
                    fields if isinstance(fields, list) else [],
                    start=1,
                ):
                    if isinstance(field, dict):
                        field["name"] = _canonical_snake(
                            field.get("name"),
                            f"field_{field_index:02d}",
                            63,
                        )
                        data_type = field.get("data_type")
                        if isinstance(data_type, str):
                            field["data_type"] = _canonical_data_type(data_type)

    reference_map = context_id_map | step_id_map | artifact_id_map
    _replace_exact_references(payload, reference_map)
    _repair_trace_references(payload, normalizations)

    task = payload.get("task")
    if isinstance(task, dict):
        _set_canonical(
            task,
            "risk_level",
            scenario.risk_level,
            "task.risk_level",
            normalizations,
        )
        _set_canonical(
            task,
            "primary_language",
            "zh-CN",
            "task.primary_language",
            normalizations,
        )
        _set_canonical(
            task,
            "expected_mode",
            _canonical_execution_mode(task.get("expected_mode")),
            "task.expected_mode",
            normalizations,
        )

    outcome = payload.get("outcome")
    if isinstance(outcome, dict):
        _set_canonical(
            outcome,
            "status",
            _canonical_outcome_status(outcome.get("status")),
            "outcome.status",
            normalizations,
        )
        _set_canonical(
            outcome,
            "validator_status",
            _canonical_validation_status(outcome.get("validator_status")),
            "outcome.validator_status",
            normalizations,
        )

    extraction_tags = payload.get("extraction_tags")
    if not isinstance(extraction_tags, list) or not extraction_tags:
        payload["extraction_tags"] = [scenario.domain, scenario.task_family, "synthetic"]
        normalizations.append("extraction_tags:added_scenario_defaults")
    return payload, normalizations


def _set_canonical(
    container: dict[str, Any],
    key: str,
    value: Any,
    path: str,
    normalizations: list[str],
) -> None:
    old_value = container.get(key)
    container[key] = value
    if old_value != value:
        normalizations.append(f"{path}:{old_value!r}->{value!r}")


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _canonical_snake(value: Any, fallback: str, max_length: int) -> str:
    raw = _string_value(value) or fallback
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    if not normalized or not normalized[0].isalpha():
        normalized = f"value_{normalized}" if normalized else fallback
    return normalized[:max_length].rstrip("_")


def _canonical_code(value: Any, fallback: str) -> str:
    normalized = _canonical_snake(value, fallback.lower(), 63).upper()
    return normalized if len(normalized) >= 4 else f"{normalized}_CODE"


def _canonical_enum(value: Any, fallback: str) -> str:
    return _canonical_snake(value, fallback.lower(), 63).upper()


def _canonical_dotted_name(value: Any, fallback: str) -> str:
    raw = _string_value(value) or fallback
    parts = [
        _canonical_snake(part, "operation", 40)
        for part in re.split(r"[./:]+", raw)
        if part.strip()
    ]
    normalized = ".".join(parts) or fallback
    if len(normalized) < 4:
        normalized = f"synthetic.{normalized}"
    return normalized[:120].rstrip(".")


def _canonical_prefixed_id(
    value: str,
    *,
    target_prefix: str,
    aliases: tuple[str, ...],
    index: int,
    used: set[str],
    max_suffix_length: int,
) -> str:
    normalized = _canonical_snake(value, f"{target_prefix}_{index:02d}", 150)
    prefixes = (target_prefix, *aliases)
    suffix = normalized
    for prefix in prefixes:
        marker = f"{prefix}_"
        if normalized.startswith(marker):
            suffix = normalized[len(marker) :]
            break
    suffix = suffix[:max_suffix_length].strip("_")
    if len(suffix) < 2:
        suffix = f"{index:02d}"
    candidate = f"{target_prefix}_{suffix}"
    duplicate_index = 2
    while candidate in used:
        suffix_marker = f"_{duplicate_index}"
        candidate = (
            f"{target_prefix}_{suffix[: max_suffix_length - len(suffix_marker)]}"
            f"{suffix_marker}"
        )
        duplicate_index += 1
    used.add(candidate)
    return candidate


def _replace_exact_references(value: Any, replacements: dict[str, str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and item in replacements:
                value[key] = replacements[item]
            else:
                _replace_exact_references(item, replacements)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str) and item in replacements:
                value[index] = replacements[item]
            else:
                _replace_exact_references(item, replacements)


def _repair_trace_references(
    payload: dict[str, Any],
    normalizations: list[str],
) -> None:
    steps = [step for step in payload.get("steps", []) if isinstance(step, dict)]
    contexts = [
        record for record in payload.get("context_records", []) if isinstance(record, dict)
    ]
    step_ids = [str(step["step_id"]) for step in steps if "step_id" in step]
    context_ids = [
        str(record["record_id"]) for record in contexts if "record_id" in record
    ]
    artifact_ids = [
        str(artifact["artifact_id"])
        for step in steps
        if isinstance((artifact := step.get("output_artifact")), dict)
        and "artifact_id" in artifact
    ]
    known_input_refs = set(context_ids + artifact_ids)

    for index, step in enumerate(steps):
        next_step = step_ids[index + 1] if index + 1 < len(step_ids) else "END"
        if step.get("on_success") not in {*step_ids, "END"}:
            _set_canonical(
                step,
                "on_success",
                next_step,
                f"steps[{index}].on_success",
                normalizations,
            )
        if step.get("on_failure") not in {*step_ids, "SAFE_STOP", "HUMAN_REVIEW"}:
            _set_canonical(
                step,
                "on_failure",
                "SAFE_STOP",
                f"steps[{index}].on_failure",
                normalizations,
            )
        input_refs = step.get("input_refs")
        if not isinstance(input_refs, list) or not input_refs:
            fallback_ref = (
                artifact_ids[index - 1]
                if index > 0 and index - 1 < len(artifact_ids)
                else (context_ids[0] if context_ids else None)
            )
            if fallback_ref:
                step["input_refs"] = [fallback_ref]
                normalizations.append(f"steps[{index}].input_refs:added_fallback")
        elif known_input_refs:
            valid_refs = [ref for ref in input_refs if ref in known_input_refs]
            if not valid_refs:
                step["input_refs"] = [
                    artifact_ids[index - 1]
                    if index > 0 and index - 1 < len(artifact_ids)
                    else context_ids[0]
                ]
                normalizations.append(f"steps[{index}].input_refs:repaired_unknown_refs")

    outcome = payload.get("outcome")
    if isinstance(outcome, dict) and artifact_ids:
        final_refs = outcome.get("final_artifact_refs")
        valid_final_refs = (
            [ref for ref in final_refs if ref in artifact_ids]
            if isinstance(final_refs, list)
            else []
        )
        if not valid_final_refs:
            outcome["final_artifact_refs"] = [artifact_ids[-1]]
            normalizations.append("outcome.final_artifact_refs:repaired_to_last_artifact")

    candidates = [
        candidate
        for candidate in payload.get("candidate_assets", [])
        if isinstance(candidate, dict)
    ]
    for index, candidate in enumerate(candidates):
        derived = candidate.get("derived_from_step_ids")
        valid_steps = (
            [step_id for step_id in derived if step_id in step_ids]
            if isinstance(derived, list)
            else []
        )
        if not valid_steps and step_ids:
            candidate["derived_from_step_ids"] = [step_ids[min(index, len(step_ids) - 1)]]
            normalizations.append(
                f"candidate_assets[{index}].derived_from_step_ids:repaired"
            )


def _canonical_schema_name(value: Any) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", _string_value(value))
    normalized = "".join(part[:1].upper() + part[1:] for part in parts)
    if len(normalized) < 3 or not normalized[0].isalpha():
        return "SyntheticArtifact"
    return normalized[:80]


def _canonical_asset_kind(value: Any, fallback: str) -> str:
    normalized = _canonical_enum(value, fallback)
    aliases = {
        "TOOLS": "TOOL",
        "FUNCTION": "TOOL",
        "STATE_MACHINE": "FSM",
        "FINITE_STATE_MACHINE": "FSM",
        "EXTRACT": "EXTRACTOR",
        "VALIDATION": "VALIDATOR",
        "SCHEMA": "CONTRACT",
        "WORKFLOW": "SKELETON",
        "HUMAN_REVIEW": "HUMAN",
    }
    canonical = aliases.get(normalized, normalized)
    allowed = {
        "TOOL",
        "FSM",
        "EXTRACTOR",
        "ADAPTER",
        "VALIDATOR",
        "CONTRACT",
        "POLICY",
        "SKELETON",
        "HUMAN",
    }
    return canonical if canonical in allowed else fallback


def _canonical_stage(value: Any) -> str:
    normalized = _canonical_enum(value, "DECIDE")
    aliases = {
        "INPUT": "INTAKE",
        "PARSE": "EXTRACT",
        "PROCESS": "DECIDE",
        "ACTION": "ACT",
        "VERIFY": "VALIDATE",
        "OUTPUT": "REPORT",
        "HUMAN_REVIEW": "HUMAN",
    }
    canonical = aliases.get(normalized, normalized)
    allowed = {
        "INTAKE",
        "EXTRACT",
        "NORMALIZE",
        "DECIDE",
        "ACT",
        "VALIDATE",
        "REPORT",
        "HUMAN",
    }
    return canonical if canonical in allowed else "DECIDE"


def _canonical_side_effect(value: Any) -> str:
    normalized = _canonical_enum(value, "NONE")
    aliases = {
        "READ": "READ_ONLY",
        "READONLY": "READ_ONLY",
        "NO_SIDE_EFFECT": "NONE",
        "WRITE": "LOCAL_WRITE",
        "HUMAN": "HUMAN_HANDOFF",
    }
    canonical = aliases.get(normalized, normalized)
    allowed = {"NONE", "READ_ONLY", "LOCAL_WRITE", "HUMAN_HANDOFF"}
    return canonical if canonical in allowed else "NONE"


def _canonical_validation_status(value: Any) -> str:
    normalized = _canonical_enum(value, "NEEDS_REVIEW")
    aliases = {
        "SUCCESS": "PASS",
        "PASSED": "PASS",
        "FAILED": "FAIL",
        "REVIEW": "NEEDS_REVIEW",
        "PENDING": "NEEDS_REVIEW",
    }
    canonical = aliases.get(normalized, normalized)
    return canonical if canonical in {"PASS", "FAIL", "NEEDS_REVIEW"} else "NEEDS_REVIEW"


def _canonical_enforcement_point(value: Any) -> str:
    normalized = _canonical_enum(value, "VALIDATOR")
    aliases = {
        "COMPILE": "COMPILER",
        "ACTION_GATEWAY": "GATEWAY",
        "VALIDATION": "VALIDATOR",
        "HUMAN_REVIEW": "HUMAN",
    }
    canonical = aliases.get(normalized, normalized)
    return canonical if canonical in {"COMPILER", "GATEWAY", "VALIDATOR", "HUMAN"} else "VALIDATOR"


def _canonical_execution_mode(value: Any) -> str:
    normalized = _canonical_enum(value, "HYBRID")
    aliases = {"REASON": "NEW", "HUMAN": "CLARIFY"}
    canonical = aliases.get(normalized, normalized)
    return canonical if canonical in {"REUSE", "HYBRID", "NEW", "CLARIFY"} else "HYBRID"


def _canonical_outcome_status(value: Any) -> str:
    normalized = _canonical_enum(value, "PARTIAL")
    aliases = {
        "SUCCESS": "SUCCEEDED",
        "PASS": "SUCCEEDED",
        "FAILED": "REJECTED",
        "FAIL": "REJECTED",
        "HUMAN_REVIEW": "WAITING_HUMAN",
    }
    canonical = aliases.get(normalized, normalized)
    allowed = {"SUCCEEDED", "PARTIAL", "WAITING_HUMAN", "REJECTED"}
    return canonical if canonical in allowed else "PARTIAL"


def _canonical_data_classification(value: Any) -> str:
    normalized = _canonical_enum(value, "INTERNAL_SYNTHETIC")
    return (
        normalized
        if normalized in {"PUBLIC_SYNTHETIC", "INTERNAL_SYNTHETIC"}
        else "INTERNAL_SYNTHETIC"
    )


def _canonical_data_type(data_type: str) -> str:
    normalized = data_type.strip().lower()
    if normalized.startswith(("array", "list", "tuple", "set")):
        return "array"
    if normalized.startswith(("object", "dict", "map", "json")):
        return "object"
    if normalized in {"str", "text", "varchar"}:
        return "string"
    if normalized in {"int", "long"}:
        return "integer"
    if normalized in {"float", "double", "decimal"}:
        return "number"
    if normalized in {"bool"}:
        return "boolean"
    return normalized


def _validate_scenario_alignment(trace: GeneratedTrace, scenario: ScenarioSpec) -> None:
    if trace.scenario_id != scenario.scenario_id:
        raise ValueError(
            f"scenario_id mismatch: expected {scenario.scenario_id}, got {trace.scenario_id}"
        )
    if trace.domain != scenario.domain:
        raise ValueError(f"domain mismatch: expected {scenario.domain}, got {trace.domain}")
    if trace.task_family != scenario.task_family:
        raise ValueError(
            f"task_family mismatch: expected {scenario.task_family}, got {trace.task_family}"
        )


def _build_envelope(
    *,
    trace_id: str,
    generated: GeneratedTrace,
    scenario: ScenarioSpec,
    normalizations: list[str],
    response: ollama.ChatResponse,
    prompt: str,
    options: GenerationOptions,
    attempt: int,
) -> SyntheticTraceEnvelope:
    content = response.message.content
    if not content:
        raise ValueError("Ollama returned empty message content")
    provenance = GenerationProvenance(
        generator="ollama_structured_trace_collector",
        model=options.model,
        generated_at=datetime.now(UTC),
        seed=options.seed + _scenario_seed_offset(generated.scenario_id),
        temperature=options.temperature,
        num_ctx=options.num_ctx,
        num_predict=options.num_predict,
        prompt_sha256=_digest(SYSTEM_PROMPT + "\n" + prompt),
        response_sha256=_digest(content),
        attempts=attempt,
        prompt_tokens=response.prompt_eval_count,
        output_tokens=response.eval_count,
        total_duration_ns=response.total_duration,
        load_duration_ns=response.load_duration,
        prompt_eval_duration_ns=response.prompt_eval_duration,
        eval_duration_ns=response.eval_duration,
    )
    governance = TraceGovernance(
        status="DRAFT",
        synthetic=True,
        contains_real_pii=False,
        chain_of_thought_stored=False,
        schema_validated=True,
        human_review_required=True,
        eligible_for_candidate_extraction=True,
        allowed_uses=[
            "asset_candidate_mining",
            "schema_experiments",
            "retrieval_seed",
            "component_testing",
        ],
        prohibited_uses=[
            "automatic_activation",
            "production_decisioning",
            "claim_as_real_execution_evidence",
        ],
    )
    actual_operations = [step.operation_key for step in generated.steps]
    missing_operations = sorted(set(scenario.required_operations) - set(actual_operations))
    actual_candidate_kinds = sorted(
        {candidate.kind for candidate in generated.candidate_assets},
        key=lambda kind: kind.value,
    )
    required_candidate_kinds = [
        AssetKind(kind) for kind in scenario.required_candidate_kinds
    ]
    missing_candidate_kinds = sorted(
        set(required_candidate_kinds) - set(actual_candidate_kinds),
        key=lambda kind: kind.value,
    )
    operation_coverage = (
        len(set(actual_operations) & set(scenario.required_operations))
        / len(scenario.required_operations)
    )
    quality_flags: list[str] = []
    if operation_coverage < 1.0:
        quality_flags.append("MISSING_REQUIRED_OPERATIONS")
    if operation_coverage < 0.75:
        quality_flags.append("LOW_OPERATION_COVERAGE")
    if missing_candidate_kinds:
        quality_flags.append("MISSING_REQUIRED_CANDIDATE_KINDS")
    if len(generated.constraints) < 2:
        quality_flags.append("FEWER_THAN_TWO_CONSTRAINTS")
    if len(generated.steps) < 3:
        quality_flags.append("FEWER_THAN_THREE_STEPS")
    if len(generated.candidate_assets) < 2:
        quality_flags.append("FEWER_THAN_TWO_CANDIDATES")
    if normalizations:
        quality_flags.append("FORMAT_NORMALIZED")
    quality_score = max(
        0.0,
        1.0
        - (0.25 * max(0.0, 1.0 - operation_coverage))
        - (0.05 * len(missing_candidate_kinds))
        - (0.03 * len([flag for flag in quality_flags if flag != "FORMAT_NORMALIZED"])),
    )
    scenario_requirements = ScenarioRequirements(
        required_operations=list(scenario.required_operations),
        actual_operations=actual_operations,
        missing_operations=missing_operations,
        operation_coverage=operation_coverage,
        required_candidate_kinds=required_candidate_kinds,
        actual_candidate_kinds=actual_candidate_kinds,
        normalizations_applied=normalizations,
        quality_flags=quality_flags,
        quality_score=round(quality_score, 4),
    )
    return SyntheticTraceEnvelope(
        schema_version="synthetic-trace.v1",
        trace_id=trace_id,
        trace=generated,
        scenario_requirements=scenario_requirements,
        provenance=provenance,
        governance=governance,
    )


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, path)


def load_validated_envelopes(output_root: Path) -> list[tuple[Path, SyntheticTraceEnvelope]]:
    """Load all persisted records under an output root."""
    records: list[tuple[Path, SyntheticTraceEnvelope]] = []
    for path in sorted((output_root / "records").glob("*/*.json")):
        envelope = SyntheticTraceEnvelope.model_validate_json(path.read_text("utf-8"))
        records.append((path, envelope))
    return records


def build_manifest(
    output_root: Path,
    *,
    model: str,
    expected_count: int,
) -> dict[str, Any]:
    """Build a deterministic manifest from validated persisted records."""
    records = load_validated_envelopes(output_root)
    counts_by_domain: dict[str, int] = {}
    total_prompt_tokens = 0
    total_output_tokens = 0
    manifest_records: list[dict[str, Any]] = []

    for path, envelope in records:
        domain = envelope.trace.domain
        counts_by_domain[domain] = counts_by_domain.get(domain, 0) + 1
        total_prompt_tokens += envelope.provenance.prompt_tokens or 0
        total_output_tokens += envelope.provenance.output_tokens or 0
        serialized = path.read_text("utf-8")
        manifest_records.append(
            {
                "trace_id": envelope.trace_id,
                "scenario_id": envelope.trace.scenario_id,
                "domain": domain,
                "task_family": envelope.trace.task_family,
                "path": str(path.relative_to(output_root)),
                "sha256": _digest(serialized),
                "candidate_kinds": sorted(
                    {candidate.kind.value for candidate in envelope.trace.candidate_assets}
                ),
                "operation_keys": [step.operation_key for step in envelope.trace.steps],
                "operation_coverage": envelope.scenario_requirements.operation_coverage,
                "quality_score": envelope.scenario_requirements.quality_score,
                "quality_flags": envelope.scenario_requirements.quality_flags,
                "normalization_count": len(
                    envelope.scenario_requirements.normalizations_applied
                ),
                "attempts": envelope.provenance.attempts,
                "prompt_tokens": envelope.provenance.prompt_tokens,
                "output_tokens": envelope.provenance.output_tokens,
            }
        )

    return {
        "schema_version": "synthetic-trace-manifest.v1",
        "collection_id": f"finance-enterprise-{expected_count}-v1",
        "updated_at": datetime.now(UTC).isoformat(),
        "model": model,
        "expected_count": expected_count,
        "record_count": len(records),
        "counts_by_domain": dict(sorted(counts_by_domain.items())),
        "total_prompt_tokens": total_prompt_tokens,
        "total_output_tokens": total_output_tokens,
        "records": manifest_records,
    }


def write_manifest_and_report(
    output_root: Path,
    *,
    model: str,
    expected_count: int,
) -> dict[str, Any]:
    """Persist the JSON manifest and a concise Markdown collection report."""
    manifest = build_manifest(output_root, model=model, expected_count=expected_count)
    _atomic_write_json(output_root / "manifest.json", manifest)

    domain_rows = "\n".join(
        f"| `{domain}` | {count} |"
        for domain, count in cast(dict[str, int], manifest["counts_by_domain"]).items()
    )
    report = f"""# Synthetic Trace Collection Report

- Collection: `finance-enterprise-{expected_count}-v1`
- Schema: `synthetic-trace.v1`
- Model: `{model}`
- Expected records: {expected_count}
- Validated records: {manifest["record_count"]}
- Prompt tokens: {manifest["total_prompt_tokens"]}
- Output tokens: {manifest["total_output_tokens"]}
- Governance: `DRAFT`, synthetic, human review required
- Chain-of-thought stored: no

## Domain coverage

| Domain | Count |
| --- | ---: |
{domain_rows}

## Intended use

These records are synthetic source traces for candidate mining, schema experiments,
retrieval seeding, and component tests. Candidate hints are not executable assets and
must never be activated without extraction, deterministic validation, Golden replay,
and explicit human approval.
"""
    report_path = output_root / "COLLECTION_REPORT.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return manifest
