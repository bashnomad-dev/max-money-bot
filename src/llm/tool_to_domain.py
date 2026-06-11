"""Маппинг tool_call (имя + arguments) → ParsedCommand.

Общий для всех LLM-бэкендов. Тут только валидация структуры и сборка pydantic-моделей.
Канонизация (точки/единицы/товары) — отдельный шаг после парсера.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from src.config.settings import settings
from src.domain.operation import (
    Cashflow,
    CashflowType,
    ClarificationNeeded,
    Confidence,
    ExpenseCategory,
    GoodsLine,
    Inventory,
    InventoryFact,
    Location,
    ParsedCommand,
    PaymentMethod,
    PeriodReportRequest,
    Purchase,
    ReportPeriodType,
    Return,
    ReturnDirection,
    Sale,
    StockQuery,
    TopMetric,
    WriteoffOrMovement,
    WriteoffOrMovementType,
)


def _conf(args: dict[str, Any], with_amount: bool = False, with_qty: bool = False) -> Confidence:
    return Confidence(
        text=float(args.get("text_confidence", 1.0)),
        amount=float(args.get("amount_confidence", 1.0)) if with_amount else 1.0,
        quantity=float(args.get("quantity_confidence", 1.0)) if with_qty else 1.0,
    )


def _lines(raw_lines: list[dict[str, Any]]) -> list[GoodsLine]:
    return [
        GoodsLine(
            name=str(r["name"]),
            qty=float(r["qty"]),
            unit=str(r["unit"]),
            price_per_unit_rub=(
                float(r["price_per_unit"]) if r.get("price_per_unit") is not None else None
            ),
            comment=r.get("comment"),
        )
        for r in raw_lines
    ]


_INVALID_LOC_MARKERS = {"<unknown>", "unknown", "null", "none", "не указано", "?", "—", "-"}


def _location(value: Any) -> Location | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in _INVALID_LOC_MARKERS:
        return None
    return Location(s)


def _ensure_location(value: Any, field_name: str, raw_text: str) -> Location | ClarificationNeeded:
    """Для обязательных полей location: вернуть валидную Location.

    Если значение пустое/невалидное — пробуем settings.default_location
    (режим «не переспрашивать точку»). Если дефолт не задан — ClarificationNeeded,
    и вызывающий код вернёт его как итог парсинга.
    """
    s = "" if value is None else str(value).strip()
    if s and s.lower() not in _INVALID_LOC_MARKERS:
        try:
            return Location(s)
        except ValueError:
            pass  # невалидная точка — попробуем дефолт ниже

    default = settings.default_location.strip()
    if default:
        try:
            return Location(default)
        except ValueError:
            pass  # дефолт настроен криво — переспросим

    return ClarificationNeeded(
        raw_text=raw_text,
        reason=f"Не указана {field_name}.",
        question="На какую точку: Магазин Зинино или Магазин Кармалы?",
        intent_hint=None,
    )


def _payment(value: Any) -> PaymentMethod:
    return PaymentMethod(value) if value else PaymentMethod.UNKNOWN


def build_command_from_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    raw_text: str,
    tx_id: str,
    occurred_at: datetime,
) -> ParsedCommand:
    """Главная диспетч-функция. Каждый case → конкретная pydantic-модель."""
    a = tool_args  # для краткости

    if tool_name == "record_sale":
        loc = _ensure_location(a.get("location"), "точка продажи", raw_text)
        if isinstance(loc, ClarificationNeeded):
            return loc
        return Sale(
            tx_id=tx_id,
            occurred_at=occurred_at,
            amount_kopecks=int(a["amount_rub"]) * 100,
            lines=_lines(a["lines"]),
            location=loc,
            customer=a.get("customer"),
            payment=_payment(a.get("payment")),
            comment=a.get("comment"),
            confidence=_conf(a, with_amount=True, with_qty=True),
            raw_text=raw_text,
        )

    if tool_name == "record_purchase":
        dst = _ensure_location(a.get("destination"), "точка приёмки", raw_text)
        if isinstance(dst, ClarificationNeeded):
            return dst
        return Purchase(
            tx_id=tx_id,
            occurred_at=occurred_at,
            amount_kopecks=int(a["amount_rub"]) * 100,
            supplier=str(a["supplier"]),
            lines=_lines(a["lines"]),
            destination=dst,
            payment=_payment(a.get("payment")),
            comment=a.get("comment"),
            confidence=_conf(a, with_amount=True, with_qty=True),
            raw_text=raw_text,
        )

    if tool_name == "record_return":
        loc = _ensure_location(a.get("location"), "точка возврата", raw_text)
        if isinstance(loc, ClarificationNeeded):
            return loc
        return Return(
            tx_id=tx_id,
            direction=ReturnDirection(a["direction"]),
            occurred_at=occurred_at,
            amount_kopecks=int(a["amount_rub"]) * 100,
            counterparty=str(a["counterparty"]),
            lines=_lines(a["lines"]),
            location=loc,
            payment=_payment(a.get("payment")),
            comment=a.get("comment"),
            confidence=_conf(a, with_amount=True, with_qty=True),
            raw_text=raw_text,
        )

    if tool_name == "record_cashflow":
        category = a.get("category")
        return Cashflow(
            tx_id=tx_id,
            occurred_at=occurred_at,
            op_type=CashflowType(a["op_type"]),
            amount_kopecks=int(a["amount_rub"]) * 100,
            description=str(a["description"]),
            category=ExpenseCategory(category) if category else None,
            counterparty=a.get("counterparty"),
            location=_location(a.get("location")),
            payment=_payment(a.get("payment")),
            confidence=_conf(a, with_amount=True),
            raw_text=raw_text,
        )

    if tool_name == "record_writeoff_or_movement":
        op_type = WriteoffOrMovementType(a["op_type"])
        src = _location(a.get("source"))
        dst = _location(a.get("destination"))
        loc = _location(a.get("location"))
        # Перемещение: source и destination обязательны. Если модель не дала их,
        # но дала "location" — этого недостаточно, нужно переспросить.
        if op_type == WriteoffOrMovementType.MOVEMENT:
            if not src or not dst:
                return ClarificationNeeded(
                    raw_text=raw_text,
                    reason="Для перемещения нужна точка-источник и точка-приёмник.",
                    question="Откуда и куда перемещаешь? Например: «переместил X с Зинино на Кармалы».",
                    intent_hint="writeoff",
                )
        # Списание: достаточно location (или source как fallback).
        elif op_type == WriteoffOrMovementType.WRITEOFF:
            if not loc and src:
                loc = src
        return WriteoffOrMovement(
            tx_id=tx_id,
            occurred_at=occurred_at,
            op_type=op_type,
            location=loc,
            source=src,
            destination=dst,
            lines=_lines(a["lines"]),
            comment=a.get("comment"),
            confidence=_conf(a, with_qty=True),
            raw_text=raw_text,
        )

    if tool_name == "record_inventory":
        loc = _ensure_location(a.get("location"), "точка инвентаризации", raw_text)
        if isinstance(loc, ClarificationNeeded):
            return loc
        facts = [
            InventoryFact(name=str(f["name"]), qty=float(f["qty"]), unit=str(f["unit"]))
            for f in a["facts"]
        ]
        return Inventory(
            tx_id=tx_id,
            occurred_at=occurred_at,
            location=loc,
            facts=facts,
            confidence=_conf(a, with_qty=True),
            raw_text=raw_text,
        )

    if tool_name == "query_or_report":
        if a["type"] == "stock":
            return StockQuery(
                product_query=a.get("product_query"),
                location=_location(a.get("location")),
            )
        elif a["type"] == "period_report":
            return PeriodReportRequest(
                period_type=ReportPeriodType(a.get("period_type") or "month"),
                year=a.get("year"),
                month=a.get("month"),
                quarter=a.get("quarter"),
                relative=a.get("relative"),
                location=_location(a.get("location")),
                top_metric=TopMetric(a.get("top_metric") or "выручка"),
                period_is_clear=bool(a.get("period_is_clear", False)),
            )
        else:
            raise ValueError(f"Неизвестный type для query_or_report: {a['type']}")

    if tool_name == "request_clarification":
        return ClarificationNeeded(
            raw_text=raw_text,
            reason=str(a["reason"]),
            question=str(a["question"]),
            intent_hint=a.get("intent_hint"),
        )

    raise ValueError(f"Неизвестный tool_name: {tool_name}")
