"""SQLite-слой: соединение, схема, репозитории."""
from src.storage.db import connect, init_schema, open_initialized
from src.storage.repositories import (
    CategoriesCacheRepo,
    ChatSheetsRepo,
    DedupRepo,
    DialogRepo,
    IdempotencyRepo,
    LocationsCacheRepo,
    OperationsLogRepo,
    PendingWritesRepo,
    PinAttemptsRepo,
    ProductsCacheRepo,
    UnknownUnitsRepo,
)

__all__ = [
    "CategoriesCacheRepo",
    "ChatSheetsRepo",
    "DedupRepo",
    "DialogRepo",
    "IdempotencyRepo",
    "LocationsCacheRepo",
    "OperationsLogRepo",
    "PendingWritesRepo",
    "PinAttemptsRepo",
    "ProductsCacheRepo",
    "UnknownUnitsRepo",
    "connect",
    "init_schema",
    "open_initialized",
]
