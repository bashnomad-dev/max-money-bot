"""CRUD-репозитории над SQLite. Тонкие методы без бизнес-логики.

Бизнес-логика (идемпотентность, семантический дедуп, выбор UX-ветки) — в src/dialog/
и хендлерах. Здесь только storage.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
# chat_sheets
# ============================================================

class ChatSheetsRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_sheet_id(self, chat_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT sheet_id FROM chat_sheets WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        return row["sheet_id"] if row else None

    def set_sheet_id(self, chat_id: str, sheet_id: str, user_id: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO chat_sheets (chat_id, sheet_id, linked_at, linked_by_user_id) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, sheet_id, _utcnow_iso(), user_id),
        )


# ============================================================
# idempotency_log
# ============================================================

class IdempotencyRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def seen(self, message_id: str) -> str | None:
        """Возвращает прошлый result если message_id уже обработан, иначе None."""
        row = self._conn.execute(
            "SELECT result FROM idempotency_log WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        return row["result"] if row else None

    def mark(self, message_id: str, chat_id: str, user_id: str, result: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO idempotency_log "
            "(message_id, chat_id, user_id, processed_at, result) VALUES (?, ?, ?, ?, ?)",
            (message_id, chat_id, user_id, _utcnow_iso(), result),
        )

    def gc_older_than_days(self, days: int = 30) -> int:
        cutoff = (_utcnow() - timedelta(days=days)).isoformat(timespec="seconds")
        cur = self._conn.execute(
            "DELETE FROM idempotency_log WHERE processed_at < ?", (cutoff,)
        )
        return cur.rowcount


# ============================================================
# dedup_window (семантическая дедупликация)
# ============================================================

class DedupRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def find(self, semantic_hash: str, chat_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM dedup_window WHERE semantic_hash = ? AND chat_id = ? "
            "AND expires_at > ?",
            (semantic_hash, chat_id, _utcnow_iso()),
        ).fetchone()
        return dict(row) if row else None

    def insert(
        self,
        semantic_hash: str,
        chat_id: str,
        operation_summary: str,
        sheet_row_refs: list[dict[str, Any]],
        ttl_minutes: int,
    ) -> None:
        now = _utcnow()
        self._conn.execute(
            "INSERT OR REPLACE INTO dedup_window "
            "(semantic_hash, chat_id, created_at, operation_summary, sheet_row_refs, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                semantic_hash,
                chat_id,
                now.isoformat(timespec="seconds"),
                operation_summary,
                json.dumps(sheet_row_refs, ensure_ascii=False),
                (now + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds"),
            ),
        )

    def gc_expired(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM dedup_window WHERE expires_at <= ?", (_utcnow_iso(),)
        )
        return cur.rowcount


# ============================================================
# dialog_state (stateful-диалоги)
# ============================================================

class DialogRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, chat_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM dialog_state WHERE chat_id = ? AND expires_at > ?",
            (chat_id, _utcnow_iso()),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["partial_data"] = json.loads(d["partial_data_json"])
        return d

    def set(
        self,
        chat_id: str,
        intent: str,
        partial_data: dict[str, Any],
        ttl_minutes: int,
        awaiting_field: str | None = None,
    ) -> None:
        now = _utcnow()
        self._conn.execute(
            "INSERT OR REPLACE INTO dialog_state "
            "(chat_id, intent, awaiting_field, partial_data_json, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                intent,
                awaiting_field,
                json.dumps(partial_data, ensure_ascii=False, default=str),
                now.isoformat(timespec="seconds"),
                (now + timedelta(minutes=ttl_minutes)).isoformat(timespec="seconds"),
            ),
        )

    def clear(self, chat_id: str) -> None:
        self._conn.execute("DELETE FROM dialog_state WHERE chat_id = ?", (chat_id,))

    def gc_expired(self) -> int:
        cur = self._conn.execute(
            "DELETE FROM dialog_state WHERE expires_at <= ?", (_utcnow_iso(),)
        )
        return cur.rowcount


# ============================================================
# operations_log (для /undo и аудита)
# ============================================================

class OperationsLogRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def log(
        self,
        chat_id: str,
        user_id: str,
        message_id: str,
        tx_id: str,
        op_kind: str,
        sheet_refs: list[dict[str, Any]],
        summary: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO operations_log "
            "(chat_id, user_id, message_id, tx_id, op_kind, sheet_refs, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                user_id,
                message_id,
                tx_id,
                op_kind,
                json.dumps(sheet_refs, ensure_ascii=False),
                summary,
                _utcnow_iso(),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def last(self, chat_id: str) -> dict[str, Any] | None:
        """Последняя НЕ отменённая операция в чате."""
        row = self._conn.execute(
            "SELECT * FROM operations_log WHERE chat_id = ? AND undone_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["sheet_refs"] = json.loads(d["sheet_refs"])
        return d

    def last_n(self, chat_id: str, n: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM operations_log WHERE chat_id = ? AND undone_at IS NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (chat_id, n),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["sheet_refs"] = json.loads(d["sheet_refs"])
            result.append(d)
        return result

    def mark_undone(self, op_id: int) -> None:
        self._conn.execute(
            "UPDATE operations_log SET undone_at = ? WHERE id = ?",
            (_utcnow_iso(), op_id),
        )

    def get_by_tx_id(self, tx_id: str) -> list[dict[str, Any]]:
        """Все записи с данным tx_id (для combo-операций, использующих один tx_id)."""
        rows = self._conn.execute(
            "SELECT * FROM operations_log WHERE tx_id = ? ORDER BY id ASC",
            (tx_id,),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["sheet_refs"] = json.loads(d["sheet_refs"])
            result.append(d)
        return result


# ============================================================
# pending_writes (очередь при сбое Sheets)
# ============================================================

class PendingWritesRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def enqueue(self, chat_id: str, payload: dict[str, Any], error: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO pending_writes (chat_id, payload_json, attempts, last_attempt_at, "
            "last_error, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                chat_id,
                json.dumps(payload, ensure_ascii=False, default=str),
                1,
                _utcnow_iso(),
                error,
                _utcnow_iso(),
            ),
        )
        return cur.lastrowid  # type: ignore[return-value]

    def list_ready(self, max_attempts: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM pending_writes WHERE attempts < ? ORDER BY created_at ASC",
            (max_attempts,),
        ).fetchall()
        return [
            {**dict(r), "payload": json.loads(r["payload_json"])} for r in rows
        ]

    def mark_attempt(self, pid: int, error: str | None) -> None:
        self._conn.execute(
            "UPDATE pending_writes SET attempts = attempts + 1, last_attempt_at = ?, "
            "last_error = ? WHERE id = ?",
            (_utcnow_iso(), error, pid),
        )

    def delete(self, pid: int) -> None:
        self._conn.execute("DELETE FROM pending_writes WHERE id = ?", (pid,))


# ============================================================
# Кеши справочников (products / locations / categories)
# ============================================================

class ProductsCacheRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(
        self,
        canon: str,
        aliases: list[str],
        default_unit: str | None,
        retail_price_kopecks: int | None,
        is_active: bool = True,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO products_cache "
            "(canon, aliases_json, default_unit, retail_price_kopecks, is_active, last_synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                canon,
                json.dumps(aliases, ensure_ascii=False),
                default_unit,
                retail_price_kopecks,
                1 if is_active else 0,
                _utcnow_iso(),
            ),
        )

    def all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM products_cache WHERE is_active = 1"
        ).fetchall()
        return [
            {**dict(r), "aliases": json.loads(r["aliases_json"])} for r in rows
        ]

    def add_alias(self, canon: str, alias: str) -> None:
        """Добавить alias к существующему канону (для канонизации с подтверждением)."""
        row = self._conn.execute(
            "SELECT aliases_json FROM products_cache WHERE canon = ?", (canon,)
        ).fetchone()
        if not row:
            return
        aliases = json.loads(row["aliases_json"])
        if alias not in aliases:
            aliases.append(alias)
            self._conn.execute(
                "UPDATE products_cache SET aliases_json = ?, last_synced_at = ? WHERE canon = ?",
                (json.dumps(aliases, ensure_ascii=False), _utcnow_iso(), canon),
            )


class LocationsCacheRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, canon: str, aliases: list[str]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO locations_cache (canon, aliases_json, last_synced_at) "
            "VALUES (?, ?, ?)",
            (canon, json.dumps(aliases, ensure_ascii=False), _utcnow_iso()),
        )


class CategoriesCacheRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, name: str, is_active: bool, triggers: list[str]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO categories_cache "
            "(name, is_active, triggers_json, last_synced_at) VALUES (?, ?, ?, ?)",
            (
                name,
                1 if is_active else 0,
                json.dumps(triggers, ensure_ascii=False),
                _utcnow_iso(),
            ),
        )


class UnknownUnitsRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def bump(self, unit: str) -> None:
        existing = self._conn.execute(
            "SELECT occurrences FROM unknown_units WHERE unit = ?", (unit,)
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE unknown_units SET occurrences = occurrences + 1 WHERE unit = ?",
                (unit,),
            )
        else:
            self._conn.execute(
                "INSERT INTO unknown_units (unit, first_seen_at, occurrences) VALUES (?, ?, 1)",
                (unit, _utcnow_iso()),
            )


class PinAttemptsRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, user_id: str, success: bool) -> None:
        self._conn.execute(
            "INSERT INTO pin_attempts (user_id, attempted_at, success) VALUES (?, ?, ?)",
            (user_id, _utcnow_iso(), 1 if success else 0),
        )

    def failed_count_recent(self, user_id: str, lockout_minutes: int) -> int:
        cutoff = (_utcnow() - timedelta(minutes=lockout_minutes)).isoformat(
            timespec="seconds"
        )
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM pin_attempts WHERE user_id = ? AND success = 0 "
            "AND attempted_at > ?",
            (user_id, cutoff),
        ).fetchone()
        return int(row["n"])

    def is_locked_out(self, user_id: str, max_attempts: int, lockout_minutes: int) -> bool:
        return self.failed_count_recent(user_id, lockout_minutes) >= max_attempts
