"""Канонизация точек. У Евгения 2 — «Магазин Зинино» и «Магазин Кармалы».

Сопоставление по корню (зинин* / кармал*) с учётом частых опечаток и распознавания.
Достаточно для двух точек.
"""
from __future__ import annotations

from src.domain.operation import Location

# Корни и частые искажения. Без сверхкоротких ключей («зин», «карм»),
# чтобы не ловить ложно слово «магазин».
_LOCATION_KEYWORDS: dict[str, Location] = {
    "зинин": Location.ZININO,
    "зенин": Location.ZININO,   # типичная ошибка распознавания
    "зинен": Location.ZININO,
    "кармал": Location.KARMALY,
    "кормал": Location.KARMALY,   # типичная ошибка
    "карамал": Location.KARMALY,  # «карамалы» — частая опечатка
    "каромал": Location.KARMALY,
}


def canonicalize_location(text: str | None) -> Location | None:
    """Сопоставить произвольный ввод (с опечатками) с точкой. None — не распознано."""
    if not text:
        return None
    lower = text.strip().lower().replace("ё", "е")
    # Убираем слово «магазин», чтобы оно не мешало матчу корней.
    lower = lower.replace("магазин", " ")
    for keyword, loc in _LOCATION_KEYWORDS.items():
        if keyword in lower:
            return loc
    return None
