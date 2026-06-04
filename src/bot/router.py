"""Регистрация всех handler-ов в maxapi.Dispatcher.

Все обработчики получают `MessageCreated` (тип от maxapi). Мы разворачиваем
его в `Message` перед передачей в handler-ы из make_handlers — handlers.py
читает поля через `_chat_id`/`_user_id`/`_text`/`_message_id`, которые умеют
работать с реальной структурой `Message`.

Голос определяем по факту наличия аудиовложения. Команды (/start, /help, ...)
через фильтр maxapi.filters.Command. Любой остальной текст — fallback-handler.

Дедупликация: в редких случаях dispatcher может вызвать handler дважды (повтор
апдейта при ретрае long-poll, нестабильная сеть). Чтобы пользователь не получал
один и тот же ответ дважды, на входе в каждый wrap проверяем in-memory cache
по `(message_id)` с TTL ~120 сек.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

from src.bot.context import AppContext
from src.bot.handlers import make_handlers
from src.bot.max_client import MAXClient

log = logging.getLogger(__name__)

COMMANDS = (
    "start", "help", "version", "link", "setup",
    "today", "last", "undo", "edit", "cancel",
    "stock", "repair", "locations", "products",
)

# Русские алиасы к английским командам. MAX матчит команды простым сравнением
# строки (см. maxapi Command), кириллица работает. Английские оставляем — короче
# и надёжнее с раскладкой.
COMMAND_ALIASES: dict[str, tuple[str, ...]] = {
    "start": ("старт",),
    "help": ("помощь", "справка"),
    "version": ("версия",),
    "link": ("привязать",),
    "setup": ("настройка",),
    "today": ("сегодня",),
    "last": ("последние",),
    "undo": ("отмени", "отменить", "отмена", "откати", "откатить"),
    "edit": ("правка",),
    "cancel": ("сброс",),
    "stock": ("остаток", "остатки"),
    "repair": ("пересчёт", "пересчет"),
    "locations": ("точки",),
    "products": ("товары",),
}


class _MidDedup:
    """Простой in-memory дедуп message_id с TTL."""

    def __init__(self, ttl_sec: int = 120, capacity: int = 1024) -> None:
        self.ttl = ttl_sec
        self.cap = capacity
        self._seen: dict[str, float] = {}
        self._order: deque[str] = deque()

    def claim(self, mid: str) -> bool:
        """True если впервые видим mid (можно обрабатывать). False — дубль, скипаем."""
        if not mid:
            return True
        now = time.monotonic()
        # очистка просроченных
        while self._order and (now - self._seen.get(self._order[0], 0) > self.ttl):
            old = self._order.popleft()
            self._seen.pop(old, None)
        if mid in self._seen:
            return False
        self._seen[mid] = now
        self._order.append(mid)
        if len(self._order) > self.cap:
            old = self._order.popleft()
            self._seen.pop(old, None)
        return True


_dedup = _MidDedup()


def _mid_of(event: Any) -> str:
    try:
        return str(event.message.body.mid or "")
    except AttributeError:
        return ""


def register_all(client: MAXClient, ctx: AppContext) -> None:
    """Зарегистрировать все хендлеры в client.dispatcher."""
    from maxapi.filters.command import Command  # type: ignore

    handlers = make_handlers(client, ctx)
    dp = client.dispatcher

    # Команды: фильтр Command(commands=[...]). Каждая английская команда + её
    # русские алиасы вешаются на один и тот же handler.
    total = 0
    for cmd in COMMANDS:
        h = handlers[cmd]
        for name in (cmd, *COMMAND_ALIASES.get(cmd, ())):
            dp.message_created.register(_wrap(h, kind="cmd", name=name), Command(commands=[name]))
            total += 1

    # Любой message_created без команды → голос или текст
    dp.message_created.register(_wrap_voice_or_text(handlers, client))

    log.info("Зарегистрировано: %d команд (с алиасами) + voice/text fallback", total)


def _wrap(handler, *, kind: str, name: str):
    """Развернуть MessageCreated → Message и пробросить в handler, с дедупом mid."""
    async def _inner(event: Any) -> None:
        mid = _mid_of(event)
        if not _dedup.claim(f"{kind}:{name}:{mid}"):
            log.info("dedup: пропуск повторного апдейта mid=%s (%s/%s)", mid, kind, name)
            return
        try:
            message = event.message
        except AttributeError:
            log.warning("event без .message: %r", event)
            return
        try:
            await handler(message)
        except Exception:  # noqa: BLE001
            log.exception("handler %s/%s упал", kind, name)
    return _inner


def _wrap_voice_or_text(handlers: dict, client: MAXClient):
    """Один универсальный хендлер: команды отлавливаются отдельно, иначе голос или текст.

    Команды (/start и т.п.) отлавливаются регистрациями с Command-фильтром,
    здесь мы их сразу отбрасываем по префиксу `/`, чтобы не было «второго» ответа.
    """
    voice_h = handlers["voice"]
    text_h = handlers["text"]

    async def _inner(event: Any) -> None:
        mid = _mid_of(event)
        if not _dedup.claim(f"fallback:{mid}"):
            log.info("dedup: пропуск повторного апдейта mid=%s (fallback)", mid)
            return
        try:
            message = event.message
        except AttributeError:
            return

        body = getattr(message, "body", None)
        atts = getattr(body, "attachments", None) or []

        has_audio = any(
            ("audio" in str(getattr(a, "type", "") or "").lower())
            for a in atts
        )
        text = (getattr(body, "text", None) or "").strip()

        # Не дублируем команды (их уже обработал Command-фильтр)
        if text.startswith("/"):
            return

        try:
            if has_audio:
                await voice_h(message)
            elif text:
                await text_h(message)
        except Exception:  # noqa: BLE001
            log.exception("voice/text handler упал")

    return _inner
