"""Очистка журналов таблицы перед боевым стартом (удаляет тестовые операции).

Чистит ТОЛЬКО журналы и расчётный лист:
  «Движение денег», «Движение товаров», «Остатки» — оставляет только заголовки.
Справочники «Товары» / «Точки» / «Категории» НЕ трогает (прайс остаётся).

Перед очисткой делает .xlsx-бэкап всей таблицы в backups/.
По умолчанию — сухой прогон (только показывает, что будет удалено).
Чтобы реально очистить — переменная окружения CONFIRM=YES.

Использование:
    python -m scripts.reset_ledger <SHEET_ID>          # сухой прогон
    CONFIRM=YES python -m scripts.reset_ledger <SHEET_ID>   # очистка

Цель указывается ЯВНО (argv или RESET_SHEET_ID) — без молчаливого DEFAULT_SHEET_ID.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.backup_sheets import BACKUPS_DIR, _dump_one
from src.config.settings import settings
from src.sheets.schema import SHEET_GOODS, SHEET_MONEY, SHEET_STOCK
from src.sheets.setup import open_sheet

# Журналы — заголовок в строке 1. «Остатки» — системный маркер в A1, заголовок в строке 2.
LEDGERS = {SHEET_MONEY: 1, SHEET_GOODS: 1, SHEET_STOCK: 2}


def _data_row_count(ws, header_rows: int) -> int:
    vals = ws.get_all_values()
    return max(0, len([r for r in vals if any(c for c in r)]) - header_rows)


def main() -> int:
    sheet_id = (sys.argv[1] if len(sys.argv) > 1 else "") or os.environ.get("RESET_SHEET_ID", "")
    if not sheet_id:
        print("Укажи таблицу: python -m scripts.reset_ledger <SHEET_ID>")
        return 1

    confirm = os.environ.get("CONFIRM") == "YES"
    ss = open_sheet(sheet_id)
    print(f"Таблица: «{ss.title}» ({sheet_id})")
    if sheet_id == settings.default_sheet_id:
        print("⚠️  Это DEFAULT_SHEET_ID (боевая). Убедись, что чистишь именно её.")

    # Что будет удалено
    plan = []
    for name, hdr in LEDGERS.items():
        try:
            ws = ss.worksheet(name)
        except Exception:
            print(f"  — лист «{name}» не найден, пропуск")
            continue
        n = _data_row_count(ws, hdr)
        plan.append((name, hdr, n))
        print(f"  «{name}»: будет удалено строк данных: {n} (заголовки сохраняются)")
    print("  Справочники «Товары»/«Точки»/«Категории» не трогаются.")

    if not confirm:
        print("\nСУХОЙ ПРОГОН. Реальная очистка — повтори с CONFIRM=YES.")
        return 0

    # Бэкап перед очисткой
    print("\nБэкап перед очисткой…")
    backup = _dump_one(sheet_id, BACKUPS_DIR)
    if backup is None:
        print("❌ Бэкап не удался — очистку НЕ выполняю. Поставь FORCE=YES чтобы пропустить бэкап.")
        if os.environ.get("FORCE") != "YES":
            return 2
    else:
        print(f"  бэкап: {backup}")

    # Очистка
    for name, hdr, _ in plan:
        ws = ss.worksheet(name)
        ws.batch_clear([f"A{hdr + 1}:Z"])
        print(f"  очищен «{name}» (с A{hdr + 1})")

    print("\n✅ Журналы очищены. Дальше: /пересчёт (остатки обнулятся) и можно начинать боевой учёт.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
