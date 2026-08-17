"""Extract validated financial_report Kind assets into the local Registry."""

from __future__ import annotations

import json
from pathlib import Path

from reduce_token_agent.registry.financial_report_registry_seed import (
    seed_financial_report_registry,
)


def main() -> int:
    """Seed the Registry and print a machine-readable summary."""
    project_root = Path(__file__).resolve().parents[1]
    result = seed_financial_report_registry(project_root)
    print(
        json.dumps(
            {
                "event": "financial_report_registry_seeded",
                "asset_count": result.asset_count,
                "edge_count": result.edge_count,
                "database": str(result.database_path.relative_to(project_root)),
                "report": str(result.report_path.relative_to(project_root)),
                "release_status": "DRAFT",
                "active_snapshot_created": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
