"""Validated extraction, Artifact persistence, Registry load, and review reporting."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reduce_token_agent.assets_runtime.customer_service import CustomerServiceRuntime
from reduce_token_agent.registry.customer_service_seed import (
    build_customer_service_assets,
    build_customer_service_edges,
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


def seed_customer_service_registry(project_root: Path) -> SeedResult:
    """Extract only customer_service evidence and load validated DRAFT assets."""
    domain = "customer_service"
    trace_root = project_root / "data/traces/synthetic/qwen3.5-9b/v1/records/customer_service"
    traces = _load_source_traces(trace_root, domain=domain, expected_count=8)
    assets = build_customer_service_assets()
    _validate_asset_evidence(assets, traces)
    edges = build_customer_service_edges(assets)

    migration_path = project_root / "migrations/001_registry.sql"
    database_path = project_root / "data/db/registry.sqlite3"
    repository = RegistryRepository(database_path, migration_path)
    repository.migrate()

    artifact_root = project_root / "data/artifacts/registry/customer_service/v1"
    runtime_artifact_root = project_root / "data/artifacts/runtime/customer_service/v1"
    runtime = CustomerServiceRuntime()
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
        raise RuntimeError("not every customer_service asset passed validation")
    if summary["runtime_ready_count"] != len(assets) - 1:
        raise RuntimeError("not every executable asset has a runtime binding")
    if summary["planning_only_count"] != 1:
        raise RuntimeError("DAEF planning prior binding is missing")
    if summary["snapshot_count"] != 0:
        raise RuntimeError("DRAFT Trace assets must not be auto-activated into a snapshot")

    report_path = project_root / "data/db/CUSTOMER_SERVICE_REVIEW.md"
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
        envelope = SyntheticTraceEnvelope.model_validate_json(path.read_text("utf-8"))
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
        "`{status}` | `{runtime}` |".format(
            asset_ref=row["asset_ref"],
            kind=row["kind"],
            name=row["name"],
            recall=row["recall_policy"],
            validation=row["validation_status"],
            status=row["status"],
            runtime=row["runtime_status"],
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
    report = f"""# Customer Service Kind Registry 审查报告

## 审查结论

- 数据范围：仅 `domain={domain}` 的合成 Trace。
- Registry：`registry.sqlite3`。
- 资产版本：{summary["asset_count"]} 个，Kind Contract 验证通过
  {summary["validated_count"]} 个。
- 关系边：{summary["edge_count"]} 条。
- 发布状态：全部为 `DRAFT`；ACTIVE Snapshot 数量为
  {summary["snapshot_count"]}。
- 当前 Runtime：{summary["runtime_ready_count"]} 个可执行资产已绑定本地 Handler，
  {summary["planning_only_count"]} 个 DAEF Skeleton 为规划专用；它们仍然全部是 DRAFT。
- 行为验收记录：{summary["runtime_tested_count"]} 个 Runtime Binding 已记录
  `tested_at`；domain 测试固定在 `tests/assets/{domain}/`。

这里的 `Skill` 只作为产品层上位词。数据库没有 `SKILL`、`BLUEPRINT` 或
`EXTRACTOR` Kind。具体请求的临时编排结果属于运行期数据，不进入 Registry
资产库；Registry 中只用 `WORKFLOW_SKELETON` 表示不绑定具体资产版本的 DAEF
宏观阶段先验。

## Kind 数量

{kind_rows}

## 资产可用情况

| Asset Ref | Kind | 名称 | 召回方式 | 合规验证 | 发布状态 | Runtime 状态 |
| --- | --- | --- | --- | --- | --- | --- |
{asset_rows}

召回约束：

- `PRIMITIVE_TOOL`、`FSM_SHARD`：有完整本地 Handler 和测试 Harness；
- `WORKFLOW_SKELETON`：只进入规划先验通道，不直接执行；
- `ADAPTER`、`VALIDATOR`：默认仅通过 Capability Graph 一跳扩展加入；
- 当前全部是 `DRAFT`，因此不会被线上/本地执行控制流误当成已发布能力。

## 来源 Trace 审查

| Scenario | Trace Quality Score | 原 Trace Quality Flags |
| --- | ---: | --- |
{trace_rows}

## 粒度决策

- 没有把每个 Trace Step 都转为资产；
- Tool 只保留单个受控查询/函数；
- FSM 以可独立验证的客服子目标为边界；
- DAEF 只保留 `INFORMATION -> TRANSFORM -> DECISION -> ACTION -> VALIDATION`
  宏观状态与不变量，不含具体资产版本；
- Adapter 只做字段转换；Validator 与生成结果的资产分离；
- Trace 中的真实姓名、金额、城市、日期和具体票据内容没有进入资产 Body。

## 后续启用门槛

1. 继续补充 Contract Unit Test、非法输入、失败码和幂等测试；
2. 用独立 Golden/Replay 扩大行为覆盖，而不只是当前最小合成案例；
3. 由人工 CLI 执行 Activate，创建新的不可变 ACTIVE Snapshot；
4. 只有新规划可以固定该 Snapshot，已有 Run 不热切换。
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
