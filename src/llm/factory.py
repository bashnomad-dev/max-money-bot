"""Выбор реализации LLMParser по настройкам.

Управляется env:
  LLM_BACKEND=gigachat | openrouter | claude
  LLM_BACKEND_FALLBACK=gigachat | openrouter | claude    (опц., кросс-backend fallback)
"""
from __future__ import annotations

from src.config.settings import settings
from src.llm.base import LLMParser


def _build(backend: str) -> LLMParser:
    backend = backend.lower().strip()
    if backend == "gigachat":
        from src.llm.gigachat_parser import GigaChatParser
        return GigaChatParser()
    if backend == "openrouter":
        from src.llm.openrouter_parser import OpenRouterParser
        return OpenRouterParser()
    if backend == "claude":
        raise NotImplementedError(
            "ClaudeParser (прямой Anthropic SDK) не реализован — используй "
            "LLM_BACKEND=openrouter с OPENROUTER_MODEL=anthropic/claude-haiku-4.5."
        )
    raise ValueError(f"Неизвестный LLM backend: {backend!r}")


def get_parser() -> LLMParser:
    return _build(settings.llm_backend)


def get_fallback_parser() -> LLMParser | None:
    """Парсер для кросс-backend fallback. None если не настроен."""
    fb = settings.llm_backend_fallback.strip()
    if not fb:
        return None
    return _build(fb)
