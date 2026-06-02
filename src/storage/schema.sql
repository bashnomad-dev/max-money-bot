-- SQLite-схема для max-money-bot.
-- Соответствует docs/data-model.md §3.

CREATE TABLE IF NOT EXISTS chat_sheets (
    chat_id TEXT PRIMARY KEY,
    sheet_id TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    linked_by_user_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_log (
    message_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    result TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dedup_window (
    semantic_hash TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    operation_summary TEXT NOT NULL,
    sheet_row_refs TEXT NOT NULL,           -- JSON
    expires_at TEXT NOT NULL,
    PRIMARY KEY (semantic_hash, chat_id)
);
CREATE INDEX IF NOT EXISTS idx_dedup_expires ON dedup_window(expires_at);

CREATE TABLE IF NOT EXISTS dialog_state (
    chat_id TEXT PRIMARY KEY,
    intent TEXT NOT NULL,
    awaiting_field TEXT,
    partial_data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dialog_expires ON dialog_state(expires_at);

CREATE TABLE IF NOT EXISTS operations_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    op_kind TEXT NOT NULL,
    sheet_refs TEXT NOT NULL,               -- JSON
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    undone_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_oplog_chat_created ON operations_log(chat_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_oplog_tx ON operations_log(tx_id);

CREATE TABLE IF NOT EXISTS pending_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products_cache (
    canon TEXT PRIMARY KEY,
    aliases_json TEXT NOT NULL,
    default_unit TEXT,
    retail_price_kopecks INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS locations_cache (
    canon TEXT PRIMARY KEY,
    aliases_json TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS categories_cache (
    name TEXT PRIMARY KEY,
    is_active INTEGER NOT NULL DEFAULT 1,
    triggers_json TEXT,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unknown_units (
    unit TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS missed_reports (
    report_date TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS pin_attempts (
    user_id TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pin_user ON pin_attempts(user_id, attempted_at DESC);
