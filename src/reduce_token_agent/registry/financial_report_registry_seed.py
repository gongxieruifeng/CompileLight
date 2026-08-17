"""Validated extraction, Artifact persistence, Registry load, and review reporting."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reduce_token_agent.assets_runtime.financial_report import FinancialReportRuntime
from reduce_token_agent.registry.financial_report_seed import (
    build_financial_report_assets,
    build_financial_report_edges,
)
from reduce_token_agent.registry.models import AssetDefinition
from reduce_token_agent.registry.repository import RegistryRepository
from reduce_token_agent.trace_data.models import SyntheticTraceEnvelope


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Paths and counts produced by one idempotent seed run."""

    database_path: Path
    report_path: Path
    artifact_root: Path
    asset_count: int
    edge_count: int


def seed_financial_report_registry(project_root: Path) -> SeedResult:
    """Extract only financial_report evidence and load validated DRAFT assets."""
    domain = "financial_report"
    trace_root = project_root / "data/traces/synthetic/qwen3.5-9b/v1/records/financial_report"
    traces = _load_source_traces(trace_root, domain=domain, expected_count=8)
    assets = build_financial_report_assets()
    _validate_asset_evidence(assets, traces)
    edges = build_financial_report_edges(assets)

    migration_path = project_root / "migrations/001_registry.sql"
    database_path = project_root / "data/db/registry.sqlite3"
    repository = RegistryRepository(database_path, migration_path)
    repository.migrate()

    artifact_root = project_root / "data/artifacts/registry/financial_report/v1"
    runtime_artifact_root = project_root / "data/artifacts/runtime/financial_report/v1"
    runtime = FinancialReportRuntime()
    runtime_metadata = runtime.metadata()
    for asset in assets:
        relative_path, digest = _write_immutable_artifact(
            project_root,
            artifact_root,
            asset,
        )
        repository.register_asset(
            asset,
            artifact_path=relative_path,
            artifact_digest=digest,
        )
        metadata = runtime_metadata[asset.asset_ref]
        runtime_path, runtime_digest = _write_runtime_metadata(
            project_root,
            runtime_artifact_root,
            asset.asset_ref,
            metadata,
        )
        repository.register_runtime_binding(
            asset_ref=asset.asset_ref,
            implementation_ref=metadata.implementation_ref,
            execution_mode=metadata.execution_mode,
            policy_version=metadata.policy_version,
            metadata_path=runtime_path,
            metadata_digest=runtime_digest,
            runtime_status=(
                "PLANNING_ONLY" if metadata.execution_mode == "PLANNING_ONLY" else "READY"
            ),
            tested_at=None,
        )
    repository.register_edges(edges)

    summary = repository.summary_for_domain(domain)
    if summary["asset_count"] != len(assets):
        raise RuntimeError(
            "Registry contains an unexpected number of asset versions; "
            "use a clean project database for this PoC seed"
        )
    if summary["validated_count"] != len(assets):
        raise RuntimeError("not every financial_report asset passed validation")
    if summary["runtime_ready_count"] != len(assets) - 1:
        raise RuntimeError("not every executable asset has a runtime binding")
    if summary["planning_only_count"] != 1:
        raise RuntimeError("DAEF planning prior binding is missing")
    if summary["snapshot_count"] != 0:
        raise RuntimeError("DRAFT Trace assets must not be auto-activated into a snapshot")

    report_path = project_root / "data/db/FINANCIAL_REPORT_REVIEW.md"
    _write_review_report(
        report_path,
        database_path=database_path,
        assets=assets,
        traces=traces,
        repository=repository,
        domain=domain,
    )
    return SeedResult(
        database_path=database_path,
        report_path=report_path,
        artifact_root=artifact_root,
        asset_count=len(assets),
        edge_count=len(edges),
    )


def _load_source_traces(
    trace_root: Path,
    *,
    domain: str,
    expected_count: int,
) -> dict[str, SyntheticTraceEnvelope]:
    traces: dict[str, SyntheticTraceEnvelope] = {}
    for path in sorted(trace_root.glob("*.json")):
        envelope = SyntheticTraceEnvelope.model_validate_json(path.read_text(encoding="utf-8"))
        if envelope.trace.domain != domain:
            raise ValueError(f"non-{domain} Trace found at {path}")
        traces[envelope.trace_id] = envelope
    if len(traces) != expected_count:
        raise ValueError(f"expected exactly {expected_count} {domain} traces, found {len(traces)}")
    return traces


def _validate_asset_evidence(
    assets: list[AssetDefinition],
    traces: dict[str, SyntheticTraceEnvelope],
) -> None:
    seen_refs: set[str] = set()
    for asset in assets:
        if asset.asset_ref in seen_refs:
            raise ValueError(f"duplicate asset ref: {asset.asset_ref}")
        seen_refs.add(asset.asset_ref)
        for evidence in asset.source_evidence:
            envelope = traces.get(evidence.trace_id)
            if envelope is None:
                raise ValueError(f"{asset.asset_ref} references unknown Trace {evidence.trace_id}")
            if evidence.scenario_id != envelope.trace.scenario_id:
                raise ValueError(f"{asset.asset_ref} scenario provenance mismatch")
            step_ids = {step.step_id for step in envelope.trace.steps}
            candidate_ids = {
                candidate.candidate_id for candidate in envelope.trace.candidate_assets
            }
            if not set(evidence.step_ids).issubset(step_ids):
                raise ValueError(f"{asset.asset_ref} references an unknown Trace step")
            if not set(evidence.candidate_ids).issubset(candidate_ids):
                raise ValueError(f"{asset.asset_ref} references an unknown Trace candidate")


