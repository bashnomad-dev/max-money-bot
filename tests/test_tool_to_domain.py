"""Тесты маппинга tool_call → ParsedCommand."""
from datetime import datetime

import pytest

from src.domain.operation import (
    Cashflow,
    CashflowType,
    ExpenseCategory,
    Inventory,
    Location,
    PaymentMethod,
    PeriodReportRequest,
    Purchase,
    Return,
    ReturnDirection,
    Sale,
    StockQuery,
    WriteoffOrMovement,
    WriteoffOrMovementType,
    ClarificationNeeded,
)
from src.llm.tool_to_domain import build_command_from_tool_call


def _now():
    return datetime(2026, 6, 2, 12, 0)


class TestRecordSale:
    def test_basic_sale(self):
        op = build_command_from_tool_call(
            tool_name="record_sale",
            tool_args={
                "amount_rub": 18000,
                "lines": [{"name": "цемент Стерлитамак", "qty": 30, "unit": "меш."}],
                "location": "Магазин Зинино",
                "customer": None,
                "payment": "наличные",
                "text_confidence": 0.95,
                "amount_confidence": 0.93,
                "quantity_confidence": 0.95,
            },
            raw_text="test",
            tx_id="ts_abc12345",
            occurred_at=_now(),
        )
        assert isinstance(op, Sale)
        assert op.amount_kopecks == 1_800_000
        assert op.location == Location.ZININO
        assert op.payment == PaymentMethod.CASH
        assert op.confidence.critical == 0.93
        assert len(op.lines) == 1
        assert op.lines[0].name == "цемент Стерлитамак"
        assert op.lines[0].qty == 30


class TestRecordPurchase:
    def test_basic_purchase(self):
        op = build_command_from_tool_call(
            tool_name="record_purchase",
            tool_args={
                "amount_rub": 25000,
                "supplier": "Петрович",
                "lines": [{"name": "штукатурка", "qty": 100, "unit": "меш."}],
                "destination": "Магазин Кармалы",
                "payment": "счёт",
                "text_confidence": 0.92,
                "amount_confidence": 0.94,
                "quantity_confidence": 0.93,
            },
            raw_text="test",
            tx_id="tp_xyz98765",
            occurred_at=_now(),
        )
        assert isinstance(op, Purchase)
        assert op.amount_kopecks == 2_500_000
        assert op.supplier == "Петрович"
        assert op.destination == Location.KARMALY
        assert op.payment == PaymentMethod.TRANSFER


class TestRecordReturn:
    def test_from_customer(self):
        op = build_command_from_tool_call(
            tool_name="record_return",
            tool_args={
                "direction": "from_customer",
                "amount_rub": 800,
                "counterparty": "Иванов",
                "lines": [{"name": "ГКЛ", "qty": 2, "unit": "лист"}],
                "location": "Магазин Зинино",
                "payment": "наличные",
                "text_confidence": 0.9,
                "amount_confidence": 0.9,
                "quantity_confidence": 0.9,
            },
            raw_text="test",
            tx_id="tr_aaa11111",
            occurred_at=_now(),
        )
        assert isinstance(op, Return)
        assert op.direction == ReturnDirection.FROM_CUSTOMER
        assert op.counterparty == "Иванов"


class TestRecordCashflow:
    def test_expense_rent(self):
        op = build_command_from_tool_call(
            tool_name="record_cashflow",
            tool_args={
                "op_type": "расход",
                "amount_rub": 80000,
                "description": "аренда",
                "category": "аренда помещения",
                "counterparty": None,
                "location": "Магазин Зинино",
                "payment": "счёт",
                "text_confidence": 0.95,
                "amount_confidence": 0.96,
            },
            raw_text="test",
            tx_id="tc_rent0001",
            occurred_at=_now(),
        )
        assert isinstance(op, Cashflow)
        assert op.op_type == CashflowType.EXPENSE
        assert op.category == ExpenseCategory.RENT


class TestRecordWriteoffOrMovement:
    def test_writeoff(self):
        op = build_command_from_tool_call(
            tool_name="record_writeoff_or_movement",
            tool_args={
                "op_type": "списание",
                "location": "Магазин Зинино",
                "lines": [{"name": "штукатурка", "qty": 3, "unit": "меш."}],
                "comment": "бой",
                "text_confidence": 0.94,
                "quantity_confidence": 0.95,
            },
            raw_text="test",
            tx_id="tw_0001",
            occurred_at=_now(),
        )
        assert isinstance(op, WriteoffOrMovement)
        assert op.op_type == WriteoffOrMovementType.WRITEOFF
        assert op.location == Location.ZININO

    def test_movement(self):
        op = build_command_from_tool_call(
            tool_name="record_writeoff_or_movement",
            tool_args={
                "op_type": "перемещение",
                "source": "Магазин Зинино",
                "destination": "Магазин Кармалы",
                "lines": [{"name": "ГКЛ", "qty": 20, "unit": "лист"}],
                "text_confidence": 0.93,
                "quantity_confidence": 0.95,
            },
            raw_text="test",
            tx_id="tm_0001",
            occurred_at=_now(),
        )
        assert isinstance(op, WriteoffOrMovement)
        assert op.op_type == WriteoffOrMovementType.MOVEMENT
        assert op.source == Location.ZININO
        assert op.destination == Location.KARMALY


class TestInventory:
    def test_batch_facts(self):
        op = build_command_from_tool_call(
            tool_name="record_inventory",
            tool_args={
                "location": "Магазин Зинино",
                "facts": [
                    {"name": "цемент", "qty": 47, "unit": "меш."},
                    {"name": "доска 50х150", "qty": 12, "unit": "шт."},
                ],
                "text_confidence": 0.88,
                "quantity_confidence": 0.9,
            },
            raw_text="test",
            tx_id="ti_0001",
            occurred_at=_now(),
        )
        assert isinstance(op, Inventory)
        assert len(op.facts) == 2


class TestQueryOrReport:
    def test_stock_query(self):
        op = build_command_from_tool_call(
            tool_name="query_or_report",
            tool_args={
                "type": "stock",
                "product_query": "цемент",
                "location": "Магазин Зинино",
            },
            raw_text="test",
            tx_id="dummy",
            occurred_at=_now(),
        )
        assert isinstance(op, StockQuery)
        assert op.product_query == "цемент"
        assert op.location == Location.ZININO

    def test_period_report(self):
        op = build_command_from_tool_call(
            tool_name="query_or_report",
            tool_args={
                "type": "period_report",
                "period_type": "month",
                "month": 5,
                "year": 2026,
                "top_metric": "выручка",
                "period_is_clear": True,
            },
            raw_text="test",
            tx_id="dummy",
            occurred_at=_now(),
        )
        assert isinstance(op, PeriodReportRequest)
        assert op.month == 5
        assert op.year == 2026
        assert op.period_is_clear is True


class TestRequestClarification:
    def test_basic(self):
        op = build_command_from_tool_call(
            tool_name="request_clarification",
            tool_args={
                "reason": "нет суммы",
                "question": "За сколько продал?",
                "intent_hint": "sale",
            },
            raw_text="test",
            tx_id="dummy",
            occurred_at=_now(),
        )
        assert isinstance(op, ClarificationNeeded)
        assert op.intent_hint == "sale"
