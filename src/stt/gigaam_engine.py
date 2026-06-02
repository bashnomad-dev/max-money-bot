"""GigaAM-обёртка. Локальная модель Сбера — бесплатно, без сети.

Требования:
  - gigaam (PyPI)
  - torch
  - ffmpeg в PATH (для конвертации в WAV 16kHz mono)
  - На первом запуске — скачивание модели (~1 GB)

См. https://github.com/salute-developers/GigaAM
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path

from src.config.settings import settings
from src.stt.base import STTError

log = logging.getLogger(__name__)

# Модель GigaAM загружается лениво (один раз на процесс).
_model = None


def _load_model():
    global _model
    if _model is None:
        try:
            import gigaam  # type: ignore
        except ImportError as e:
            raise STTError(
                "Не установлен пакет gigaam. pip install gigaam (требует torch и ffmpeg)."
            ) from e
        log.info("Загружаю модель GigaAM: %s", settings.gigaam_model)
        _model = gigaam.load_model(settings.gigaam_model)
    return _model


def _ensure_wav16k_mono(src: Path) -> Path:
    """Сконвертировать любой формат в WAV 16kHz mono через ffmpeg."""
    if src.suffix.lower() == ".wav":
        return src
    dst = Path(tempfile.gettempdir()) / f"{src.stem}_16k.wav"
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except FileNotFoundError as e:
        raise STTError("ffmpeg не найден в PATH. Установи его и повтори.") from e
    except subprocess.CalledProcessError as e:
        raise STTError(f"ffmpeg ошибка: {e.stderr.decode('utf-8', errors='replace')}") from e
    return dst


class GigaAMEngine:
    name = "gigaam"

    async def transcribe(self, audio_path: Path) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> str:
        wav_path = _ensure_wav16k_mono(audio_path)
        model = _load_model()
        try:
            result = model.transcribe(str(wav_path))
        except Exception as e:  # noqa: BLE001
            raise STTError(f"GigaAM transcribe failed: {e}") from e
        if isinstance(result, dict):
            return result.get("text", "").strip()
        return str(result).strip()
