"""Соединение с SQLite + миграции (одна — schema.sql)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def connect(db_path: str) -> sqlite3.Connection:
    """Открыть SQLite-соединение с прагмами для производительности и параллельности."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL — нормальный режим параллельного доступа
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Применить schema.sql (idempotent — все CREATE с IF NOT EXISTS)."""
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)


def open_initialized(db_path: str) -> sqlite3.Connection:
    """Открыть соединение и сразу применить схему. Удобно для main и тестов."""
    conn = connect(db_path)
    init_schema(conn)
    return conn
