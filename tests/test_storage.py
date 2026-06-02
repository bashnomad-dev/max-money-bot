"""Smoke-тесты SQLite-слоя (репозитории)."""
import tempfile
from pathlib import Path

import pytest

from src.storage import (
    DedupRepo,
    DialogRepo,
    IdempotencyRepo,
    OperationsLogRepo,
    open_initialized,
)


@pytest.fixture
def conn():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "test.sqlite3"
        c = open_initialized(str(db))
        yield c
        c.close()


def test_idempotency_log(conn):
    repo = IdempotencyRepo(conn)
    assert repo.seen("m1") is None
    repo.mark("m1", "chat1", "user1", "written")
    assert repo.seen("m1") == "written"


def test_dedup_window(conn):
    repo = DedupRepo(conn)
    assert repo.find("h1", "chat1") is None
    repo.insert("h1", "chat1", "продажа 18к", [{"sheet": "Деньги", "row": 5}], ttl_minutes=5)
    found = repo.find("h1", "chat1")
    assert found is not None
    assert found["operation_summary"] == "продажа 18к"


def test_dialog_state_set_get_clear(conn):
    repo = DialogRepo(conn)
    assert repo.get("chat1") is None
    repo.set("chat1", "clarify_sale", {"amount": 18000}, ttl_minutes=5, awaiting_field="товар")
    st = repo.get("chat1")
    assert st is not None
    assert st["intent"] == "clarify_sale"
    assert st["partial_data"]["amount"] == 18000
    assert st["awaiting_field"] == "товар"
    repo.clear("chat1")
    assert repo.get("chat1") is None


def test_operations_log_and_undo(conn):
    repo = OperationsLogRepo(conn)
    op_id = repo.log("chat1", "user1", "msg1", "tx_abc12345", "sale",
                    [{"sheet": "Д", "row": 5}, {"sheet": "Т", "row": 12}],
                    "продажа 18000 цемент 30 меш.")
    last = repo.last("chat1")
    assert last is not None
    assert last["tx_id"] == "tx_abc12345"
    assert len(last["sheet_refs"]) == 2
    repo.mark_undone(op_id)
    assert repo.last("chat1") is None

    # /last N — отменённые не показываются
    assert repo.last_n("chat1", 5) == []


def test_get_by_tx_id_combo(conn):
    """Несколько строк с одним tx_id (для combo-операций)."""
    repo = OperationsLogRepo(conn)
    repo.log("chat1", "user1", "msg1", "tx_combo01", "money", [{"sheet": "Д", "row": 5}], "ден")
    repo.log("chat1", "user1", "msg1", "tx_combo01", "goods", [{"sheet": "Т", "row": 8}], "тов")
    by_tx = repo.get_by_tx_id("tx_combo01")
    assert len(by_tx) == 2
