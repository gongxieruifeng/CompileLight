"""Generic runtime verification for versioned capability assets."""

from __future__ import annotations

import importlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from reduce_token_agent.registry.repository import RegistryRepository, utc_now


class RuntimeProtocol(Protocol):
    """Minimal runtime contract used by the verifier."""

    def metadata(self) -> dict[str, Any]: ...

    def sample_payload(self, asset_ref: str) -> dict[str, Any]: ...

    def execute(self, asset_ref: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def planning_prior(self, asset_ref: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AssetVerificationRecord:
    """Traceable verification outcome for one asset ref."""

    asset_ref: str
    asset_id: str
    version: str
    domain: str
    kind: str
    name: str
    status: str
    validation_status: str
    runtime_status_before: str | None
    runtime_status_after: str | None
    tested_at_before: str | None
    tested_at_after: str | None
    input_payload: dict[str, Any] | None
    input_source: str
    output_payload: dict[str, Any] | None
    validator_ref: str | None
    validator_output: dict[str, Any] | None
    execution_status: str
    validation_status_runtime: str
    success: bool
    error: dict[str, str] | None
    started_at: str
    finished_at: str

    def as_json(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the record."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class AssetVerificationSummary:
    """Aggregate outcome for one verification batch."""

    domain: str | None
    total: int
    passed: int
    failed: int
    skipped: int
    report_path: str


def load_runtime_for_domain(domain: str) -> RuntimeProtocol:
    """Load the domain runtime module using a stable naming convention."""
    module = importlib.import_module(f"reduce_token_agent.assets_runtime.{domain}")
    class_candidates = [
        "".join(part.capitalize() for part in domain.split("_")) + "Runtime",
        "Runtime",
        "DomainRuntime",
    ]
    for class_name in class_candidates:
        runtime_class = getattr(module, class_name, None)
        if runtime_class is not None:
            return cast(RuntimeProtocol, runtime_class())
    for factory_name in ("get_runtime", "build_runtime", "create_runtime"):
        factory = getattr(module, factory_name, None)
        if factory is not None:
            return cast(RuntimeProtocol, factory())
    raise RuntimeError(f"no runtime factory found for domain {domain}")


def verify_assets(
    repository: RegistryRepository,
    runtime: RuntimeProtocol,
    asset_refs: list[str],
    *,
    mark_tested: bool,
    payload_dir: Path | None = None,
    payload_overrides: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[AssetVerificationRecord], AssetVerificationSummary]:
    """Verify one or many exact asset refs and return traceable records."""
    records: list[AssetVerificationRecord] = []
    for asset_ref in asset_refs:
        records.append(
            verify_one_asset(
                repository,
                runtime,
                asset_ref,
                mark_tested=mark_tested,
                payload_dir=payload_dir,
                payload_overrides=payload_overrides,
            )
        )
    summary = AssetVerificationSummary(
        domain=_record_domain(records),
        total=len(records),
        passed=sum(1 for record in records if record.success),
        failed=sum(1 for record in records if not record.success),
        skipped=sum(1 for record in records if record.execution_status == "SKIPPED"),
        report_path="",
    )
    return records, summary


def verify_one_asset(
    repository: RegistryRepository,
    runtime: RuntimeProtocol,
    asset_ref: str,
    *,
    mark_tested: bool,
    payload_dir: Path | None = None,
    payload_overrides: dict[str, dict[str, Any]] | None = None,
) -> AssetVerificationRecord:
    """Verify one asset ref with traceable input, output, and status details."""
    started_at = utc_now()
    context = repository.asset_context(asset_ref)
    if context is None:
        finished_at = utc_now()
        return AssetVerificationRecord(
            asset_ref=asset_ref,
            asset_id="",
            version="",
            domain="",
            kind="",
            name="",
            status="NOT_FOUND",
            validation_status="NOT_TESTED",
            runtime_status_before=None,
            runtime_status_after=None,
            tested_at_before=None,
            tested_at_after=None,
            input_payload=None,
            input_source="not_found",
            output_payload=None,
            validator_ref=None,
            validator_output=None,
            execution_status="FAILED",
            validation_status_runtime="FAILED",
            success=False,
            error={"code": "ASSET_NOT_FOUND", "message": asset_ref},
            started_at=started_at,
            finished_at=finished_at,
        )

    kind = cast(str, context["kind"])
    domain = cast(str, context["domain"])
    runtime_status_before = _maybe_str(context["runtime_status"])
    tested_at_before = _maybe_str(context["tested_at"])
    payload, payload_source = _resolve_payload(
        runtime,
        asset_ref,
        payload_dir=payload_dir,
        payload_overrides=payload_overrides,
    )
    validator_ref = repository.required_validator_ref(asset_ref)
    output_payload: dict[str, Any] | None = None
    validator_output: dict[str, Any] | None = None
    execution_status = "SKIPPED"
    validation_status_runtime = "SKIPPED"
    success = False
    error: dict[str, str] | None = None

    try:
        if kind == "WORKFLOW_SKELETON":
            planning_prior = runtime.planning_prior(asset_ref)
            output_payload = planning_prior
            execution_status = "SKIPPED"
            validation_status_runtime = "NOT_APPLICABLE"
            success = (
                planning_prior.get("directly_executable") is False
                and bool(planning_prior.get("stages"))
            )
        else:
            output_payload = runtime.execute(asset_ref, payload)
            execution_status = "SUCCESS"
            if kind == "VALIDATOR":
                validation_status_runtime = "NOT_APPLICABLE"
                success = bool(output_payload.get("valid"))
            else:
                if validator_ref is not None:
                    validator_output = runtime.execute(
                        validator_ref,
                        {"payload": output_payload},
                    )
                    validation_status_runtime = (
                        "SUCCESS" if validator_output.get("valid") is True else "FAILED"
                    )
                    success = execution_status == "SUCCESS" and (
                        validation_status_runtime == "SUCCESS"
                    )
                else:
                    validation_status_runtime = "NOT_APPLICABLE"
                    success = True

        if success and mark_tested:
            tested_at = utc_now()
            repository.mark_runtime_tested(asset_ref, tested_at=tested_at)
            refreshed = repository.asset_context(asset_ref)
            runtime_status_after = (
                _maybe_str(refreshed["runtime_status"]) if refreshed else runtime_status_before
            )
            tested_at_after = (
                _maybe_str(refreshed["tested_at"]) if refreshed else tested_at
            )
        else:
            runtime_status_after = runtime_status_before
            tested_at_after = tested_at_before
    except Exception as exc:  # pragma: no cover - converted into structured failure
        runtime_status_after = runtime_status_before
        tested_at_after = tested_at_before
        error = {"code": exc.__class__.__name__, "message": str(exc)}
        success = False
        if execution_status == "SKIPPED":
            execution_status = "FAILED"
        if validation_status_runtime == "SKIPPED":
            validation_status_runtime = "FAILED"

    finished_at = utc_now()
    return AssetVerificationRecord(
        asset_ref=asset_ref,
        asset_id=cast(str, context["asset_id"]),
        version=cast(str, context["version"]),
        domain=domain,
        kind=kind,
        name=cast(str, context["name"]),
        status=cast(str, context["status"]),
        validation_status=cast(str, context["validation_status"]),
        runtime_status_before=runtime_status_before,
        runtime_status_after=runtime_status_after,
        tested_at_before=tested_at_before,
        tested_at_after=tested_at_after,
        input_payload=payload,
        input_source=payload_source,
        output_payload=output_payload,
        validator_ref=validator_ref,
        validator_output=validator_output,
        execution_status=execution_status,
        validation_status_runtime=validation_status_runtime,
        success=success,
        error=error,
        started_at=started_at,
        finished_at=finished_at,
    )


def write_verification_report(
    report_path: Path,
    *,
    summary: AssetVerificationSummary,
    records: list[AssetVerificationRecord],
) -> None:
    """Persist a structured verification report."""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "summary": {
            "domain": summary.domain,
            "total": summary.total,
            "passed": summary.passed,
            "failed": summary.failed,
            "skipped": summary.skipped,
        },
        "records": [record.as_json() for record in records],
    }
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _resolve_payload(
    runtime: RuntimeProtocol,
    asset_ref: str,
    *,
    payload_dir: Path | None,
    payload_overrides: dict[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any], str]:
    if payload_overrides is not None and asset_ref in payload_overrides:
        return dict(payload_overrides[asset_ref]), "override"
    if payload_dir is not None:
        path = payload_dir / _payload_filename(asset_ref)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), f"file:{path}"
    sample_payload = getattr(runtime, "sample_payload", None)
    if callable(sample_payload):
        return cast(dict[str, Any], sample_payload(asset_ref)), "sample_payload"
    sample_payloads = getattr(runtime, "sample_payloads", None)
    if callable(sample_payloads):
        mapping = cast(dict[str, dict[str, Any]], sample_payloads())
        if asset_ref in mapping:
            return dict(mapping[asset_ref]), "sample_payloads"
    raise RuntimeError(f"no payload available for {asset_ref}")


def _record_domain(records: list[AssetVerificationRecord]) -> str | None:
    if not records:
        return None
    domains = {record.domain for record in records if record.domain}
    if len(domains) == 1:
        return next(iter(domains))
    return None


def _payload_filename(asset_ref: str) -> str:
    return asset_ref.replace(".", "__").replace("@", "__") + ".json"


def _maybe_str(value: Any) -> str | None:
    if value is None:
        return None
    return cast(str, value)
