"""Stateful-диалог: входная операция + текущее состояние → решение.

Решает по правилам SPEC §9.1:
  1. Новая точка / товар не из каталога → CANONICALIZE.
  2. Сумма > LARGE_AMOUNT_THRESHOLD_RUB → CARD (карточка перед записью).
  3. Семантический хэш найден в dedup_window → DEDUP_CHECK.
  4. critical_confidence: ≥ AUTO → WRITE; ≥ CLARIFY → CARD; иначе CLARIFY.

Не выполняет I/O, только принимает решение. Хендлер MAX вызывает соответствующие
действия по результату.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.config.settings import settings
from src.dialog.semantic_hash import semantic_hash
from src.domain.operation import (
    Cashflow,
    ClarificationNeeded,
    Inventory,
    PeriodReportRequest,
    Purchase,
    Return,
    Sale,
    StockQuery,
    WriteoffOrMovement,
)


class DialogStep(StrEnum):
    WRITE = "write"                    # запись сразу + ✅
    CARD = "card"                      # показать карточку до записи
    DEDUP_CHECK = "dedup_check"        # подозрение на повтор
    CANONICALIZE = "canonicalize"      # новая точка/товар
    CLARIFY = "clarify"                # уточняющий вопрос
    QUERY = "query"                    # запрос остатков
    REPORT = "report"                  # отчёт за период
    LARGE_AMOUNT_CARD = "large_card"   # карточка для крупной суммы


@dataclass
class DialogResult:
    step: DialogStep
    op: Any                          # ParsedCommand
    semantic_hash: str | None = None
    dedup_match: dict | None = None
    message: str | None = None       # текст для отправки пользователю


class DialogEngine:
    def __init__(
        self,
        known_product_canons: set[str] | None = None,
        known_locations: set[str] | None = None,
    ) -> None:
        self._known_products = known_product_canons or set()
        self._known_locations = known_locations or set()

    def update_caches(
        self,
        known_product_canons: set[str] | None = None,
        known_locations: set[str] | None = None,
    ) -> None:
        if known_product_canons is not None:
            self._known_products = known_product_canons
        if known_locations is not None:
            self._known_locations = known_locations

    def decide(self, op: Any, existing_dedup_match: dict | None = None) -> DialogResult:
        """Определить, что делать с разобранной командой."""
        # 1. Уточнения и запросы — отдельные ветки
        if isinstance(op, ClarificationNeeded):
            return DialogResult(step=DialogStep.CLARIFY, op=op, message=op.question)
        if isinstance(op, StockQuery):
            return DialogResult(step=DialogStep.QUERY, op=op)
        if isinstance(op, PeriodReportRequest):
            return DialogResult(step=DialogStep.REPORT, op=op)

        # 2. Канонизация: новые товары или новые точки
        # (только для операций с lines или location)
        if hasattr(op, "lines") and op.lines:
            for line in op.lines:
                if line.name and line.name.lower() not in self._known_products:
                    # Просто отмечаем сценарий; конкретный кандидат подбирается в хендлере
                    # через ProductCatalog.lookup
                    return DialogResult(step=DialogStep.CANONICALIZE, op=op)

        # 3. Крупная сумма
        amount_kopecks = getattr(op, "amount_kopecks", 0)
        if amount_kopecks and amount_kopecks > settings.large_amount_threshold_kopecks:
            return DialogResult(step=DialogStep.LARGE_AMOUNT_CARD, op=op)

        # 4. Семантический дедуп
        if isinstance(op, (Sale, Purchase, Return, Cashflow, WriteoffOrMovement)):
            shash = semantic_hash(op)
            if existing_dedup_match:
                return DialogResult(
                    step=DialogStep.DEDUP_CHECK,
                    op=op,
                    semantic_hash=shash,
                    dedup_match=existing_dedup_match,
                )
        else:
            shash = None

        # 5. Confidence
        conf = getattr(op, "confidence", None)
        if conf is None:
            return DialogResult(step=DialogStep.WRITE, op=op, semantic_hash=shash)

        critical = conf.critical
        if critical < settings.clarification_threshold:
            return DialogResult(
                step=DialogStep.CLARIFY,
                op=op,
                message="Я не уверен в распознавании. Уточни, пожалуйста, что записать.",
            )
        if critical < settings.auto_write_confidence_threshold:
            return DialogResult(step=DialogStep.CARD, op=op, semantic_hash=shash)
        return DialogResult(step=DialogStep.WRITE, op=op, semantic_hash=shash)
