"""Логирование входящего user_id и отклонения доступа (whitelist)."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

from src.bot import access as access_mod
from src.bot import handlers as handlers_mod


class _FakeClient:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def reply(self, message, text):  # noqa: ANN001
        self.replies.append(text)


def _message(user_id: int | str):
    return SimpleNamespace(sender=SimpleNamespace(user_id=user_id))


def _get_start_handler(client):
    # ctx не нужен для handle_start — доступ проверяется до его использования.
    handlers = handlers_mod.make_handlers(client, ctx=object())
    return handlers["start"]


def test_denied_access_logs_user_id(monkeypatch, caplog):
    monkeypatch.setattr(access_mod.settings, "allowed_user_ids", "111")
    monkeypatch.setattr(handlers_mod.settings, "silent_reject", False, raising=False)

    client = _FakeClient()
    handle_start = _get_start_handler(client)

    with caplog.at_level(logging.INFO, logger=handlers_mod.log.name):
        asyncio.run(handle_start(_message(999)))

    assert "access denied" in caplog.text
    assert "999" in caplog.text
    # пользователь получил отказ, START_MSG не отправлен
    assert client.replies and "999" not in client.replies[0]


def test_allowed_access_logs_user_id(monkeypatch, caplog):
    monkeypatch.setattr(access_mod.settings, "allowed_user_ids", "111")

    client = _FakeClient()
    handle_start = _get_start_handler(client)

    with caplog.at_level(logging.INFO, logger=handlers_mod.log.name):
        asyncio.run(handle_start(_message(111)))

    assert "access granted" in caplog.text
    assert "111" in caplog.text
