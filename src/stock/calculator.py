"""Расчёт остатков и СВ-цены закупки из «Движения товаров».

Принципы:
  - Ключ агрегата: (product_canon, location).
  - Количество меняется по типу операции:
      поступление, возврат покупателя → +qty
      продажа, списание, возврат поставщику → −qty
      перемещение: считается как 2 строки в источнике (-) и приёмнике (+)
      инвентаризация: запись дельты, qty уже представляет |delta|; знак определяется
                      сравнением с расчётным остатком (логика в writer.write_inventory)
  - СВ-цена обновляется только при поступлении (или возврате поставщику с известной ценой):
      new_avg = (old_qty * old_avg + new_qty * new_price) / (old_qty + new_qty)
  - При выбытии (продажа, списание, перемещение исх.) СВ-цена НЕ меняется.

Эту логику использует:
  1. /repair stock — полный пересчёт из истории.
  2. После каждой записи — инкрементальное обновление одной (product, location) пары.

См. docs/SPEC.md §12, data-model.md §1.2-1.3.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable


# ============================================================
# Типы строк из листа «Движение товаров»
# ============================================================

OPS_INCREMENT = {"поступление", "возврат покупателя"}
OPS_DECREMENT = {"продажа", "списание", "возврат поставщику"}
OP_MOVEMENT = "перемещение"
OP_INVENTORY = "инвентаризация"


@dataclass
class StockSnapshot:
    """Состояние одного товара на одной точке."""
    product: str
    location: str
    qty: float = 0.0
    avg_cost_rub: float = 0.0  # храним в рублях для совместимости с Sheets
    updated_at: datetime | None = None

    @property
    def total_cost_rub(self) -> float:
        return self.qty * self.avg_cost_rub


@dataclass
class GoodsRow:
    """Минимально нужные поля строки «Движения товаров» для расчёта остатков."""
    occurred_at: datetime
    op_type: str                 # из {поступление, продажа, списание, возврат покупателя, возврат поставщику, перемещение, инвентаризация}
    location: str                # для перемещения — это либо источник либо приёмник; различаем через source
    source: str | None           # только для перемещения-приёмника
    product: str
    qty: float
    unit: str
    price_per_unit_rub: float | None
    comment: str | None = None


# ============================================================
# Основной расчёт
# ============================================================

class StockCalculator:
    """In-memory агрегатор. Применяй строки в хронологическом порядке."""

    def __init__(self) -> None:
        self._snapshots: dict[tuple[str, str], StockSnapshot] = {}

    def snapshot(self, product: str, location: str) -> StockSnapshot:
        key = (product, location)
        if key not in self._snapshots:
            self._snapshots[key] = StockSnapshot(product=product, location=location)
        return self._snapshots[key]

    def all_snapshots(self) -> list[StockSnapshot]:
        return list(self._snapshots.values())

    def get_qty(self, product: str, location: str) -> float:
        return self.snapshot(product, location).qty

    def apply(self, row: GoodsRow) -> StockSnapshot:
        """Применить одну строку движения. Возвращает обновлённый snapshot."""
        snap = self.snapshot(row.product, row.location)

        if row.op_type in OPS_INCREMENT:
            self._apply_receipt(snap, row.qty, row.price_per_unit_rub)
        elif row.op_type in OPS_DECREMENT:
            self._apply_outflow(snap, row.qty)
        elif row.op_type == OP_MOVEMENT:
            # У нас row.location == точка этой строки. source != None означает что это приёмник.
            if row.source is not None and row.source != row.location:
                # Это приёмная сторона: оприходовать по avg_cost источника, если он у нас есть
                source_snap = self.snapshot(row.product, row.source)
                self._apply_receipt(snap, row.qty, source_snap.avg_cost_rub or None)
            else:
                # Исходная сторона
                self._apply_outflow(snap, row.qty)
        elif row.op_type == OP_INVENTORY:
            # Инвентаризация — корректировка. В writer.write_inventory мы пишем дельту
            # как qty>0 + комментарий "дельта". Распарсить «было/стало» из комментария.
            delta = _parse_inventory_delta(row.comment)
            if delta is None:
                # Fallback: считаем что qty это новое полное значение
                self._set_absolute(snap, row.qty, row.price_per_unit_rub)
            else:
                if delta > 0:
                    self._apply_receipt(snap, delta, row.price_per_unit_rub)
                elif delta < 0:
                    self._apply_outflow(snap, abs(delta))
        else:
            # Неизвестный тип — игнорим, чтобы не сломать пересчёт
            pass

        snap.updated_at = row.occurred_at
        return snap

    @staticmethod
    def _apply_receipt(snap: StockSnapshot, qty: float, price_per_unit: float | None) -> None:
        if price_per_unit is None or price_per_unit <= 0:
            # Поступление без цены — обновляем только qty, СВ-цена остаётся
            snap.qty += qty
            return
        # Формула СВ-цены
        new_total_qty = snap.qty + qty
        if new_total_qty <= 0:
            snap.qty = new_total_qty
            return
        snap.avg_cost_rub = (snap.qty * snap.avg_cost_rub + qty * price_per_unit) / new_total_qty
        snap.qty = new_total_qty

    @staticmethod
    def _apply_outflow(snap: StockSnapshot, qty: float) -> None:
        # СВ-цена не меняется при выбытии
        snap.qty -= qty

    @staticmethod
    def _set_absolute(snap: StockSnapshot, qty: float, price_per_unit: float | None) -> None:
        snap.qty = qty
        if price_per_unit is not None and price_per_unit > 0:
            snap.avg_cost_rub = price_per_unit


# ============================================================
# Парсинг дельты инвентаризации из комментария writer.write_inventory
# ============================================================

def _parse_inventory_delta(comment: str | None) -> float | None:
    """Достать дельту из формата `инвентаризация: было X, стало Y, дельта Z`."""
    if not comment:
        return None
    import re
    m = re.search(r"дельта\s+(-?[\d,.]+)", comment, flags=re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


# ============================================================
# Высокоуровневые точки входа
# ============================================================

def apply_goods_row(calculator: StockCalculator, row: GoodsRow) -> StockSnapshot:
    """Прозрачное проксирование, чтобы было чем замокать в тестах."""
    return calculator.apply(row)


def recompute_from_movements(rows: Iterable[GoodsRow]) -> StockCalculator:
    """Полный пересчёт остатков из истории /repair stock."""
    calc = StockCalculator()
    for row in sorted(rows, key=lambda r: r.occurred_at):
        calc.apply(row)
    return calc
