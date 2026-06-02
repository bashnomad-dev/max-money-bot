"""Тесты пересчёта остатков и СВ-цены."""
from datetime import datetime, timedelta

import pytest

from src.stock.calculator import GoodsRow, StockCalculator, recompute_from_movements


def _row(ts_offset_min: int, op_type: str, product: str, location: str, qty: float,
         price: float | None = None, source: str | None = None) -> GoodsRow:
    base = datetime(2026, 6, 1, 9, 0)
    return GoodsRow(
        occurred_at=base + timedelta(minutes=ts_offset_min),
        op_type=op_type,
        location=location,
        source=source,
        product=product,
        qty=qty,
        unit="меш.",
        price_per_unit_rub=price,
    )


class TestStockCalculator:
    def test_receipt_then_sale(self):
        calc = StockCalculator()
        calc.apply(_row(0, "поступление", "цемент", "Зинино", 100, price=300))
        assert calc.get_qty("цемент", "Зинино") == 100
        assert calc.snapshot("цемент", "Зинино").avg_cost_rub == 300

        calc.apply(_row(10, "продажа", "цемент", "Зинино", 30))
        assert calc.get_qty("цемент", "Зинино") == 70
        # СВ-цена не меняется при выбытии
        assert calc.snapshot("цемент", "Зинино").avg_cost_rub == 300

    def test_avg_cost_weighted(self):
        """Закупка 100 по 300 + 50 по 360 = СВ должна быть 320."""
        calc = StockCalculator()
        calc.apply(_row(0, "поступление", "цемент", "Зинино", 100, price=300))
        calc.apply(_row(10, "поступление", "цемент", "Зинино", 50, price=360))
        snap = calc.snapshot("цемент", "Зинино")
        assert snap.qty == 150
        assert snap.avg_cost_rub == pytest.approx(320, rel=1e-3)

    def test_writeoff(self):
        calc = StockCalculator()
        calc.apply(_row(0, "поступление", "штукатурка", "Зинино", 20, price=250))
        calc.apply(_row(10, "списание", "штукатурка", "Зинино", 3))
        assert calc.get_qty("штукатурка", "Зинино") == 17

    def test_return_by_customer_increments(self):
        calc = StockCalculator()
        calc.apply(_row(0, "поступление", "ГКЛ", "Зинино", 50, price=400))
        calc.apply(_row(10, "продажа", "ГКЛ", "Зинино", 10))
        calc.apply(_row(20, "возврат покупателя", "ГКЛ", "Зинино", 2))
        assert calc.get_qty("ГКЛ", "Зинино") == 42

    def test_movement_two_sides(self):
        calc = StockCalculator()
        calc.apply(_row(0, "поступление", "ГКЛ", "Зинино", 50, price=400))
        # Исходная сторона (без source)
        calc.apply(_row(10, "перемещение", "ГКЛ", "Зинино", 20))
        # Приёмная сторона (source != location)
        calc.apply(_row(11, "перемещение", "ГКЛ", "Кармалы", 20, source="Зинино"))
        assert calc.get_qty("ГКЛ", "Зинино") == 30
        assert calc.get_qty("ГКЛ", "Кармалы") == 20
        # СВ-цена должна перенестись на приёмник
        assert calc.snapshot("ГКЛ", "Кармалы").avg_cost_rub == 400

    def test_recompute_from_movements_orders_by_time(self):
        """Подаём в обратном порядке — пересчёт должен отсортировать по occurred_at."""
        rows = [
            _row(20, "продажа", "цемент", "Зинино", 30),
            _row(0, "поступление", "цемент", "Зинино", 100, price=300),
            _row(10, "поступление", "цемент", "Зинино", 50, price=360),
        ]
        calc = recompute_from_movements(rows)
        snap = calc.snapshot("цемент", "Зинино")
        assert snap.qty == 120  # 100 + 50 - 30
        assert snap.avg_cost_rub == pytest.approx(320, rel=1e-3)

    def test_inventory_delta_parsing(self):
        calc = StockCalculator()
        calc.apply(_row(0, "поступление", "цемент", "Зинино", 50, price=300))
        # Инвентаризация: было 50, стало 47, дельта -3
        inv = _row(10, "инвентаризация", "цемент", "Зинино", 3)
        inv.comment = "инвентаризация: было 50, стало 47, дельта -3"
        calc.apply(inv)
        assert calc.get_qty("цемент", "Зинино") == 47
