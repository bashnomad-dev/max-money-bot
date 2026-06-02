"""MAX-бот: клиент, контекст, хендлеры, роутер."""
from src.bot.access import is_allowed
from src.bot.context import AppContext
from src.bot.handlers import make_handlers
from src.bot.max_client import MAXClient
from src.bot.pipeline import process_parsed
from src.bot.router import register_all

__all__ = [
    "AppContext",
    "MAXClient",
    "is_allowed",
    "make_handlers",
    "process_parsed",
    "register_all",
]
