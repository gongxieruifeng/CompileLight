PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset (
    asset_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'PRIMITIVE_TOOL',
            'FSM_SHARD',
            'WORKFLOW_SKELETON',
            'ADAPTER',
            'VALIDATOR'
        )
    ),
    owner TEXT NOT NULL,
    domain TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_version (
    asset_ref TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL REFERENCES asset(asset_id),
    version TEXT NOT NULL,
    contract_json TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    artifact_digest TEXT NOT NULL,
    source_trace_ids_json TEXT NOT NULL,
    test_suite_ref TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(asset_id, version),
    UNIQUE(artifact_digest)
);

CREATE TABLE IF NOT EXISTS asset_release (
    asset_ref TEXT PRIMARY KEY REFERENCES asset_version(asset_ref),
    status TEXT NOT NULL CHECK (
        status IN ('DRAFT', 'ACTIVE', 'QUARANTINED', 'RETIRED')
    ),
    risk_level TEXT NOT NULL CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
    required_scopes_json TEXT NOT NULL,
    validation_status TEXT NOT NULL CHECK (
        validation_status IN ('NOT_TESTED', 'PASS', 'FAIL')
    ),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS route_header (
    asset_ref TEXT PRIMARY KEY REFERENCES asset_version(asset_ref),
    name TEXT NOT NULL,
    summary TEXT NOT NULL,
    recall_policy TEXT NOT NULL CHECK (
        recall_policy IN ('ORDINARY', 'PLANNING_PRIOR', 'GRAPH_ONLY')
    ),
    positive_triggers_json TEXT NOT NULL,
    anti_triggers_json TEXT NOT NULL,
    input_type_summary TEXT NOT NULL,
    output_type_summary TEXT NOT NULL,
    keywords_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_edge (
    from_ref TEXT NOT NULL REFERENCES asset_version(asset_ref),
    to_ref TEXT NOT NULL REFERENCES asset_version(asset_ref),
    edge_type TEXT NOT NULL CHECK (
        edge_type IN (
            'DEPENDS_ON',
            'REQUIRES_VALIDATOR',
            'ALTERNATIVE_TO',
            'COMPATIBLE_VIA_ADAPTER'
        )
    ),
    adapter_ref TEXT REFERENCES asset_version(asset_ref),
    evidence TEXT NOT NULL,
    PRIMARY KEY(from_ref, to_ref, edge_type)
);

CREATE TABLE IF NOT EXISTS evaluation_run (
    evaluation_id TEXT PRIMARY KEY,
    asset_ref TEXT NOT NULL REFERENCES asset_version(asset_ref),
    suite_ref TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL')),
    evaluated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS registry_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    active_set_digest TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_member (
    snapshot_id TEXT NOT NULL REFERENCES registry_snapshot(snapshot_id),
    asset_ref TEXT NOT NULL REFERENCES asset_version(asset_ref),
    PRIMARY KEY(snapshot_id, asset_ref)
);

CREATE INDEX IF NOT EXISTS idx_asset_kind ON asset(kind);
CREATE INDEX IF NOT EXISTS idx_release_status ON asset_release(status);
CREATE INDEX IF NOT EXISTS idx_route_recall_policy ON route_header(recall_policy);
CREATE INDEX IF NOT EXISTS idx_edge_from_ref ON capability_edge(from_ref);
