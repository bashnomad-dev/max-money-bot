"""Тесты семантического хэша для дедупликации повторов."""
from datetime import datetime

import pytest

from src.dialog.semantic_hash import semantic_hash
from src.domain.operation import (
    Cashflow,
    CashflowType,
    Confidence,
    GoodsLine,
    Location,
    PaymentMethod,
    Sale,
)


def _sale(amount_rub: int, qty: float, customer: str | None = None):
    return Sale(
        tx_id="x",
        occurred_at=datetime(2026, 6, 1, 12, 0),
        amount_kopecks=amount_rub * 100,
        lines=[GoodsLine(name="цемент", qty=qty, unit="меш.")],
        location=Location.ZININO,
        customer=customer,
        payment=PaymentMethod.CASH,
        confidence=Confidence(text=1.0, amount=1.0, quantity=1.0),
        raw_text="",
    )


class TestSemanticHash:
    def test_identical_sales_have_same_hash(self):
        a = _sale(18000, 30, "Иванов")
        b = _sale(18000, 30, "Иванов")
        assert semantic_hash(a) == semantic_hash(b)

    def test_different_amount_different_hash(self):
        a = _sale(18000, 30)
        b = _sale(20000, 30)
        assert semantic_hash(a) != semantic_hash(b)

    def test_different_qty_different_hash(self):
        """Чтобы продажа 30 мешков и 31 мешок не схлопывались."""
        a = _sale(18000, 30)
        b = _sale(18000, 31)
        assert semantic_hash(a) != semantic_hash(b)

    def test_small_amount_jitter_collapses(self):
        """Сумма 18500 и 18540 округляются до 18500."""
        a = _sale(18500, 30)
        b = _sale(18540, 30)
        assert semantic_hash(a) == semantic_hash(b)

    def test_amount_180_diff_in_hundreds_different(self):
        """Сумма 18500 и 18700 — разные сотни → разные хэши."""
        a = _sale(18500, 30)
        b = _sale(18700, 30)
        assert semantic_hash(a) != semantic_hash(b)

    def test_cashflow_uses_description(self):
        a = Cashflow(
            tx_id="x", occurred_at=datetime(2026, 6, 1, 12, 0),
            op_type=CashflowType.EXPENSE, amount_kopecks=8_000_000,
            description="аренда", category=None, counterparty=None,
            location=Location.ZININO, payment=PaymentMethod.TRANSFER,
            confidence=Confidence(text=1.0, amount=1.0, quantity=1.0),
            raw_text="",
        )
        b = Cashflow(
            tx_id="x", occurred_at=datetime(2026, 6, 1, 12, 0),
            op_type=CashflowType.EXPENSE, amount_kopecks=8_000_000,
            description="зарплата", category=None, counterparty=None,
            location=Location.ZININO, payment=PaymentMethod.TRANSFER,
            confidence=Confidence(text=1.0, amount=1.0, quantity=1.0),
            raw_text="",
        )
        # Разное описание → разный хэш
        assert semantic_hash(a) != semantic_hash(b)
