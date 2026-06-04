"""Тесты доделанных пунктов плана: /edit last, минусовой остаток,
себестоимость в отчёте, детект ручных правок «Остатков»."""
from datetime import datetime

import pytest

from src.bot.pipeline import _outflow_lines
from src.domain.operation import (
    Confidence,
    GoodsLine,
    Location,
    PaymentMethod,
    Purchase,
    Return,
    ReturnDirection,
    Sale,
    WriteoffOrMovement,
    WriteoffOrMovementType,
)
from src.reports._common import GoodsAggRow
from src.reports.period import _populate_sale_costs
from src.sheets.schema import (
    GOODS_HEADERS,
    MONEY_HEADERS,
    SHEET_GOODS,
    SHEET_MONEY,
    SHEET_STOCK,
    STOCK_HEADERS,
)
from src.sheets.writer import _esc, _parse_amount_rub, edit_last_field
from src.stock.sheets_sync import detect_stock_drift


def _conf():
    return Confidence(text=0.95, amount=0.95, quantity=0.95)


def _now():
    return datetime(2026, 6, 2, 14, 30)


# ============================================================
# /edit last
# ============================================================

@pytest.mark.parametrize(
    "value,expected",
    [("18000", 18000), ("18 000", 18000), ("18к", 18000), ("18,5к", 18500), ("плохо", None)],
)
def test_parse_amount_rub(value, expected):
    assert _parse_amount_rub(value) == expected


def test_edit_last_field_updates_money_cell(fake_spreadsheet):
    ws = fake_spreadsheet.add_worksheet(SHEET_MONEY)
    ws.append_row(MONEY_HEADERS)
    ws.append_row(["02.06.2026", "14:30", "продажа", 18000, "", "", "не указано",
                   "Магазин Зинино", "наличные", "tx1"])
    refs = [{"sheet": SHEET_MONEY, "row_index": 2}]

    edit_last_field(fake_spreadsheet, refs, "сумма", "20000")
    assert ws.rows[1][3] == 20000

    edit_last_field(fake_spreadsheet, refs, "контрагент", "Петрович")
    assert ws.rows[1][6] == "Петрович"


def test_edit_last_field_unknown_field_raises(fake_spreadsheet):
    ws = fake_spreadsheet.add_worksheet(SHEET_MONEY)
    ws.append_row(MONEY_HEADERS)
    refs = [{"sheet": SHEET_MONEY, "row_index": 2}]
    with pytest.raises(ValueError):
        edit_last_field(fake_spreadsheet, refs, "цвет", "синий")


@pytest.mark.parametrize(
    "value,expected",
    [
        ("+ СуперКамин штукатурка", "'+ СуперКамин штукатурка"),
        ("=сумма", "'=сумма"),
        ("-скидка", "'-скидка"),
        ("@тег", "'@тег"),
        ("Цемент М500", "Цемент М500"),
        ("", ""),
    ],
)
def test_esc_protects_formula_like_text(value, expected):
    assert _esc(value) == expected


def test_edit_last_field_no_money_row_raises(fake_spreadsheet):
    # Операция только в товарах (списание) — денежной строки нет.
    refs = [{"sheet": SHEET_GOODS, "row_index": 2}]
    with pytest.raises(ValueError):
        edit_last_field(fake_spreadsheet, refs, "сумма", "100")


# ============================================================
# Выбывающие строки (для карточки минуса)
# ============================================================

def test_outflow_lines_sale():
    op = Sale(
        tx_id="t", occurred_at=_now(), amount_kopecks=100,
        lines=[GoodsLine(name="цемент", qty=30, unit="меш.")],
        location=Location.ZININO, confidence=_conf(), raw_text="x",
    )
    assert _outflow_lines(op) == [("цемент", "Магазин Зинино", 30)]


def test_outflow_lines_purchase_is_inflow():
    op = Purchase(
        tx_id="t", occurred_at=_now(), amount_kopecks=100, supplier="Петрович",
        lines=[GoodsLine(name="цемент", qty=30, unit="меш.")],
        destination=Location.ZININO, confidence=_conf(), raw_text="x",
    )
    assert _outflow_lines(op) == []


