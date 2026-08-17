PRAGMA foreign_keys = ON;

CREATE VIRTUAL TABLE IF NOT EXISTS route_header_fts USING fts5(
    asset_ref UNINDEXED,
    search_text,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS retrieval_embedding (
    asset_ref TEXT PRIMARY KEY REFERENCES asset_version(asset_ref),
    embedding_model TEXT NOT NULL,
    embedding_dim INTEGER NOT NULL CHECK (embedding_dim > 0),
    embedding_blob BLOB NOT NULL,
    content_digest TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS retrieval_index_state (
    index_id TEXT PRIMARY KEY,
    visibility_policy TEXT NOT NULL CHECK (
        visibility_policy IN ('VALIDATED_DRAFT', 'ACTIVE_SNAPSHOT')
    ),
    snapshot_id TEXT REFERENCES registry_snapshot(snapshot_id),
    embedding_model TEXT NOT NULL,
    asset_set_digest TEXT NOT NULL,
    document_count INTEGER NOT NULL CHECK (document_count >= 0),
    built_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retrieval_embedding_model
    ON retrieval_embedding(embedding_model);
CREATE INDEX IF NOT EXISTS idx_retrieval_state_built_at
    ON retrieval_index_state(built_at);
