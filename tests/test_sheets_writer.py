"""Тесты sheets/writer.py с моком gspread."""
from datetime import datetime

import pytest

from src.domain.operation import (
    Cashflow,
    CashflowType,
    Confidence,
    ExpenseCategory,
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
from src.sheets.schema import GOODS_HEADERS, MONEY_HEADERS, SHEET_GOODS, SHEET_MONEY
from src.sheets.writer import (
    undo_by_refs,
    write_cashflow,
    write_purchase,
    write_return,
    write_sale,
    write_writeoff_or_movement,
)


@pytest.fixture
def spreadsheet_with_sheets(fake_spreadsheet):
    """Spreadsheet с двумя обязательными листами и заголовками."""
    ws_money = fake_spreadsheet.add_worksheet(SHEET_MONEY)
    ws_money.append_row(MONEY_HEADERS)
    ws_goods = fake_spreadsheet.add_worksheet(SHEET_GOODS)
    ws_goods.append_row(GOODS_HEADERS)
    return fake_spreadsheet


def _conf():
    return Confidence(text=0.95, amount=0.93, quantity=0.95)


def _now():
    return datetime(2026, 6, 2, 14, 30)


def test_write_sale_writes_to_both_sheets(spreadsheet_with_sheets):
    op = Sale(
        tx_id="ts_abc12345",
        occurred_at=_now(),
        amount_kopecks=1_800_000,
        lines=[GoodsLine(name="цемент", qty=30, unit="меш.", price_per_unit_rub=600)],
        location=Location.ZININO,
        customer=None,
        payment=PaymentMethod.CASH,
        confidence=_conf(),
        raw_text="test",
    )
    result = write_sale(spreadsheet_with_sheets, op)
    assert result.tx_id == "ts_abc12345"
    assert result.op_kind == "sale"
    assert len(result.refs) == 2  # 1 строка товаров + 1 строка денег
    # Проверим что строка попала в "Движение денег" с правильным типом
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    assert money_ws.rows[1][2] == "продажа"   # колонка "Тип операции"
    assert money_ws.rows[1][3] == 18000        # колонка "Сумма (₽)"
    # И в "Движение товаров"
    goods_ws = spreadsheet_with_sheets.worksheet(SHEET_GOODS)
    assert goods_ws.rows[1][5] == "цемент"     # колонка "Товар"


def test_write_purchase_pours_supplier(spreadsheet_with_sheets):
    op = Purchase(
        tx_id="tp_xxx",
        occurred_at=_now(),
        amount_kopecks=2_500_000,
        supplier="Петрович",
        lines=[GoodsLine(name="штукатурка", qty=100, unit="меш.", price_per_unit_rub=250)],
        destination=Location.KARMALY,
        payment=PaymentMethod.TRANSFER,
        confidence=_conf(),
        raw_text="test",
    )
    result = write_purchase(spreadsheet_with_sheets, op)
    assert len(result.refs) == 2
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    row = money_ws.rows[1]
    assert row[2] == "закупка"
    assert row[5] == "закупка товара"          # автокатегория для закупки
    assert row[6] == "Петрович"


def test_write_return_from_customer(spreadsheet_with_sheets):
    op = Return(
        tx_id="tr_001",
        direction=ReturnDirection.FROM_CUSTOMER,
        occurred_at=_now(),
        amount_kopecks=80_000,
        counterparty="Иванов",
        lines=[GoodsLine(name="ГКЛ", qty=2, unit="лист")],
        location=Location.ZININO,
        payment=PaymentMethod.CASH,
        confidence=_conf(),
        raw_text="test",
    )
    result = write_return(spreadsheet_with_sheets, op)
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    goods_ws = spreadsheet_with_sheets.worksheet(SHEET_GOODS)
    assert money_ws.rows[1][2] == "возврат покупателю"
    assert goods_ws.rows[1][2] == "возврат покупателя"


def test_write_cashflow_only_money(spreadsheet_with_sheets):
    op = Cashflow(
        tx_id="tc_001",
        occurred_at=_now(),
        op_type=CashflowType.EXPENSE,
        amount_kopecks=8_000_000,
        description="аренда",
        category=ExpenseCategory.RENT,
        counterparty=None,
        location=Location.ZININO,
        payment=PaymentMethod.TRANSFER,
        confidence=Confidence(text=0.95, amount=0.96, quantity=1.0),
        raw_text="test",
    )
    result = write_cashflow(spreadsheet_with_sheets, op)
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    goods_ws = spreadsheet_with_sheets.worksheet(SHEET_GOODS)
    assert len(money_ws.rows) == 2  # заголовок + 1
    assert len(goods_ws.rows) == 1  # только заголовок — товары не трогаем
    assert money_ws.rows[1][2] == "расход"
    assert money_ws.rows[1][5] == "аренда помещения"


def test_write_movement_two_rows_in_goods(spreadsheet_with_sheets):
    op = WriteoffOrMovement(
        tx_id="tm_001",
        occurred_at=_now(),
        op_type=WriteoffOrMovementType.MOVEMENT,
        source=Location.ZININO,
        destination=Location.KARMALY,
        lines=[GoodsLine(name="ГКЛ", qty=20, unit="лист")],
        confidence=Confidence(text=0.93, amount=1.0, quantity=0.95),
        raw_text="test",
    )
    result = write_writeoff_or_movement(spreadsheet_with_sheets, op)
    goods_ws = spreadsheet_with_sheets.worksheet(SHEET_GOODS)
    assert len(goods_ws.rows) == 3  # заголовок + 2 строки (источник, приёмник)
    # Источник
    row_out = goods_ws.rows[1]
    assert row_out[2] == "перемещение"
    assert row_out[3] == "Магазин Зинино"
    # Приёмник
    row_in = goods_ws.rows[2]
    assert row_in[3] == "Магазин Кармалы"
    assert row_in[4] == "Магазин Зинино"  # источник в колонке "Источник"


def test_undo_by_refs_removes_rows(spreadsheet_with_sheets):
    """Записать продажу, потом откатить — обе строки должны исчезнуть."""
    op = Sale(
        tx_id="ts_undo",
        occurred_at=_now(),
        amount_kopecks=1_800_000,
        lines=[GoodsLine(name="цемент", qty=30, unit="меш.")],
        location=Location.ZININO,
        payment=PaymentMethod.CASH,
        confidence=_conf(),
        raw_text="test",
    )
    result = write_sale(spreadsheet_with_sheets, op)
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    goods_ws = spreadsheet_with_sheets.worksheet(SHEET_GOODS)
    assert len(money_ws.rows) == 2
    assert len(goods_ws.rows) == 2

    removed = undo_by_refs(spreadsheet_with_sheets, result.refs_as_dicts())
    assert removed == 2
    assert len(money_ws.rows) == 1  # только заголовок
    assert len(goods_ws.rows) == 1


def test_author_written_to_last_column(spreadsheet_with_sheets):
    """MAX user_id автора пишется в последнюю колонку «Автор» обоих листов."""
    op = Sale(
        tx_id="ts_author",
        occurred_at=_now(),
        amount_kopecks=1_800_000,
        lines=[GoodsLine(name="цемент", qty=30, unit="меш.")],
        location=Location.ZININO,
        payment=PaymentMethod.CASH,
        confidence=_conf(),
        raw_text="test",
    )
    write_sale(spreadsheet_with_sheets, op, author="9876543")
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    goods_ws = spreadsheet_with_sheets.worksheet(SHEET_GOODS)
    # «Автор» — последняя колонка по заголовкам
    assert money_ws.rows[0][-1] == "Автор"
    assert money_ws.rows[1][-1] == "9876543"
    assert goods_ws.rows[1][-1] == "9876543"


def test_author_blank_when_not_passed(spreadsheet_with_sheets):
    op = Cashflow(
        tx_id="ts_noauthor",
        occurred_at=_now(),
        op_type=CashflowType.EXPENSE,
        amount_kopecks=200_000,
        description="налоги",
        confidence=_conf(),
        raw_text="test",
    )
    write_cashflow(spreadsheet_with_sheets, op)
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    assert money_ws.rows[1][-1] == ""


def test_edit_last_field_payment_and_location(spreadsheet_with_sheets):
    """Дополнение последней операции: оплата → кол.9, точка → кол.8 (с канонизацией опечатки)."""
    from src.sheets.writer import edit_last_field
    op = Sale(
        tx_id="ts_supp",
        occurred_at=_now(),
        amount_kopecks=1_800_000,
        lines=[GoodsLine(name="цемент", qty=30, unit="меш.")],
        location=Location.ZININO,
        payment=PaymentMethod.UNKNOWN,
        confidence=_conf(),
        raw_text="test",
    )
    result = write_sale(spreadsheet_with_sheets, op)
    refs = result.refs_as_dicts()

    edit_last_field(spreadsheet_with_sheets, refs, "оплата", "нал")
    money_ws = spreadsheet_with_sheets.worksheet(SHEET_MONEY)
    assert money_ws.rows[1][8] == "наличные"   # кол.9 «Способ оплаты»

    edit_last_field(spreadsheet_with_sheets, refs, "точка", "Карамалы")
    assert money_ws.rows[1][7] == "Магазин Кармалы"  # кол.8 «Точка», опечатка распознана


def test_edit_last_field_rejects_bad_payment(spreadsheet_with_sheets):
    from src.sheets.writer import edit_last_field
    op = Cashflow(
        tx_id="ts_badpay",
        occurred_at=_now(),
        op_type=CashflowType.EXPENSE,
        amount_kopecks=200_000,
        description="налоги",
        confidence=_conf(),
        raw_text="test",
    )
    result = write_cashflow(spreadsheet_with_sheets, op)
    with pytest.raises(ValueError):
        edit_last_field(spreadsheet_with_sheets, result.refs_as_dicts(), "оплата", "абракадабра")
