"""Парсинг Прайс 2025.xls Евгения → нормализованный JSON.

Структура исходника (TDSheet, 9793 строк, 5 колонок):
  ряд 1: "Розничный прайс-лист"
  ряд 3: "Магазин"
  ряд 4: headers (Номенклатура / ... / Цена (руб.) / Единица измерения)
  ряд 5: "Магазин Зинино"   ← разделитель точки
  далее: либо строка-категория (только название), либо товар (название + цена + единица)
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import xlrd

SRC = Path("docs/intake/evgeny/Прайс 2025.xls")
OUT_JSON = Path("docs/intake/evgeny/price-normalized.json")
OUT_SUMMARY = Path("docs/intake/evgeny/price-summary.md")


def cell(sheet, row, col):
    try:
        v = sheet.cell_value(row, col)
        return str(v).strip() if v not in (None, "") else ""
    except IndexError:
        return ""


def looks_like_price(s):
    if not s:
        return False
    cleaned = s.replace(",", ".").replace(" ", "").replace("\xa0", "")
    try:
        float(cleaned)
        return True
    except ValueError:
        return False


def parse_price(s):
    return float(s.replace(",", ".").replace(" ", "").replace("\xa0", ""))


def main():
    wb = xlrd.open_workbook(str(SRC))
    sheet = wb.sheets()[0]
    print(f"Лист: {sheet.name}, {sheet.nrows} строк, {sheet.ncols} колонок")

    products = []
    current_location = None
    current_category = None
    skipped_rows = 0

    for i in range(sheet.nrows):
        c0 = cell(sheet, i, 0)
        c1 = cell(sheet, i, 1)
        c2 = cell(sheet, i, 2)
        c3 = cell(sheet, i, 3)
        c4 = cell(sheet, i, 4)
        cells = [c0, c1, c2, c3, c4]

        if not any(cells):
            continue

        name = c0
        price_str = c3
        unit = c4

        if name.lower().startswith("магазин ") and not looks_like_price(price_str):
            current_location = name
            current_category = None
            continue

        if name and not price_str and not unit:
            if name.lower() in ("номенклатура", "розничный прайс-лист", "магазин"):
                continue
            current_category = name
            continue

        if name and looks_like_price(price_str):
            products.append({
                "name": name,
                "price_rub": parse_price(price_str),
                "unit": unit or None,
                "location": current_location,
                "category": current_category,
            })
        else:
            skipped_rows += 1

    print(f"Извлечено товаров: {len(products)}")
    print(f"Пропущено строк: {skipped_rows}")

    locations = Counter(p["location"] for p in products if p["location"])
    categories = Counter(p["category"] for p in products if p["category"])
    units = Counter(p["unit"] for p in products if p["unit"])

    print(f"\nТочки ({len(locations)}):")
    for loc, n in locations.most_common():
        print(f"  {loc}: {n} товаров")

    print(f"\nКатегории (top-30 из {len(categories)}):")
    for cat, n in categories.most_common(30):
        print(f"  {cat}: {n}")

    print(f"\nЕдиницы измерения (top-20 из {len(units)}):")
    for u, n in units.most_common(20):
        print(f"  {u}: {n}")

    price_values = [p["price_rub"] for p in products]
    print(f"\nЦены: min={min(price_values):.2f}, max={max(price_values):.2f}, "
          f"median={sorted(price_values)[len(price_values)//2]:.2f}")

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "source": str(SRC),
                "total_products": len(products),
                "locations": dict(locations),
                "categories_count": len(categories),
                "units_count": len(units),
                "products": products,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nЗаписано: {OUT_JSON}")

    lines = [
        "# Прайс 2025 Евгения — извлечённая статистика",
        "",
        f"Источник: `{SRC.name}` (9793 строки в листе TDSheet).",
        f"После парсинга: **{len(products)} товаров** в {len(locations)} точках.",
        "",
        "## Точки",
        "",
    ]
    for loc, n in locations.most_common():
        lines.append(f"- **{loc}** — {n} товаров")

    lines += [
        "",
        f"## Категории ({len(categories)} штук, top-30)",
        "",
        "| Категория | Товаров |",
        "|-----------|---------|",
    ]
    for cat, n in categories.most_common(30):
        cat_esc = cat.replace("|", "\\|")
        lines.append(f"| {cat_esc} | {n} |")

    lines += [
        "",
        f"## Единицы измерения ({len(units)} штук, top-20)",
        "",
        "| Единица | Кол-во SKU |",
        "|---------|------------|",
    ]
    for u, n in units.most_common(20):
        u_esc = u.replace("|", "\\|")
        lines.append(f"| {u_esc} | {n} |")

    lines += [
        "",
        "## Цены (₽)",
        "",
        f"- Минимум: {min(price_values):.2f}",
        f"- Медиана: {sorted(price_values)[len(price_values)//2]:.2f}",
        f"- Максимум: {max(price_values):.2f}",
        "",
        "## Файлы",
        "",
        "- `price-normalized.json` — полный список товаров в нормализованном виде (для импорта в лист «Товары»).",
        "- `Прайс 2025.xls` — исходник (читается xlrd).",
    ]
    OUT_SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(f"Записано: {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
