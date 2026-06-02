"""Адаптер над maxapi 1.x.

Цели:
  - инкапсулировать Bot/Dispatcher из maxapi (ленивая инициализация);
  - дать handlers.py одинаковый API send_message / reply / react / download_voice
    независимо от деталей пакета;
  - не пускать наружу типы maxapi там, где можно обойтись dict-подобными атрибутами.

В хендлеры приходит maxapi.types.Message (см. router.py — мы разворачиваем
MessageCreated → message). Это удобно: handlers.py обращается к
`message.body.text`, `message.recipient.chat_id`, `message.reply(...)`, и т.п.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.config.settings import settings

log = logging.getLogger(__name__)


class MAXClient:
    """Тонкая обёртка над maxapi.Bot + maxapi.Dispatcher."""

    def __init__(self) -> None:
        self._bot: Any = None
        self._dispatcher: Any = None
        if not settings.max_bot_token:
            raise RuntimeError("MAX_BOT_TOKEN не задан в .env")

    def _init_bot(self) -> None:
        if self._bot is not None:
            return
        try:
            from maxapi import Bot, Dispatcher  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "Не установлен пакет maxapi. pip install maxapi"
            ) from e
        self._bot = Bot(token=settings.max_bot_token)
        self._dispatcher = Dispatcher()

    @property
    def bot(self) -> Any:
        self._init_bot()
        return self._bot

    @property
    def dispatcher(self) -> Any:
        self._init_bot()
        return self._dispatcher

    # ===== Outgoing =====

    async def send_message(self, chat_id: int | str, text: str) -> None:
        try:
            cid = int(chat_id)
        except (TypeError, ValueError):
            log.error("Не могу преобразовать chat_id=%r к int", chat_id)
            return
        await self.bot.send_message(chat_id=cid, text=text)

    async def reply(self, message: Any, text: str) -> None:
        """Ответ конкретному сообщению. Падает обратно на send_message если body=None."""
        try:
            await message.reply(text)
            return
        except Exception:  # noqa: BLE001
            log.exception("reply failed, fallback to send_message")
        try:
            chat_id = message.recipient.chat_id
            if chat_id is not None:
                await self.send_message(chat_id, text)
        except Exception:  # noqa: BLE001
            log.exception("send_message fallback тоже упал")

    async def react(self, message: Any, emoji: str = "✅") -> bool:
        """В MAX Bot API 1.x реакций на сообщения нет.

        Возвращаем False — caller сделает текстовый fallback («✅ записал»).
        """
        return False

    # ===== Voice =====

    async def download_voice(self, message: Any, dst_dir: Path) -> Path:
        """Скачать первое аудиовложение сообщения в локальный файл.

        В maxapi 1.x аудио в `message.body.attachments` приходит как `Audio` с
        полем `payload.url` (см. types/attachments/{audio,attachment}.py).
        Скачиваем через httpx — никаких SDK-вызовов не нужно.
        """
        import httpx

        atts = getattr(getattr(message, "body", None), "attachments", None) or []
        url: str | None = None
        for a in atts:
            payload = getattr(a, "payload", None)
            u = getattr(payload, "url", None)
            t = str(getattr(a, "type", "") or "").lower()
            if u and ("audio" in t or t == ""):
                url = u
                break
        if not url:
            raise RuntimeError("В сообщении нет аудиовложения")

        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / "voice.bin"
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(url)
            r.raise_for_status()
            dst.write_bytes(r.content)
        return dst

    # ===== Polling =====

    async def start_polling(self) -> None:
        await self.dispatcher.start_polling(self.bot)

    async def close(self) -> None:
        if self._bot is not None and hasattr(self._bot, "close_session"):
            try:
                await self._bot.close_session()
            except Exception:  # noqa: BLE001
                log.exception("close_session упал — продолжаю")
