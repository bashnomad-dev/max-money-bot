"""Выбор реализации LLMParser по настройкам.

Управляется env:
  LLM_BACKEND=gigachat | claude   (основной)
  LLM_BACKEND_FALLBACK=claude     (опц., для кросс-backend fallback при low confidence)
"""
from __future__ import annotations

from src.config.settings import settings
from src.llm.base import LLMParser


def get_parser() -> LLMParser:
    backend = settings.llm_backend.lower()
    if backend == "gigachat":
        from src.llm.gigachat_parser import GigaChatParser
        return GigaChatParser()
    if backend == "claude":
        # ClaudeParser реализуется позже (резерв; не приоритет для MVP под Евгения)
        raise NotImplementedError(
            "ClaudeParser ещё не реализован. На MVP используем GigaChat (LLM_BACKEND=gigachat). "
            "См. roadmap в docs/SPEC.md §14.3."
        )
    raise ValueError(f"Неизвестный LLM_BACKEND: {backend!r}")


def get_fallback_parser() -> LLMParser | None:
    """Парсер для кросс-backend fallback. None если не настроен."""
    fb = settings.llm_backend_fallback.lower().strip()
    if not fb:
        return None
    if fb == "claude":
        raise NotImplementedError("ClaudeParser fallback ещё не реализован.")
    if fb == "gigachat":
        from src.llm.gigachat_parser import GigaChatParser
        return GigaChatParser()
    raise ValueError(f"Неизвестный LLM_BACKEND_FALLBACK: {fb!r}")
