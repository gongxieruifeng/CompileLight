"""Second-layer exact asset resolution and controlled invocation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from reduce_token_agent.domain.capability import (
    AssetCallDescriptor,
    AssetDetails,
    RelatedAsset,
)
from reduce_token_agent.registry.models import AssetKind
from reduce_token_agent.registry.retrieval_repository import RetrievalRepository
from reduce_token_agent.runtime_verification import (
    AssetVerificationRecord,
    load_runtime_for_domain,
    verify_one_asset,
)


class AssetResolver:
    """Resolve Contract and runtime metadata only after exact asset selection."""

    def __init__(self, repository: RetrievalRepository) -> None:
        self.repository = repository

    def resolve(self, asset_ref: str) -> AssetDetails:
        row = self.repository.detail_row(asset_ref)
        if row is None:
            raise LookupError(f"asset not found: {asset_ref}")
        artifact_path = _artifact_file(
            self.repository.project_root,
            cast(str, row["artifact_path"]),
        )
        artifact_payload = cast(
            dict[str, Any],
            json.loads(artifact_path.read_text(encoding="utf-8")),
        )
        domain = cast(str, row["domain"])
        runtime = load_runtime_for_domain(domain)
        sample_payload = runtime.sample_payload(asset_ref)
        contract = cast(dict[str, Any], json.loads(row["contract_json"]))
        related = [
            RelatedAsset(
                asset_ref=cast(str, item["to_ref"]),
                kind=AssetKind(cast(str, item["kind"])),
                edge_type=cast(str, item["edge_type"]),
                evidence=cast(str, item["evidence"]),
            )
            for item in self.repository.related_rows(asset_ref)
        ]
        return AssetDetails(
            asset_ref=cast(str, row["asset_ref"]),
            asset_id=cast(str, row["asset_id"]),
            version=cast(str, row["version"]),
            kind=AssetKind(cast(str, row["kind"])),
            domain=domain,
            release_status=cast(str, row["status"]),
            validation_status=cast(str, row["validation_status"]),
            name=cast(str, row["name"]),
            summary=cast(str, row["summary"]),
            positive_triggers=cast(
                list[str], json.loads(row["positive_triggers_json"])
            ),
            anti_triggers=cast(
                list[str], json.loads(row["anti_triggers_json"])
            ),
            keywords=cast(list[str], json.loads(row["keywords_json"])),
            contract=contract,
            call=AssetCallDescriptor(
                implementation_ref=cast(str, row["implementation_ref"]),
                execution_mode=cast(Any, row["execution_mode"]),
                runtime_status=cast(Any, row["runtime_status"]),
                policy_version=cast(str, row["policy_version"]),
                tested_at=cast(str | None, row["tested_at"]),
                input_schema=cast(dict[str, Any], contract["input_schema"]),
                output_schema=cast(dict[str, Any], contract["output_schema"]),
                sample_payload=sample_payload,
                required_validator_ref=self.repository.registry.required_validator_ref(
                    asset_ref
                ),
            ),
            related_assets=related,
            artifact_schema_version=cast(str, artifact_payload["schema_version"]),
            artifact_path=cast(str, row["artifact_path"]),
            artifact_digest=cast(str, row["artifact_digest"]),
            runtime_metadata_path=cast(str, row["metadata_path"]),
            runtime_metadata_digest=cast(str, row["metadata_digest"]),
        )


def _artifact_file(project_root: Path, relative_path: str) -> Path:
    """Resolve an immutable artifact for isolated DB fixtures or the live project."""
    candidate = project_root / relative_path
    if candidate.exists():
        return candidate
    fallback = Path(__file__).resolve().parents[3] / relative_path
    if fallback.exists():
        return fallback
    return candidate


class RetrievedAssetInvoker:
    """Invoke only an exact, resolved, tested asset binding."""

    def __init__(self, project_root: Path, repository: RetrievalRepository) -> None:
        self.project_root = project_root
        self.repository = repository
        self.resolver = AssetResolver(repository)

    def invoke(
        self,
        asset_ref: str,
        payload: dict[str, Any] | None = None,
    ) -> AssetVerificationRecord:
        """Return the existing traceable input/output/validator execution record."""
        details = self.resolver.resolve(asset_ref)
        if details.validation_status != "PASS" or details.call.tested_at is None:
            raise PermissionError(f"asset is not verified for invocation: {asset_ref}")
        if details.call.runtime_status not in {"READY", "PLANNING_ONLY"}:
            raise PermissionError(f"asset runtime is unavailable: {asset_ref}")
        runtime = load_runtime_for_domain(details.domain)
        overrides = None if payload is None else {asset_ref: payload}
        return verify_one_asset(
            self.repository.registry,
            runtime,
            asset_ref,
            mark_tested=False,
            payload_overrides=overrides,
        )
