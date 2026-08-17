CREATE TABLE IF NOT EXISTS execution_run (
    run_id TEXT PRIMARY KEY REFERENCES control_run(run_id),
    thread_id TEXT NOT NULL,
    blueprint_id TEXT NOT NULL,
    status TEXT NOT NULL,
    placeholder_step_count INTEGER NOT NULL DEFAULT 0,
    business_validated INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    result_json TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS execution_step_attempt (
    run_id TEXT NOT NULL REFERENCES execution_run(run_id),
    step_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    phase TEXT NOT NULL,
    subgoal_id TEXT NOT NULL,
    executor_kind TEXT NOT NULL,
    operation_key TEXT NOT NULL,
    asset_ref TEXT,
    validator_ref TEXT,
    validated_asset_refs_json TEXT NOT NULL DEFAULT '[]',
    input_refs_json TEXT NOT NULL,
    output_artifact_refs_json TEXT NOT NULL,
    input_summary_json TEXT NOT NULL,
    output_summary_json TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    business_validated INTEGER NOT NULL DEFAULT 0,
    failure_code TEXT,
    side_effect TEXT NOT NULL,
    idempotency_key_ref TEXT,
    decision_summary TEXT NOT NULL,
    duration_ns INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY(run_id, step_id, attempt_number, phase)
);

CREATE INDEX IF NOT EXISTS idx_execution_step_run
ON execution_step_attempt(run_id, step_id, attempt_number);

CREATE TABLE IF NOT EXISTS execution_token_usage (
    usage_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES execution_run(run_id),
    stage TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    attempts INTEGER NOT NULL,
    estimated INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);
