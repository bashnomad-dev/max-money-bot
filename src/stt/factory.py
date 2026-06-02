"""Выбор STT-движка по env STT_ENGINE."""
from __future__ import annotations

from src.config.settings import settings
from src.stt.base import STTEngine


def get_engine() -> STTEngine:
    engine = settings.stt_engine.lower()
    if engine == "gigaam":
        from src.stt.gigaam_engine import GigaAMEngine
        return GigaAMEngine()
    if engine == "whisper":
        from src.stt.whisper_engine import WhisperEngine
        return WhisperEngine()
    raise ValueError(f"Неизвестный STT_ENGINE: {engine!r}")
