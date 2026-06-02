"""Тесты форматирования отчётов (без реальных Sheets — собираем структуру руками)."""
from datetime import date

from src.reports.daily import DailyReport, format_daily_report
from src.reports.period import PeriodReport, format_period_report


class TestDailyReportFormat:
    def test_empty_day(self):
        rep = DailyReport(report_date=date(2026, 6, 2))
        text = format_daily_report(rep)
        assert "Финансы за 02.06.2026" in text
        assert "Приход: 0 рублей" in text
        assert "Итог: 0 рублей" in text

    def test_with_data(self):
        rep = DailyReport(
            report_date=date(2026, 6, 2),
            income_rub=145000,
            expense_rub=78500,
            income_count=12,
            expense_count=5,
            by_location={"Магазин Зинино": 42000, "Магазин Кармалы": 24500},
            top_products=[
                ("Доска Хв 50×150×6000", 45000, 9),
                ("Цемент Стерлитамак", 28000, 87),
            ],
        )
        text = format_daily_report(rep)
        assert "Приход: 145 000 ₽" in text
        assert "Расход: 78 500 ₽" in text
        assert "Итог: +66 500 ₽" in text
        assert "Магазин Зинино: +42 000 ₽" in text
        assert "Цемент Стерлитамак" in text


class TestPeriodReportFormat:
    def test_basic_format(self):
        rep = PeriodReport(
            period_label="май 2026",
            location_filter=None,
            top_metric="выручка",
            income_rub=1_240_000,
            expense_rub=890_000,
            income_count=165,
            expense_count=42,
            by_location_net={"Магазин Зинино": 210_000, "Магазин Кармалы": 140_000},
            top_items=[("Цемент Стерлитамак", 350_000, 100_000, 1000)],
        )
        text = format_period_report(rep)
        assert "Финансовый отчёт за май 2026" in text
        assert "Приход: 1 240 000 рублей" in text
        assert "Итог: +350 000 рублей" in text
        assert "Магазин Зинино: +210 000 ₽" in text
        assert "Топ-3 товара выручка" in text

    def test_location_filter_in_title(self):
        rep = PeriodReport(
            period_label="июнь 2026",
            location_filter="Магазин Зинино",
            top_metric="выручка",
        )
        text = format_period_report(rep)
        assert "Магазин Зинино" in text
