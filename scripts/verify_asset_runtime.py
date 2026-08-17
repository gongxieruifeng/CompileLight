"""Verify that one or many Registry assets can execute with traceable status."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reduce_token_agent.registry.repository import RegistryRepository, utc_now
from reduce_token_agent.runtime_verification import (
    load_runtime_for_domain,
    verify_assets,
    write_verification_report,
)


def main() -> int:
    """Run one-off or batch runtime verification and emit JSON trace records."""
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    db_path = args.db_path or project_root / "data/db/registry.sqlite3"
    migration_path = args.migration_path or project_root / "migrations/001_registry.sql"
    repository = RegistryRepository(db_path, migration_path)
    repository.migrate()

    asset_refs = resolve_asset_refs(repository, args)
    if not asset_refs:
        raise SystemExit("no asset refs were selected for verification")

    selected_domains = {
        domain
        for domain in (
            _domain_from_asset_ref(repository, asset_ref) for asset_ref in asset_refs
        )
        if domain is not None
    }
    if len(selected_domains) > 1:
        raise SystemExit("selected asset refs span multiple domains")

    runtime_domain = args.domain or next(iter(selected_domains), None)
    if runtime_domain is None:
        raise SystemExit("could not infer a runtime domain for the selected assets")
    runtime = load_runtime_for_domain(runtime_domain)

    payload_overrides = load_payload_overrides(args.payload_file, args.asset_ref)
    records, summary = verify_assets(
        repository,
        runtime,
        asset_refs,
        mark_tested=args.mark_tested,
        payload_dir=args.payload_dir,
        payload_overrides=payload_overrides,
    )

    report_path = args.report_path or default_report_path(
        project_root=project_root,
        domain=runtime_domain,
    )
    write_verification_report(report_path, summary=summary, records=records)

    for record in records:
        print(
            json.dumps(
                {
                    "event": "asset_runtime_verified",
                    "asset_ref": record.asset_ref,
                    "domain": record.domain,
                    "kind": record.kind,
                    "input_source": record.input_source,
                    "execution_status": record.execution_status,
                    "validation_status": record.validation_status_runtime,
                    "success": record.success,
                    "runtime_status_before": record.runtime_status_before,
                    "runtime_status_after": record.runtime_status_after,
                    "tested_at_before": record.tested_at_before,
                    "tested_at_after": record.tested_at_after,
                    "report": _display_path(report_path, project_root),
                },
                ensure_ascii=False,
            )
        )

    print(
        json.dumps(
            {
                "event": "asset_runtime_verification_summary",
                "domain": summary.domain,
                "total": summary.total,
                "passed": summary.passed,
                "failed": summary.failed,
                "skipped": summary.skipped,
                "report": _display_path(report_path, project_root),
            },
            ensure_ascii=False,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    """Parse command-line options for the verifier."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset-ref", action="append", dest="asset_ref")
    parser.add_argument("--domain")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--payload-file", type=Path)
    parser.add_argument("--payload-dir", type=Path)
    parser.add_argument("--report-path", type=Path)
    parser.add_argument("--db-path", type=Path)
    parser.add_argument("--migration-path", type=Path)
    parser.add_argument(
        "--mark-tested",
        action="store_true",
        help="write tested_at back to runtime_binding after a successful verification",
    )
    return parser.parse_args()


def resolve_asset_refs(
    repository: RegistryRepository,
    args: argparse.Namespace,
) -> list[str]:
    """Resolve the target asset refs from CLI options."""
    if args.asset_ref:
        return list(dict.fromkeys(args.asset_ref))
    if args.domain and args.all:
        return repository.asset_refs_for_domain(args.domain)
    if args.domain:
        return repository.asset_refs_for_domain(args.domain)
    return []


def load_payload_overrides(
    payload_file: Path | None,
    asset_refs: list[str] | None,
) -> dict[str, dict[str, Any]] | None:
    """Load an explicit payload override for one selected asset."""
    if payload_file is None:
        return None
    if asset_refs is None or len(asset_refs) != 1:
        raise SystemExit("--payload-file can only be used with exactly one asset_ref")
    return {asset_refs[0]: json.loads(payload_file.read_text(encoding="utf-8"))}


def default_report_path(*, project_root: Path, domain: str) -> Path:
    """Create a stable report path under the runtime verification reports tree."""
    timestamp = utc_now().replace(":", "-")
    return (
        project_root
        / "data/reports/runtime_verification"
        / domain
        / f"{timestamp}.json"
    )


def _domain_from_asset_ref(
    repository: RegistryRepository,
    asset_ref: str,
) -> str | None:
    context = repository.asset_context(asset_ref)
    if context is None:
        return None
    return context["domain"]


def _display_path(path: Path, project_root: Path) -> str:
    """Render an absolute or project-relative path without raising."""
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
