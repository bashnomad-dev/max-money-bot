"""Форматирование запроса остатков /stock в человекочитаемый текст."""
from __future__ import annotations

from collections import defaultdict

from src.reports._common import fmt_rub
from src.sheets.schema import SHEET_STOCK


def read_stock_rows(spreadsheet) -> list[dict]:
    ws = spreadsheet.worksheet(SHEET_STOCK)
    # У листа «Остатки» в A1 может быть служебный маркер — заголовки во второй строке
    a1 = ws.cell(1, 1).value
    if a1 and "СИСТЕМНЫЙ" in a1:
        all_values = ws.get_all_values()
        headers = all_values[1] if len(all_values) >= 2 else []
        records = [dict(zip(headers, row)) for row in all_values[2:] if any(row)]
    else:
        records = ws.get_all_records()
    return records


def format_stock_report(
    spreadsheet,
    product_query: str | None,
    location_filter: str | None,
    max_lines: int = 30,
) -> str:
    rows = read_stock_rows(spreadsheet)
    if not rows:
        return "Остатки пусты — операций пока не было."

    # Фильтрация
    filtered = []
    for r in rows:
        product = str(r.get("Товар", "")).strip()
        location = str(r.get("Точка", "")).strip()
        if product_query and product_query.lower() not in product.lower():
            continue
        if location_filter and location != location_filter:
            continue
        try:
            qty = float(str(r.get("Количество", "0")).replace(",", "."))
        except ValueError:
            qty = 0.0
        if qty <= 0:
            continue
        filtered.append({
            "product": product,
            "location": location,
            "qty": qty,
            "unit": str(r.get("Единица", "")).strip(),
        })

    if not filtered:
        msg = "Не нашёл остатков"
        if product_query:
            msg += f" по запросу «{product_query}»"
        if location_filter:
            msg += f" на {location_filter}"
        return msg + "."

    # Группировка по товару
    by_product: dict[str, list[dict]] = defaultdict(list)
    for f in filtered:
        by_product[f["product"]].append(f)

    parts = ["Остатки:"]
    truncated = False
    for product, items in list(by_product.items())[:max_lines]:
        parts.append(f"")
        parts.append(f"{product}:")
        for it in sorted(items, key=lambda x: x["location"]):
            qty_str = f"{int(it['qty'])}" if it["qty"] == int(it["qty"]) else f"{it['qty']:.2f}"
            parts.append(f"  {it['location']}: {qty_str} {it['unit']}")
    if len(by_product) > max_lines:
        truncated = True
        parts.append("")
        parts.append(
            f"(показано первых {max_lines} из {len(by_product)} товаров. "
            f"Уточни запрос: /stock <часть_названия>)"
        )

    return "\n".join(parts)
