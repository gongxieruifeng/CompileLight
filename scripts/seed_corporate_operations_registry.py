"""Extract validated corporate_operations Kind assets into the local Registry."""

from __future__ import annotations

import json
from pathlib import Path

from reduce_token_agent.registry.seed import seed_corporate_operations_registry


def main() -> int:
    """Seed the Registry and print a machine-readable summary."""
    project_root = Path(__file__).resolve().parents[1]
    result = seed_corporate_operations_registry(project_root)
    print(
        json.dumps(
            {
                "event": "corporate_operations_registry_seeded",
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