def test_outflow_lines_return_to_supplier_only():
    to_supplier = Return(
        tx_id="t", direction=ReturnDirection.TO_SUPPLIER, occurred_at=_now(),
        amount_kopecks=100, counterparty="Петрович",
        lines=[GoodsLine(name="цемент", qty=5, unit="меш.")],
        location=Location.ZININO, confidence=_conf(), raw_text="x",
    )
    from_customer = to_supplier.model_copy(update={"direction": ReturnDirection.FROM_CUSTOMER})
    assert _outflow_lines(to_supplier) == [("цемент", "Магазин Зинино", 5)]
    assert _outflow_lines(from_customer) == []


def test_outflow_lines_movement_uses_source():
    op = WriteoffOrMovement(
        tx_id="t", occurred_at=_now(), op_type=WriteoffOrMovementType.MOVEMENT,
        source=Location.ZININO, destination=Location.KARMALY,
        lines=[GoodsLine(name="цемент", qty=10, unit="меш.")],
        confidence=_conf(), raw_text="x",
    )
    assert _outflow_lines(op) == [("цемент", "Магазин Зинино", 10)]


# ============================================================
# Себестоимость продаж (прибыль в отчёте)
# ============================================================

def test_populate_sale_costs_uses_weighted_avg():
    rows = [
        GoodsAggRow(datetime(2026, 6, 1, 10), "поступление", "Магазин Зинино",
                    "цемент", 100, "меш.", 600.0, "tx1"),
        GoodsAggRow(datetime(2026, 6, 2, 10), "продажа", "Магазин Зинино",
                    "цемент", 30, "меш.", None, "tx2"),
    ]
    _populate_sale_costs(rows)
    sale = rows[1]
    assert sale.cost_rub == pytest.approx(30 * 600.0)


def test_populate_sale_costs_blends_two_purchases():
    # 100 по 600 + 100 по 800 → СВ-цена 700; продажа 50 → cost 35000.
    rows = [
        GoodsAggRow(datetime(2026, 6, 1, 10), "поступление", "Магазин Зинино",
                    "цемент", 100, "меш.", 600.0, "tx1"),
        GoodsAggRow(datetime(2026, 6, 1, 11), "поступление", "Магазин Зинино",
                    "цемент", 100, "меш.", 800.0, "tx2"),
        GoodsAggRow(datetime(2026, 6, 2, 10), "продажа", "Магазин Зинино",
                    "цемент", 50, "меш.", None, "tx3"),
    ]
    _populate_sale_costs(rows)
    assert rows[2].cost_rub == pytest.approx(50 * 700.0)


# ============================================================
# Детект ручных правок «Остатков»
# ============================================================

def _goods_row(dt, op_type, product, qty, price, tx, location="Магазин Зинино"):
    return [dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M"), op_type, location, "",
            product, qty, "меш.", price if price is not None else "", "", "", tx]


def _spreadsheet_with_goods_and_stock(fake_spreadsheet, stock_qty):
    ws_goods = fake_spreadsheet.add_worksheet(SHEET_GOODS)
    ws_goods.append_row(GOODS_HEADERS)
    ws_goods.append_row(_goods_row(datetime(2026, 6, 1, 10), "поступление", "цемент", 100, 600, "tx1"))
    ws_goods.append_row(_goods_row(datetime(2026, 6, 2, 12), "продажа", "цемент", 30, None, "tx2"))

    ws_stock = fake_spreadsheet.add_worksheet(SHEET_STOCK)
    ws_stock.append_row(STOCK_HEADERS)
    ws_stock.append_row(["цемент", "Магазин Зинино", stock_qty, "меш.", 600, ""])
    return fake_spreadsheet


def test_detect_stock_drift_flags_manual_edit(fake_spreadsheet):
    # Расчётный остаток = 70, в листе 999 → расхождение.
    ss = _spreadsheet_with_goods_and_stock(fake_spreadsheet, stock_qty=999)
    drift = detect_stock_drift(ss)
    assert drift == [("цемент", "Магазин Зинино", 999.0, 70.0)]


def test_detect_stock_drift_clean_when_matches(fake_spreadsheet):
    ss = _spreadsheet_with_goods_and_stock(fake_spreadsheet, stock_qty=70)
    assert detect_stock_drift(ss) == []
