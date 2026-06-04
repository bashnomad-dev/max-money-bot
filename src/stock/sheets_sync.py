"""Синхронизация StockCalculator ↔ лист «Остатки» в Google Sheets.

Использование:
  - sync_after_op(spreadsheet, calculator, affected_keys): после транзакции
    обновляем только затронутые (товар, точка) строки.
  - repair_full(spreadsheet): полный пересчёт через recompute_from_movements
    и заливка с нуля (truncate+rewrite).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from src.sheets.schema import GOODS_HEADERS, SHEET_GOODS, SHEET_STOCK, STOCK_HEADERS
from src.stock.calculator import GoodsRow, StockCalculator, StockSnapshot, recompute_from_movements

log = logging.getLogger(__name__)


def _stock_row(snap: StockSnapshot, default_unit: str = "") -> list[Any]:
    """Сборка строки для листа «Остатки» в порядке STOCK_HEADERS."""
    return [
        snap.product,
        snap.location,
        snap.qty,
        default_unit or "",
        round(snap.avg_cost_rub, 2),
        snap.updated_at.strftime("%d.%m.%Y %H:%M") if snap.updated_at else "",
    ]


def _read_goods_rows(spreadsheet) -> list[GoodsRow]:
    """Прочитать «Движение товаров» как GoodsRow[] для пересчёта."""
    ws = spreadsheet.worksheet(SHEET_GOODS)
    records = ws.get_all_records()  # list[dict]
    rows: list[GoodsRow] = []
    for r in records:
        try:
            dt_str = f"{r['Дата']} {r['Время']}"
            dt = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
        except (KeyError, ValueError):
            continue
        rows.append(
            GoodsRow(
                occurred_at=dt,
                op_type=str(r.get("Тип операции", "")).strip(),
                location=str(r.get("Точка", "")).strip(),
                source=(str(r.get("Источник", "")).strip() or None),
                product=str(r.get("Товар", "")).strip(),
                qty=_safe_float(r.get("Количество", 0)),
                unit=str(r.get("Единица", "")).strip(),
                price_per_unit_rub=_safe_float_or_none(r.get("Цена за ед. (₽)", "")),
                comment=str(r.get("Комментарий", "")).strip() or None,
            )
        )
    return rows


def _safe_float(v: Any) -> float:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return 0.0


def _safe_float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return None


def repair_full(spreadsheet) -> tuple[int, int]:
    """Полный пересчёт остатков из «Движения товаров». Возвращает (прочитано_строк, записано_остатков)."""
    rows = _read_goods_rows(spreadsheet)
    log.info("repair_full: прочитано %d строк из «%s»", len(rows), SHEET_GOODS)

    calc = recompute_from_movements(rows)
    snapshots = sorted(calc.all_snapshots(), key=lambda s: (s.location, s.product))

    ws = spreadsheet.worksheet(SHEET_STOCK)

    # Очистка с сохранением A1-маркера и заголовков
    a1_cell = ws.cell(1, 1).value
    if a1_cell and "СИСТЕМНЫЙ" in a1_cell:
        ws.batch_clear(["A3:Z"])  # очищаем данные ниже заголовков (в строке 2)
        header_row = 2
    else:
        ws.batch_clear(["A2:Z"])
        header_row = 1

    new_rows = [_stock_row(s, default_unit=_first_unit_for(rows, s)) for s in snapshots if s.qty != 0]
    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
    log.info("repair_full: записано %d строк в «%s»", len(new_rows), SHEET_STOCK)

    return len(rows), len(new_rows)


def _first_unit_for(rows: list[GoodsRow], snap: StockSnapshot) -> str:
    """Найти первую попавшуюся единицу для этой пары (product, location)."""
    for r in rows:
        if r.product == snap.product and r.location == snap.location and r.unit:
            return r.unit
    return ""


def detect_stock_drift(
    spreadsheet, eps: float = 0.001
) -> list[tuple[str, str, float, float]]:
    """Сверить лист «Остатки» с пересчётом из истории движений.

    Возвращает список расхождений (товар, точка, остаток_в_листе, расчётный_остаток).
    Непустой результат = лист правили вручную (или прошёл сбой sync) → нужен /repair stock.
    """
    calc = recompute_from_movements(_read_goods_rows(spreadsheet))
    expected: dict[tuple[str, str], float] = {
        (s.product, s.location): s.qty for s in calc.all_snapshots() if s.qty != 0
    }

    ws = spreadsheet.worksheet(SHEET_STOCK)
    a1_cell = ws.cell(1, 1).value
    header_offset = 2 if (a1_cell and "СИСТЕМНЫЙ" in a1_cell) else 1
    try:
        existing = ws.get_all_records(head=header_offset, expected_headers=STOCK_HEADERS)
    except TypeError:
        existing = ws.get_all_records(head=header_offset)

    drift: list[tuple[str, str, float, float]] = []
    seen: set[tuple[str, str]] = set()
    for rec in existing:
        key = (str(rec.get("Товар", "")).strip(), str(rec.get("Точка", "")).strip())
        if not key[0]:
            continue
        seen.add(key)
        sheet_qty = _safe_float(rec.get("Количество", 0))
        calc_qty = expected.get(key, 0.0)
        if abs(sheet_qty - calc_qty) > eps:
            drift.append((key[0], key[1], sheet_qty, calc_qty))

    # Позиции, которые должны быть, но в листе их нет
    for key, calc_qty in expected.items():
        if key not in seen:
            drift.append((key[0], key[1], 0.0, calc_qty))

    return drift


def sync_after_op(
    spreadsheet,
    calculator: StockCalculator,
    affected_keys: set[tuple[str, str]],
) -> int:
    """Обновить только затронутые (product, location) строки в листе «Остатки».

    Стратегия: ищем существующие строки по (Товар + Точка), обновляем; если нет — append.
    """
    if not affected_keys:
        return 0

    ws = spreadsheet.worksheet(SHEET_STOCK)
    # Лист может начинаться с системного маркера в A1 — тогда заголовок в строке 2.
    a1_cell = ws.cell(1, 1).value
    header_offset = 2 if (a1_cell and "СИСТЕМНЫЙ" in a1_cell) else 1
    try:
        existing = ws.get_all_records(
            head=header_offset,
            expected_headers=STOCK_HEADERS,
        )
    except TypeError:
        # старые версии gspread без expected_headers
        existing = ws.get_all_records(head=header_offset)
    existing_map: dict[tuple[str, str], int] = {}
    for i, rec in enumerate(existing, start=header_offset + 1):
        key = (str(rec.get("Товар", "")).strip(), str(rec.get("Точка", "")).strip())
        existing_map[key] = i

    updated = 0
    new_rows: list[list[Any]] = []
    for key in affected_keys:
        snap = calculator.snapshot(*key)
        row_values = _stock_row(snap)
        if key in existing_map:
            ws.update(f"A{existing_map[key]}:F{existing_map[key]}", [row_values])
            updated += 1
        else:
            new_rows.append(row_values)
    if new_rows:
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    return updated + len(new_rows)
