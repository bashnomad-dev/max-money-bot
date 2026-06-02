"""Регистрация всех handler в MAX dispatcher."""
from __future__ import annotations

from src.bot.context import AppContext
from src.bot.handlers import make_handlers
from src.bot.max_client import MAXClient


def register_all(client: MAXClient, ctx: AppContext) -> None:
    """Зарегистрировать все команды и хендлеры голос/текст."""
    handlers = make_handlers(client, ctx)

    # Команды
    for cmd in ("start", "help", "version", "link", "setup", "today", "last",
                "undo", "cancel", "stock", "locations", "products"):
        client.register_message_handler(handlers[cmd], commands=[cmd])

    # Голос
    client.register_message_handler(handlers["voice"], content_types=["voice"])

    # Любой текст без команды (последний — фолбэк)
    client.register_message_handler(handlers["text"], content_types=["text"])
