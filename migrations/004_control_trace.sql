CREATE TABLE IF NOT EXISTS control_run (
    run_id TEXT PRIMARY KEY,
    trace_id TEXT UNIQUE,
    task_id TEXT,
    tenant_id TEXT,
    principal_ref TEXT,
    query_ref TEXT NOT NULL,
    safe_query TEXT,
    status TEXT NOT NULL,
    mode TEXT,
    destinations_json TEXT NOT NULL DEFAULT '[]',
    failure_code TEXT,
    trace_path TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS control_event (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES control_run(run_id),
    sequence INTEGER NOT NULL,
    stage TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(run_id, sequence)
);

CREATE TABLE IF NOT EXISTS control_blueprint (
    run_id TEXT PRIMARY KEY REFERENCES control_run(run_id),
    proposal_json TEXT,
    compile_result_json TEXT,
    repair_attempts INTEGER NOT NULL DEFAULT 0,
    registry_view_json TEXT
);
