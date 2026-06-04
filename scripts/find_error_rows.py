"""Read-only: найти строки с #ERROR! / битыми значениями в «Движении товаров»."""
from src.config.settings import settings
from src.sheets.schema import GOODS_HEADERS, SHEET_GOODS, SHEET_STOCK
from src.sheets.setup import open_sheet


def scan(ws, name: str) -> None:
    print(f"\n=== {name}: строки с #ERROR! / #REF! / #N/A ===")
    values = ws.get_all_values()
    bad_markers = ("#ERROR!", "#REF!", "#N/A", "#VALUE!", "#NAME?")
    found = False
    for i, row in enumerate(values, start=1):
        for col, cell in enumerate(row):
            if any(m in str(cell) for m in bad_markers):
                found = True
                print(f"  строка {i}, колонка {col + 1}: {row}")
                break
    if not found:
        print("  не найдено")


def main() -> None:
    ss = open_sheet(settings.default_sheet_id)
    scan(ss.worksheet(SHEET_GOODS), SHEET_GOODS)
    scan(ss.worksheet(SHEET_STOCK), SHEET_STOCK)


if __name__ == "__main__":
    main()
