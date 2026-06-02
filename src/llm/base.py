"""Интерфейс LLM-парсера. Реализации: GigaChat (основная) и Claude (fallback).

Переключение через env LLM_BACKEND. Cм. docs/llm-parsing.md §6.
"""
from typing import Protocol

from src.domain.operation import ParsedCommand


class LLMError(Exception):
    """Базовая ошибка парсера. Подтипы: транспорт, парсинг, валидация."""


class LLMTransportError(LLMError):
    """Сеть, авторизация, недоступность API."""


class LLMParseError(LLMError):
    """Модель вернула что-то невалидное — не получилось привести к ParsedCommand."""


class LLMParser(Protocol):
    """Парсит распознанный текст в типизированную операцию.

    Контракт:
      - На вход: уже расшифрованный текст голосового (или текстовое сообщение).
      - На выход: один из ParsedCommand (Sale/Purchase/.../ClarificationNeeded).
      - При непреодолимой ошибке транспорта/парсинга — соответствующее исключение.
      - tx_id и occurred_at заполняет вызывающий код (не парсер).
    """

    async def parse(self, text: str) -> ParsedCommand:
        ...

    @property
    def name(self) -> str:
        """Идентификатор бэкенда для логов: 'gigachat' / 'claude'."""
        ...
