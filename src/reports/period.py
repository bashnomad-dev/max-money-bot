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
    pretty_location,
    read_goods_rows_for_reports,
    read_money_rows,
)
from src.stock.calculator import GoodsRow, StockCalculator


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
    all_goods = read_goods_rows_for_reports(spreadsheet)
    # Себестоимость продаж считаем по всей истории (СВ-цена накапливается с самого
    # начала), потом фильтруем по периоду.
    _populate_sale_costs(all_goods)
    goods_rows = filter_goods_by_period(all_goods, start, end)

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
        loc = pretty_location(r.location)
        if r.is_income:
            rep.income_rub += r.amount_rub
            rep.income_count += 1
            by_loc_net[loc] += r.amount_rub
        elif r.is_expense:
            rep.expense_rub += r.amount_rub
            rep.expense_count += 1
            by_loc_net[loc] -= r.amount_rub
    rep.by_location_net = dict(sorted(by_loc_net.items(), key=lambda kv: -kv[1]))

    # Топ-3: по выручке / прибыли / количеству
    rep.top_items = _build_top(goods_rows, money_rows, top_metric)
    return rep


def _populate_sale_costs(rows: list[GoodsAggRow]) -> None:
    """Проставить cost_rub каждой продажной строке = qty * СВ-цена на момент продажи.

    Реплеим всю историю движений хронологически тем же калькулятором, что и остатки,
    чтобы СВ-цена совпадала с листом «Остатки».
    """
    calc = StockCalculator()
    for r in sorted(rows, key=lambda x: x.occurred_at):
        if r.op_type == "продажа":
            r.cost_rub = calc.snapshot(r.product, r.location).avg_cost_rub * r.qty
        calc.apply(
            GoodsRow(
                occurred_at=r.occurred_at,
                op_type=r.op_type,
                location=r.location,
                source=r.source,
                product=r.product,
                qty=r.qty,
                unit=r.unit,
                price_per_unit_rub=r.price_per_unit_rub,
                comment=r.comment,
            )
        )


def _build_top(
    goods_rows: list[GoodsAggRow],
    money_rows: list[MoneyRow],
    metric: str,
) -> list[tuple[str, int, int, float]]:
    # Сумма по «Движение денег» для каждой продажи (по tx_id).
    # Используется как fallback когда LLM не указал цену за единицу в строке
    # «Движение товаров» — тогда выручка делится между lines пропорционально qty.
    sale_amount_by_tx: dict[str, float] = {}
    for r in money_rows:
        if r.op_type == "продажа":
            sale_amount_by_tx[r.tx_id] = float(r.amount_rub)

    # Суммарный qty продажи по tx_id (для пропорционального распределения).
    sale_total_qty_by_tx: dict[str, float] = defaultdict(float)
    for g in goods_rows:
        if g.op_type == "продажа" and g.tx_id in sale_amount_by_tx:
            sale_total_qty_by_tx[g.tx_id] += g.qty

    aggregate: dict[str, dict[str, float]] = defaultdict(
        lambda: {"revenue": 0.0, "cost": 0.0, "qty": 0.0}
    )
    for g in goods_rows:
        if g.op_type != "продажа" or g.tx_id not in sale_amount_by_tx:
            continue
        # 1) явная цена за единицу из строки товаров
        if g.price_per_unit_rub:
            line_revenue = float(g.price_per_unit_rub) * g.qty
        # 2) fallback: доля от общей суммы продажи пропорционально qty
        else:
            total_qty = sale_total_qty_by_tx.get(g.tx_id, 0)
            if total_qty > 0:
                line_revenue = sale_amount_by_tx[g.tx_id] * (g.qty / total_qty)
            else:
                line_revenue = 0.0
        aggregate[g.product]["revenue"] += line_revenue
        aggregate[g.product]["qty"] += g.qty
        # Себестоимость = qty * СВ-цена на момент продажи (см. _populate_sale_costs).
        aggregate[g.product]["cost"] += g.cost_rub or 0.0

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
