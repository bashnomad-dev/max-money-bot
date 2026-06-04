"""Общие утилиты для отчётов: чтение Sheets, парсинг периодов, форматирование."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from src.domain.operation import Location
from src.sheets.schema import SHEET_GOODS, SHEET_MONEY


# ============================================================
# Типы операций денег (для классификации приход/расход)
# ============================================================

INCOME_OPS = {"продажа", "прочий приход", "возврат поставщика", "внесение"}
EXPENSE_OPS = {"закупка", "расход", "возврат покупателю", "изъятие"}


@dataclass
class MoneyRow:
    occurred_at: datetime
    op_type: str
    amount_rub: int
    description: str
    category: str
    counterparty: str
    location: str
    payment: str
    tx_id: str

    @property
    def is_income(self) -> bool:
        return self.op_type in INCOME_OPS

    @property
    def is_expense(self) -> bool:
        return self.op_type in EXPENSE_OPS


def pretty_location(loc: str) -> str:
    """В отчётах вместо «не указано» / пусто показываем «Общие» — для cashflow
    без привязки к конкретной точке (зарплата, аренда, налоги и т.п.).
    """
    s = (loc or "").strip()
    if not s or s.lower() == "не указано":
        return "Общие"
    return s


@dataclass
class GoodsAggRow:
    """Минимальные поля «Движения товаров» для агрегатов отчётов."""
    occurred_at: datetime
    op_type: str
    location: str
    product: str
    qty: float
    unit: str
    price_per_unit_rub: float | None
    tx_id: str
    source: str | None = None
    comment: str | None = None
    cost_rub: float | None = None  # себестоимость строки = qty * СВ-цена на момент операции


def read_money_rows(spreadsheet) -> list[MoneyRow]:
    ws = spreadsheet.worksheet(SHEET_MONEY)
    records = ws.get_all_records()
    out: list[MoneyRow] = []
    for r in records:
        dt = _parse_dt(r.get("Дата"), r.get("Время"))
        if not dt:
            continue
        out.append(
            MoneyRow(
                occurred_at=dt,
                op_type=str(r.get("Тип операции", "")).strip(),
                amount_rub=_to_int_rub(r.get("Сумма (₽)", 0)),
                description=str(r.get("Описание", "")).strip(),
                category=str(r.get("Категория", "")).strip(),
                counterparty=str(r.get("Контрагент", "")).strip(),
                location=str(r.get("Точка", "")).strip(),
                payment=str(r.get("Способ оплаты", "")).strip(),
                tx_id=str(r.get("tx_id", "")).strip(),
            )
        )
    return out


def read_goods_rows_for_reports(spreadsheet) -> list[GoodsAggRow]:
    ws = spreadsheet.worksheet(SHEET_GOODS)
    records = ws.get_all_records()
    out: list[GoodsAggRow] = []
    for r in records:
        dt = _parse_dt(r.get("Дата"), r.get("Время"))
        if not dt:
            continue
        out.append(
            GoodsAggRow(
                occurred_at=dt,
                op_type=str(r.get("Тип операции", "")).strip(),
                location=str(r.get("Точка", "")).strip(),
                product=str(r.get("Товар", "")).strip(),
                qty=_to_float(r.get("Количество", 0)),
                unit=str(r.get("Единица", "")).strip(),
                price_per_unit_rub=_to_float_or_none(r.get("Цена за ед. (₽)", "")),
                tx_id=str(r.get("tx_id", "")).strip(),
                source=(str(r.get("Источник", "")).strip() or None),
                comment=(str(r.get("Комментарий", "")).strip() or None),
            )
        )
    return out


# ============================================================
# Утилиты парсинга
# ============================================================

def _parse_dt(date_str: Any, time_str: Any) -> datetime | None:
    if not date_str or not time_str:
        return None
    try:
        return datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return None


def _to_int_rub(v: Any) -> int:
    try:
        return int(round(float(str(v).replace(",", ".").replace(" ", ""))))
    except (ValueError, TypeError):
        return 0


def _to_float(v: Any) -> float:
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return 0.0


def _to_float_or_none(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", ".").replace(" ", ""))
    except (ValueError, TypeError):
        return None


# ============================================================
# Форматирование чисел
# ============================================================

def fmt_rub(amount: int) -> str:
    """1234567 → '1 234 567'."""
    return f"{amount:,}".replace(",", " ")


def fmt_signed_rub(amount: int) -> str:
    sign = "+" if amount > 0 else ""
    return f"{sign}{fmt_rub(amount)}"


# ============================================================
# Периоды
# ============================================================

def period_bounds(
    period_type: str,
    year: int | None,
    month: int | None,
    quarter: int | None,
    relative: str | None,
    today: date,
) -> tuple[date, date, str]:
    """Возвращает (start, end_exclusive, period_label) для типа периода."""
    if period_type == "day":
        return today, today + timedelta(days=1), today.strftime("%d.%m.%Y")

    if period_type == "month":
        m = month or today.month
        y = year or today.year
        # Дефолт года: если получилось будущее — взять прошлый
        candidate = date(y, m, 1)
        if candidate > today.replace(day=1) and year is None:
            y -= 1
        start = date(y, m, 1)
        end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
        return start, end, f"{_month_name_ru(m)} {y}"

    if period_type == "quarter":
        q = quarter or ((today.month - 1) // 3 + 1)
        y = year or today.year
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 3
        start = date(y, start_month, 1)
        end = date(y + (1 if end_month > 12 else 0), end_month if end_month <= 12 else 1, 1)
        return start, end, f"Q{q} {y}"

    if period_type == "year":
        y = year or today.year
        return date(y, 1, 1), date(y + 1, 1, 1), str(y)

    # custom — оставим простой fallback на текущий месяц
    return period_bounds("month", year, month, quarter, "current", today)


_MONTHS_RU = [
    "", "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
]


def _month_name_ru(month: int) -> str:
    return _MONTHS_RU[month]


def filter_money_by_period(rows: list[MoneyRow], start: date, end: date) -> list[MoneyRow]:
    return [r for r in rows if start <= r.occurred_at.date() < end]


def filter_goods_by_period(rows: list[GoodsAggRow], start: date, end: date) -> list[GoodsAggRow]:
    return [r for r in rows if start <= r.occurred_at.date() < end]
