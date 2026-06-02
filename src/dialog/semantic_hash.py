"""Семантический хэш для дедупликации повторных операций (SPEC §8)."""
from __future__ import annotations

import hashlib

from src.domain.operation import (
    Cashflow,
    Purchase,
    Return,
    Sale,
    WriteoffOrMovement,
)


def semantic_hash(op) -> str:
    """Сгенерировать хэш по бизнес-смыслу операции.

    Сумма округляется до сотен рублей (защита от микроотклонений),
    количество товаров сохраняется без округления (избегаем false positives),
    товар нормализуется в lowercase.

    Для перемещений/cashflow возвращается уникальный хэш по типу+сумме+описанию.
    """
    if isinstance(op, Sale):
        return _hash(
            "sale",
            _round_to_hundreds(op.amount_kopecks),
            _norm_loc(op.location.value),
            _norm_str(op.customer or ""),
            _lines_signature(op.lines),
        )
    if isinstance(op, Purchase):
        return _hash(
            "purchase",
            _round_to_hundreds(op.amount_kopecks),
            _norm_loc(op.destination.value),
            _norm_str(op.supplier),
            _lines_signature(op.lines),
        )
    if isinstance(op, Return):
        return _hash(
            "return",
            op.direction.value,
            _round_to_hundreds(op.amount_kopecks),
            _norm_loc(op.location.value),
            _norm_str(op.counterparty),
            _lines_signature(op.lines),
        )
    if isinstance(op, Cashflow):
        loc = op.location.value if op.location else ""
        return _hash(
            "cashflow",
            op.op_type.value,
            _round_to_hundreds(op.amount_kopecks),
            _norm_str(op.description),
            _norm_loc(loc),
        )
    if isinstance(op, WriteoffOrMovement):
        loc = op.location.value if op.location else ""
        src = op.source.value if op.source else ""
        dst = op.destination.value if op.destination else ""
        return _hash(
            "wom",
            op.op_type.value,
            _norm_loc(loc),
            _norm_loc(src),
            _norm_loc(dst),
            _lines_signature(op.lines),
        )
    # Для остальных типов (Inventory, query, clarification) дедуп не имеет смысла
    return _hash("other", str(op))


def _hash(*parts) -> str:
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _round_to_hundreds(kopecks: int) -> int:
    """Округление до сотен рублей: 18500 → 18500, 18540 → 18500, 18570 → 18600."""
    rub = kopecks // 100
    return (rub // 100) * 100


def _norm_str(s: str) -> str:
    return s.strip().lower().replace("ё", "е")


def _norm_loc(s: str) -> str:
    return _norm_str(s)


def _lines_signature(lines: list) -> str:
    parts = []
    for ln in lines:
        # qty без округления чтобы 1.5 и 1.5 совпали, а 1.5 и 1.6 — нет
        parts.append(f"{_norm_str(ln.name)}|{ln.qty}|{_norm_str(ln.unit)}")
    return ";".join(sorted(parts))
