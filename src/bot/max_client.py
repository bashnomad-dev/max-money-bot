"""Тонкая обёртка над `maxapi` (Python SDK для MAX Bot API).

Все импорты maxapi — ленивые внутри методов, чтобы тесты могли импортировать
этот модуль без установленного пакета.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Coroutine

from src.config.settings import settings

log = logging.getLogger(__name__)


class MAXClient:
    """Простой адаптер: send/reply/react + регистрация хендлеров.

    API maxapi нативно похож на aiogram. Если в реальном пакете методы
    называются иначе — правим тут локально, остальной код не трогаем.
    """

    def __init__(self) -> None:
        self._bot = None
        self._dispatcher = None
        if not settings.max_bot_token:
            raise RuntimeError("MAX_BOT_TOKEN не задан в .env")

    def _init_bot(self):
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
    def bot(self):
        self._init_bot()
        return self._bot

    @property
    def dispatcher(self):
        self._init_bot()
        return self._dispatcher

    async def send_message(self, chat_id: str | int, text: str) -> None:
        await self.bot.send_message(chat_id=chat_id, text=text)

    async def reply(self, message, text: str) -> None:
        """Ответ на конкретное сообщение (с reply_to)."""
        try:
            await message.reply(text)
        except Exception:  # noqa: BLE001
            # fallback на send в чат, если reply API нет
            chat_id = getattr(message, "chat_id", None) or getattr(message.chat, "id", None)
            await self.send_message(chat_id, text)

    async def react(self, message, emoji: str = "✅") -> bool:
        """Поставить реакцию на сообщение. Возвращает True если успешно.

        Если в API maxapi нет реакций — возвращает False, вызывающий код
        делает fallback на короткий текстовый ответ.
        """
        # Пробуем разные потенциальные API
        for method_name in ("react", "set_reaction", "send_reaction"):
            method = getattr(message, method_name, None) or getattr(self.bot, method_name, None)
            if method is None:
                continue
            try:
                await method(emoji)
                return True
            except TypeError:
                # Возможно нужен другой сигнатурой
                try:
                    await method(message_id=message.message_id, emoji=emoji)
                    return True
                except Exception:  # noqa: BLE001
                    continue
            except Exception:  # noqa: BLE001
                log.exception("Не удалось поставить реакцию через %s", method_name)
                return False
        return False

    async def download_voice(self, message, dst_dir: Path) -> Path:
        """Скачать голосовое из MAX. Возвращает путь к файлу."""
        dst_dir.mkdir(parents=True, exist_ok=True)
        # Конкретный путь зависит от структуры message в maxapi.
        # По аналогии с aiogram: message.voice.file_id → bot.download(file_id, dst).
        file_id = (
            getattr(getattr(message, "voice", None), "file_id", None)
            or getattr(message, "file_id", None)
        )
        if not file_id:
            raise RuntimeError("Сообщение не содержит голосового вложения")
        dst = dst_dir / f"voice_{file_id}.ogg"
        # download API
        for method_name in ("download", "download_file", "get_file"):
            method = getattr(self.bot, method_name, None)
            if method is None:
                continue
            try:
                await method(file_id, destination=str(dst))
                return dst
            except TypeError:
                try:
                    file_obj = await method(file_id)
                    if hasattr(file_obj, "read"):
                        with dst.open("wb") as f:
                            f.write(file_obj.read())
                        return dst
                except Exception:  # noqa: BLE001
                    continue
        raise RuntimeError("Не удалось скачать голосовое — проверь API maxapi")

    def register_message_handler(
        self,
        handler: Callable[..., Coroutine[Any, Any, None]],
        commands: list[str] | None = None,
        content_types: list[str] | None = None,
    ) -> None:
        """Зарегистрировать хендлер. Сигнатура повторяет aiogram-стиль."""
        # В разных версиях maxapi регистрация может отличаться. Пробуем стандарт.
        if hasattr(self.dispatcher, "message_handler"):
            decorator = self.dispatcher.message_handler(
                commands=commands, content_types=content_types
            )
            decorator(handler)
        elif hasattr(self.dispatcher, "register_message_handler"):
            self.dispatcher.register_message_handler(
                handler, commands=commands, content_types=content_types
            )
        else:
            raise RuntimeError("maxapi.Dispatcher не имеет ожидаемого API регистрации хендлеров")

    async def start_polling(self) -> None:
        """Запуск long-polling."""
        if hasattr(self.dispatcher, "start_polling"):
            await self.dispatcher.start_polling(self.bot)
        else:
            raise RuntimeError("maxapi.Dispatcher не поддерживает start_polling")