def _write_immutable_artifact(
    project_root: Path,
    artifact_root: Path,
    asset: AssetDefinition,
) -> tuple[Path, str]:
    kind_directory = asset.kind.value.lower()
    filename = f"{asset.asset_id.replace('.', '__')}@{asset.version}.json"
    path = artifact_root / kind_directory / filename
    payload = {
        "schema_version": "registry-asset.v1",
        "asset": asset.model_dump(mode="json"),
    }
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    digest = "sha256:" + hashlib.sha256(serialized).hexdigest()

    if path.exists():
        existing = path.read_bytes()
        if existing != serialized:
            raise ValueError(f"immutable Artifact conflict at {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_bytes(serialized)
        os.replace(temporary_path, path)
    return path.relative_to(project_root), digest


def _write_runtime_metadata(
    project_root: Path,
    artifact_root: Path,
    asset_ref: str,
    metadata: Any,
) -> tuple[Path, str]:
    """Persist policy and implementation metadata without embedding code in the DB."""
    filename = asset_ref.replace(".", "__").replace("@", "__") + ".json"
    path = artifact_root / filename
    payload = {
        "schema_version": "runtime-binding.v1",
        "asset_ref": asset_ref,
        "implementation_ref": metadata.implementation_ref,
        "execution_mode": metadata.execution_mode,
        "policy_version": metadata.policy_version,
        "business_rules": list(metadata.business_rules),
        "side_effect": metadata.side_effect,
    }
    serialized = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    digest = "sha256:" + hashlib.sha256(serialized).hexdigest()
    if path.exists():
        if path.read_bytes() != serialized:
            raise ValueError(f"immutable runtime metadata conflict at {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + ".tmp")
        temporary_path.write_bytes(serialized)
        os.replace(temporary_path, path)
    return path.relative_to(project_root), digest


def _write_review_report(
    report_path: Path,
    *,
    database_path: Path,
    assets: list[AssetDefinition],
    traces: dict[str, SyntheticTraceEnvelope],
    repository: RegistryRepository,
    domain: str,
) -> None:
    summary = repository.summary_for_domain(domain)
    kind_rows = "\n".join(
        f"| `{kind}` | {count} |" for kind, count in sorted(summary["kind_counts"].items())
    )
    asset_rows = "\n".join(
        "| `{asset_ref}` | `{kind}` | {name} | `{recall}` | `{validation}` | "
        "`{status}` | `{runtime}` | `{tested}` |".format(
            asset_ref=row["asset_ref"],
            kind=row["kind"],
            name=row["name"],
            recall=row["recall_policy"],
            validation=row["validation_status"],
            status=row["status"],
            runtime=row["runtime_status"],
            tested=row["tested_at"] or "未测试",
        )
        for row in repository.asset_rows_for_domain(domain)
    )
    trace_rows = "\n".join(
        "| `{scenario}` | {score:.4f} | {flags} |".format(
            scenario=envelope.trace.scenario_id,
            score=envelope.scenario_requirements.quality_score,
            flags=", ".join(envelope.scenario_requirements.quality_flags) or "无",
        )
        for envelope in sorted(
            traces.values(),
            key=lambda item: item.trace.scenario_id,
        )
    )
    report = f"""# Financial Report Kind Registry 审查报告

## 审查结论

- 该 domain 已完成 `DRAFT` 资产抽取、运行绑定和本地可执行验证。
- 当前未创建 `ACTIVE` Snapshot，未实现 Retrieval Layer。
- `WORKFLOW_SKELETON` 仅作为 DAEF 规划先验存在。

## 数据库概况

- 数据库路径：`{database_path}`
- 资产数量：{summary["asset_count"]}
- 关系边数量：{summary["edge_count"]}
- Runtime Ready：{summary["runtime_ready_count"]}
- Planning Only：{summary["planning_only_count"]}
- tested_at：{summary["runtime_tested_count"]}
- Snapshot：{summary["snapshot_count"]}

## Kind 汇总

{kind_rows}

## 资产清单

| Asset Ref | Kind | Name | Recall | Validation | Status | Runtime | tested_at |
| --- | --- | --- | --- | --- | --- | --- | --- |
{asset_rows}

## Trace 质量标记

| Scenario | Quality Score | Flags |
| --- | ---: | --- |
{trace_rows}

## 当前可用性

- `PRIMITIVE_TOOL`：本地可直接执行。
- `FSM_SHARD`：已绑定最小业务执行体，并可独立验证。
- `ADAPTER`：仅做确定性字段和币种归一。
- `VALIDATOR`：独立校验输出边界。
- `WORKFLOW_SKELETON`：仅用于 DAEF 规划先验。

## 备注

- 这里仍然不包含 Retrieval Layer。
- 这里仍然不创建 Active Snapshot。
- 这里仍然不引入 `Skill` / `BLUEPRINT` / `EXTRACTOR` kind。
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
