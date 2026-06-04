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
    pretty_location,
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
    stock_drift: list[tuple[str, str, float, float]] = field(default_factory=list)

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
        loc = pretty_location(r.location)
        if r.is_income:
            rep.income_rub += r.amount_rub
            rep.income_count += 1
            by_loc_net[loc] += r.amount_rub
        elif r.is_expense:
            rep.expense_rub += r.amount_rub
            rep.expense_count += 1
            by_loc_net[loc] -= r.amount_rub
    rep.by_location = dict(sorted(by_loc_net.items(), key=lambda kv: -abs(kv[1])))

    # Топ-3 товаров по выручке. Если цена за единицу в строке товаров пуста
    # (типично — LLM указал только total), распределяем total из «Движение денег»
    # пропорционально qty между lines одной продажи (тот же tx_id).
    sale_amount_by_tx: dict[str, float] = {
        r.tx_id: float(r.amount_rub) for r in money_today if r.op_type == "продажа"
    }
    sale_total_qty_by_tx: dict[str, float] = defaultdict(float)
    for g in goods_today:
        if g.op_type == "продажа" and g.tx_id in sale_amount_by_tx:
            sale_total_qty_by_tx[g.tx_id] += g.qty

    revenue_by_product: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))
    for g in goods_today:
        if g.op_type != "продажа" or g.tx_id not in sale_amount_by_tx:
            continue
        if g.price_per_unit_rub:
            line_value = float(g.price_per_unit_rub) * g.qty
        else:
            total_qty = sale_total_qty_by_tx.get(g.tx_id, 0)
            line_value = (
                sale_amount_by_tx[g.tx_id] * (g.qty / total_qty)
                if total_qty > 0 else 0.0
            )
        current_rub, current_qty = revenue_by_product[g.product]
        revenue_by_product[g.product] = (
            current_rub + int(round(line_value)),
            current_qty + g.qty,
        )

    top = sorted(
        revenue_by_product.items(),
        key=lambda kv: (-kv[1][0], -kv[1][1]),
    )[:3]
    rep.top_products = [(name, rub, qty) for name, (rub, qty) in top]

    # В автоотчёте (не в /today) проверяем, не правили ли «Остатки» руками.
    if not is_intermediate:
        try:
            from src.stock.sheets_sync import detect_stock_drift
            rep.stock_drift = detect_stock_drift(spreadsheet)
        except Exception:  # noqa: BLE001
            rep.stock_drift = []

    return rep


def _drift_warning(rep: DailyReport) -> str:
    """Блок предупреждения о ручных правках листа «Остатки» (пусто, если расхождений нет)."""
    if not rep.stock_drift:
        return ""
    lines = ["", "⚠️ Лист «Остатки» расходится с расчётом (правки вручную?):"]
    for product, loc, sheet_qty, calc_qty in rep.stock_drift[:10]:
        lines.append(f"  • {product} на {loc}: в листе {sheet_qty:g}, должно {calc_qty:g}")
    if len(rep.stock_drift) > 10:
        lines.append(f"  …и ещё {len(rep.stock_drift) - 10}")
    lines.append("Запусти /repair stock, чтобы пересчитать.")
    return "\n".join(lines)


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
            + _drift_warning(rep)
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

    drift = _drift_warning(rep)
    if drift:
        parts.append(drift)

    return "\n".join(parts)
