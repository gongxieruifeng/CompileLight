PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS route_header_fts;

CREATE TABLE IF NOT EXISTS runtime_binding (
    asset_ref TEXT PRIMARY KEY REFERENCES asset_version(asset_ref),
    implementation_ref TEXT NOT NULL,
    execution_mode TEXT NOT NULL CHECK (
        execution_mode IN ('EXECUTABLE', 'PLANNING_ONLY')
    ),
    policy_version TEXT NOT NULL,
    metadata_path TEXT NOT NULL,
    metadata_digest TEXT NOT NULL,
    runtime_status TEXT NOT NULL CHECK (
        runtime_status IN ('READY', 'PLANNING_ONLY', 'UNAVAILABLE')
    ),
    tested_at TEXT,
    UNIQUE(metadata_digest)
);

CREATE INDEX IF NOT EXISTS idx_runtime_status ON runtime_binding(runtime_status);
