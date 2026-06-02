"""Whisper API fallback (OpenAI). Используется если GigaAM недоступен или упал."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.config.settings import settings
from src.stt.base import STTError

log = logging.getLogger(__name__)


class WhisperEngine:
    name = "whisper"

    def __init__(self) -> None:
        if not settings.openai_api_key:
            raise STTError("OPENAI_API_KEY не задан для Whisper fallback")
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as e:
            raise STTError("pip install openai") from e
        self._client = OpenAI(api_key=settings.openai_api_key)

    async def transcribe(self, audio_path: Path) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> str:
        with audio_path.open("rb") as f:
            try:
                resp = self._client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language="ru",
                )
            except Exception as e:  # noqa: BLE001
                raise STTError(f"Whisper API error: {e}") from e
        return resp.text.strip()
