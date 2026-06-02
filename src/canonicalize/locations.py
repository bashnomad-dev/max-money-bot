"""Канонизация точек. У Евгения 2 — «Магазин Зинино» и «Магазин Кармалы».

Простое сопоставление по корню (зинин* / кармал*). Достаточно для двух точек.
"""
from __future__ import annotations

from src.domain.operation import Location

_LOCATION_KEYWORDS: dict[str, Location] = {
    "зинин": Location.ZININO,
    "зенин": Location.ZININO,  # типичная ошибка распознавания
    "зин": Location.ZININO,    # совсем сокращённый
    "кармал": Location.KARMALY,
    "кормал": Location.KARMALY,  # типичная ошибка
    "карм": Location.KARMALY,
}


def canonicalize_location(text: str | None) -> Location | None:
    if not text:
        return None
    lower = text.strip().lower().replace("ё", "е")
    for keyword, loc in _LOCATION_KEYWORDS.items():
        if keyword in lower:
            return loc
    return None
