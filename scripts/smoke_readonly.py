"""Read-only смоук новых фич против живой таблицы. Ничего не пишет.

Запуск: python -m scripts.smoke_readonly
"""
from datetime import date

from src.config.settings import settings
from src.reports.period import build_period_report, format_period_report
from src.sheets.setup import open_sheet
from src.stock.sheets_sync import detect_stock_drift


def main() -> None:
    sheet_id = settings.default_sheet_id
    print(f"Открываю таблицу {sheet_id} (read-only)…")
    ss = open_sheet(sheet_id)

    print("\n=== detect_stock_drift ===")
    drift = detect_stock_drift(ss)
    if not drift:
        print("Расхождений нет — лист «Остатки» совпадает с пересчётом.")
    else:
        print(f"Найдено расхождений: {len(drift)}")
        for product, loc, sheet_qty, calc_qty in drift[:10]:
            print(f"  • {product} на {loc}: в листе {sheet_qty:g}, должно {calc_qty:g}")

    print("\n=== отчёт за текущий месяц (топ по прибыли) ===")
    rep = build_period_report(
        ss,
        period_type="month",
        year=None,
        month=None,
        quarter=None,
        relative="current",
        location_filter=None,
        top_metric="прибыль",
        today=date.today(),
    )
    print(format_period_report(rep))


if __name__ == "__main__":
    main()
