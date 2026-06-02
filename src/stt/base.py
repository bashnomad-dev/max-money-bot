"""Интерфейс STT-движка."""
from pathlib import Path
from typing import Protocol


class STTError(Exception):
    """Ошибка распознавания (неподдерживаемый формат, обрыв, API недоступен)."""


class STTEngine(Protocol):
    """Распознавание речи: аудиофайл → текст на русском."""

    async def transcribe(self, audio_path: Path) -> str:
        ...

    @property
    def name(self) -> str:
        """Идентификатор движка для логов: 'gigaam' | 'whisper'."""
        ...
