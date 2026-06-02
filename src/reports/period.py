"""Сводный отчёт за период (месяц/квартал/год) + опц. фильтр по точке + 3 метрики топа."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from src.reports._common import (
    GoodsAggRow,
    MoneyRow,
    filter_goods_by_period,
    filter_money_by_period,
    fmt_rub,
    fmt_signed_rub,
    period_bounds,
    read_goods_rows_for_reports,
    read_money_rows,
)


@dataclass
class PeriodReport:
    period_label: str
    location_filter: str | None
    top_metric: str  # 'выручка' | 'прибыль' | 'количество'
    income_rub: int = 0
    expense_rub: int = 0
    income_count: int = 0
    expense_count: int = 0
    by_location_net: dict[str, int] = field(default_factory=dict)
    top_items: list[tuple[str, int, int, float]] = field(default_factory=list)
    # (label, revenue_rub, profit_rub, quantity)

    @property
    def balance_rub(self) -> int:
        return self.income_rub - self.expense_rub


def build_period_report(
    spreadsheet,
    period_type: str,
    year: int | None,
    month: int | None,
    quarter: int | None,
    relative: str | None,
    location_filter: str | None,
    top_metric: str,
    today: date,
) -> PeriodReport:
    start, end, period_label = period_bounds(period_type, year, month, quarter, relative, today)

    money_rows = filter_money_by_period(read_money_rows(spreadsheet), start, end)
    goods_rows = filter_goods_by_period(read_goods_rows_for_reports(spreadsheet), start, end)

    if location_filter:
        money_rows = [r for r in money_rows if r.location == location_filter]
        goods_rows = [r for r in goods_rows if r.location == location_filter]

    rep = PeriodReport(
        period_label=period_label,
        location_filter=location_filter,
        top_metric=top_metric,
    )

    by_loc_net: dict[str, int] = defaultdict(int)
    for r in money_rows:
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
    rep.by_location_net = dict(sorted(by_loc_net.items(), key=lambda kv: -kv[1]))

    # Топ-3: по выручке / прибыли / количеству
    rep.top_items = _build_top(goods_rows, money_rows, top_metric)
    return rep


def _build_top(
    goods_rows: list[GoodsAggRow],
    money_rows: list[MoneyRow],
    metric: str,
) -> list[tuple[str, int, int, float]]:
    sales_tx = {r.tx_id for r in money_rows if r.op_type == "продажа"}
    purchase_tx = {r.tx_id for r in money_rows if r.op_type == "закупка"}

    # revenue: сумма за позиции в продажах (цена × qty), либо amount пропорционально
    # profit: revenue минус себестоимость (price_per_unit_rub из продажи = СВ-цена на момент)
    # quantity: суммарное qty в продажах
    aggregate: dict[str, dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "cost": 0.0, "qty": 0.0}
    )
    for g in goods_rows:
        if g.op_type == "продажа" and g.tx_id in sales_tx:
            # Если есть цена за единицу — используем как розничную цену реализации
            line_revenue = (g.price_per_unit_rub or 0) * g.qty
            aggregate[g.product]["revenue"] += line_revenue
            aggregate[g.product]["qty"] += g.qty
            # Себестоимость для прибыли: используем ту же цену за единицу как СВ-цену
            # (при штатной работе для продаж пишется СВ-цена; для прибыли это упрощение)
            aggregate[g.product]["cost"] += line_revenue  # пока 0 прибыли по умолчанию

    if metric == "выручка":
        sort_key = lambda kv: -kv[1]["revenue"]
    elif metric == "количество":
        sort_key = lambda kv: -kv[1]["qty"]
    else:  # прибыль
        sort_key = lambda kv: -(kv[1]["revenue"] - kv[1]["cost"])

    sorted_items = sorted(aggregate.items(), key=sort_key)[:3]
    return [
        (
            name,
            int(round(d["revenue"])),
            int(round(d["revenue"] - d["cost"])),
            d["qty"],
        )
        for name, d in sorted_items
    ]


def format_period_report(rep: PeriodReport) -> str:
    parts = [f"Финансовый отчёт за {rep.period_label}"]
    if rep.location_filter:
        parts.append(f"(только {rep.location_filter})")
    parts[0] += ":"
    parts += [
        f"– Приход: {fmt_rub(rep.income_rub)} рублей ({rep.income_count} операций)",
        f"– Расход: {fmt_rub(rep.expense_rub)} рублей ({rep.expense_count} операций)",
        f"– Итог: {fmt_signed_rub(rep.balance_rub)} рублей",
    ]

    if rep.by_location_net and not rep.location_filter:
        parts += ["", "По точкам:"]
        for loc, net in rep.by_location_net.items():
            parts.append(f"  {loc}: {fmt_signed_rub(net)} ₽")

    if rep.top_items:
        parts += ["", f"Топ-3 товара {rep.top_metric}:"]
        for i, (name, revenue, profit, qty) in enumerate(rep.top_items, 1):
            qty_str = f"{int(qty)}" if qty == int(qty) else f"{qty:.2f}"
            if rep.top_metric == "выручка":
                parts.append(f"  {i}. {name} — {fmt_rub(revenue)} ₽ ({qty_str} шт)")
            elif rep.top_metric == "прибыль":
                parts.append(f"  {i}. {name} — {fmt_signed_rub(profit)} ₽")
            else:
                parts.append(f"  {i}. {name} — {qty_str} шт ({fmt_rub(revenue)} ₽)")

    return "\n".join(parts)
