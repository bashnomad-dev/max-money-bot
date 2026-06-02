"""Дневной автоотчёт (21:00 МСК) + промежуточный /today."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

from src.domain.operation import Location
from src.reports._common import (
    GoodsAggRow,
    MoneyRow,
    filter_goods_by_period,
    filter_money_by_period,
    fmt_rub,
    fmt_signed_rub,
    read_goods_rows_for_reports,
    read_money_rows,
)


@dataclass
class DailyReport:
    report_date: date
    income_rub: int = 0
    expense_rub: int = 0
    income_count: int = 0
    expense_count: int = 0
    by_location: dict[str, int] = field(default_factory=dict)
    top_products: list[tuple[str, int, float]] = field(default_factory=list)
    is_intermediate: bool = False  # для /today

    @property
    def balance_rub(self) -> int:
        return self.income_rub - self.expense_rub


def build_daily_report(
    spreadsheet,
    report_date: date,
    is_intermediate: bool = False,
) -> DailyReport:
    money_rows = read_money_rows(spreadsheet)
    goods_rows = read_goods_rows_for_reports(spreadsheet)

    end = date(report_date.year, report_date.month, report_date.day)
    # включаем сегодня — фильтруем по date == report_date
    money_today = [r for r in money_rows if r.occurred_at.date() == report_date]
    goods_today = [r for r in goods_rows if r.occurred_at.date() == report_date]

    rep = DailyReport(report_date=report_date, is_intermediate=is_intermediate)
    by_loc_net: dict[str, int] = defaultdict(int)

    for r in money_today:
        if r.is_income:
            rep.income_rub += r.amount_rub
            rep.income_count += 1
            if r.location:
                by_loc_net[r.location] += r.amount_rub
        elif r.is_expense:
            rep.expense_rub += r.amount_rub
            rep.expense_count += 1
            if r.location:
                by_loc_net[r.location] -= r.amount_rub
    rep.by_location = dict(sorted(by_loc_net.items(), key=lambda kv: -abs(kv[1])))

    # Топ-3 товаров по выручке (только продажи: связываем по tx_id)
    sales_tx = {r.tx_id for r in money_today if r.op_type == "продажа"}
    revenue_by_product: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    for g in goods_today:
        if g.op_type == "продажа" and g.tx_id in sales_tx:
            current_rub, current_qty = revenue_by_product[g.product]
            line_value = int(round((g.price_per_unit_rub or 0) * g.qty))
            revenue_by_product[g.product] = (current_rub + line_value, current_qty + g.qty)
    # Если нет цен — топ по количеству
    top = sorted(
        revenue_by_product.items(),
        key=lambda kv: (-kv[1][0], -kv[1][1]),
    )[:3]
    rep.top_products = [(name, rub, qty) for name, (rub, qty) in top]
    return rep


def format_daily_report(rep: DailyReport) -> str:
    if rep.income_count == 0 and rep.expense_count == 0:
        if rep.is_intermediate:
            return (
                f"На сейчас ({datetime.now().strftime('%H:%M')}, "
                f"{rep.report_date.strftime('%d.%m.%Y')}):\n"
                f"– Приход: 0 ₽\n"
                f"– Расход: 0 ₽\n"
                f"– Итог: 0 ₽\n"
                f"Сегодня операций пока нет."
            )
        return (
            f"Финансы за {rep.report_date.strftime('%d.%m.%Y')}:\n"
            f"– Приход: 0 рублей\n"
            f"– Расход: 0 рублей\n"
            f"– Итог: 0 рублей.\n"
            f"Сегодня финансовых операций не найдено."
        )

    title = (
        f"На сейчас ({datetime.now().strftime('%H:%M')}, "
        f"{rep.report_date.strftime('%d.%m.%Y')}):"
        if rep.is_intermediate
        else f"Финансы за {rep.report_date.strftime('%d.%m.%Y')}:"
    )
    parts = [
        title,
        f"– Приход: {fmt_rub(rep.income_rub)} ₽ ({rep.income_count} операций)",
        f"– Расход: {fmt_rub(rep.expense_rub)} ₽ ({rep.expense_count} операций)",
        f"– Итог: {fmt_signed_rub(rep.balance_rub)} ₽",
    ]

    if rep.by_location:
        parts.append("")
        parts.append("По точкам:")
        for loc, net in rep.by_location.items():
            parts.append(f"  {loc}: {fmt_signed_rub(net)} ₽")

    if rep.top_products:
        parts.append("")
        parts.append("Топ товаров по выручке:")
        for i, (name, rub, qty) in enumerate(rep.top_products, 1):
            qty_str = f"{int(qty)}" if qty == int(qty) else f"{qty:.2f}"
            if rub > 0:
                parts.append(f"  {i}. {name} — {fmt_rub(rub)} ₽ ({qty_str} шт)")
            else:
                parts.append(f"  {i}. {name} — {qty_str} шт (цена не указана)")

    return "\n".join(parts)
