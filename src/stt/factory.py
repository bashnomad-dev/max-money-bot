"""Выбор STT-движка по env STT_ENGINE (+ опциональный фолбэк STT_FALLBACK)."""
from __future__ import annotations

import logging
from pathlib import Path

from src.config.settings import settings
from src.stt.base import STTEngine

log = logging.getLogger(__name__)


def _build_one(name: str) -> STTEngine:
    name = name.lower()
    if name == "gigaam":
        from src.stt.gigaam_engine import GigaAMEngine
        return GigaAMEngine()
    if name == "whisper":
        from src.stt.whisper_engine import WhisperEngine
        return WhisperEngine()
    raise ValueError(f"Неизвестный STT-движок: {name!r}")


class FallbackSTTEngine:
    """Основной движок + запасной. Если основной упал или вернул пусто — пробуем запасной.

    Закрывает кейс с ДЕМО, когда STT отвалился и бот ответил «технические работы».
    """

    def __init__(self, primary: STTEngine, fallback: STTEngine) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def name(self) -> str:
        return f"{self._primary.name}+{self._fallback.name}"

    async def transcribe(self, audio_path: Path) -> str:
        try:
            text = await self._primary.transcribe(audio_path)
            if text:
                return text
            log.warning("STT %s вернул пусто — пробую %s", self._primary.name, self._fallback.name)
        except Exception:  # noqa: BLE001
            log.exception("STT %s упал — пробую %s", self._primary.name, self._fallback.name)
        return await self._fallback.transcribe(audio_path)


def get_engine() -> STTEngine:
    primary = _build_one(settings.stt_engine)

    fb = settings.stt_fallback.strip().lower()
    if fb and fb != settings.stt_engine.lower():
        try:
            fallback = _build_one(fb)
        except Exception as e:  # noqa: BLE001
            log.warning("STT-фолбэк %s недоступен (%s) — работаю только на %s", fb, e, primary.name)
            return primary
        return FallbackSTTEngine(primary, fallback)

    return primary
