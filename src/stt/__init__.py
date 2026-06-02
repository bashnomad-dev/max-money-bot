"""Speech-to-text. Основной — GigaAM (локально). Fallback — Whisper API."""
from src.stt.base import STTEngine, STTError
from src.stt.factory import get_engine

__all__ = ["STTEngine", "STTError", "get_engine"]
