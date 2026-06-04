"""E2E проверка путей записи на ОТДЕЛЬНОЙ тестовой таблице.

Сервисный аккаунт не может создавать файлы (нет квоты Drive), поэтому таблицу
создаёшь ты и шаришь на сервисный аккаунт (Редактор). Боевую таблицу не трогает.

Запуск: E2E_SHEET_ID=<id> python -m scripts.e2e_write_paths
        либо python -m scripts.e2e_write_paths <id>
"""
import os
import sys
from datetime import datetime

from src.bot.pipeline import _negative_stock_warning
from src.config.settings import settings
from src.domain.operation import (
    Confidence,
    GoodsLine,
    Location,
    PaymentMethod,
    Purchase,
    Sale,
)
from src.sheets.schema import SHEET_GOODS, SHEET_MONEY, SHEET_STOCK
from src.sheets.setup import setup_sheet
from src.sheets.writer import edit_last_field, write_purchase, write_sale
from src.stock.sheets_sync import detect_stock_drift, repair_full


def _client():
    import gspread
    from google.oauth2.service_account import Credentials

    creds = Credentials.from_service_account_file(
        settings.google_service_account_json,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


def _conf():
    return Confidence(text=0.95, amount=0.95, quantity=0.95)


def ok(cond: bool, msg: str) -> None:
    print(("  ✅ " if cond else "  ❌ ") + msg)
    if not cond:
        raise AssertionError(msg)


def main() -> None:
    sid = os.environ.get("E2E_SHEET_ID") or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not sid:
        print("Укажи ID тестовой таблицы: E2E_SHEET_ID=<id> python -m scripts.e2e_write_paths")
        raise SystemExit(1)
    if sid == settings.default_sheet_id:
        print("ОТКАЗ: это боевая таблица (DEFAULT_SHEET_ID). Нужна отдельная тестовая.")
        raise SystemExit(1)

    client = _client()
    print(f"Тестовая таблица id={sid}")
    if True:
        print("setup_sheet (без импорта прайса)…")
        rep = setup_sheet(sid, import_prices=False)
        ok(SHEET_STOCK in rep["created_sheets"] or rep["created_sheets"] == [],
           f"листы готовы (созданы: {rep['created_sheets']})")
        ss = client.open_by_key(sid)

        now = datetime(2026, 6, 4, 10, 0)

        print("\n1) Закупка 100 цемент @600 на Зинино")
        purchase = Purchase(
            tx_id="tp_0001", occurred_at=now, amount_kopecks=6_000_000, supplier="Петрович",
            lines=[GoodsLine(name="цемент", qty=100, unit="меш.", price_per_unit_rub=600)],
            destination=Location.ZININO, payment=PaymentMethod.TRANSFER,
            confidence=_conf(), raw_text="x",
        )
        write_purchase(ss, purchase)
        repair_full(ss)
        drift = detect_stock_drift(ss)
        ok(drift == [], f"после repair drift пуст (было: {drift})")

        print("\n2) _esc: товар с ведущим '+' не ломается в #ERROR!")
        plus = Purchase(
            tx_id="tp_0002", occurred_at=now, amount_kopecks=300_000, supplier="Леруа",
            lines=[GoodsLine(name="+ ТестТовар", qty=3, unit="шт.", price_per_unit_rub=1000)],
            destination=Location.ZININO, payment=PaymentMethod.TRANSFER,
            confidence=_conf(), raw_text="x",
        )
        write_purchase(ss, plus)
        goods = ss.worksheet(SHEET_GOODS)
        col_f = [r for r in goods.col_values(6)]
        ok("+ ТестТовар" in col_f, f"имя сохранилось как текст, не #ERROR! (колонка Товар: {col_f[-2:]})")
        ok("#ERROR!" not in col_f, "нигде нет #ERROR!")

        print("\n3) Продажа 30 цемент @700 на Зинино")
        sale = Sale(
            tx_id="ts_0003", occurred_at=now, amount_kopecks=2_100_000,
            lines=[GoodsLine(name="цемент", qty=30, unit="меш.", price_per_unit_rub=700)],
            location=Location.ZININO, payment=PaymentMethod.CASH,
            confidence=_conf(), raw_text="x",
        )
        sale_res = write_sale(ss, sale)
        repair_full(ss)
        # цемент: 100 - 30 = 70
        drift = detect_stock_drift(ss)
        ok(drift == [], f"после продажи+repair drift пуст (было: {drift})")

        print("\n4) /edit last: меняем сумму продажи на 25000")
        edit_last_field(ss, sale_res.refs_as_dicts(), "сумма", "25000")
        money = ss.worksheet(SHEET_MONEY)
        money_ref = next(r for r in sale_res.refs_as_dicts() if r["sheet"] == SHEET_MONEY)
        cell_val = money.cell(money_ref["row_index"], 4).value  # колонка «Сумма (₽)»
        ok(str(cell_val) == "25000", f"в строке {money_ref['row_index']} сумма стала {cell_val}")

        print("\n5) Карточка минуса: продажа 999 цемента (остаток 70)")
        big = sale.model_copy(update={
            "tx_id": "ts_0004",
            "lines": [GoodsLine(name="цемент", qty=999, unit="меш.")],
        })
        warn = _negative_stock_warning(ss, big)
        ok(warn is not None and "минус" in warn, f"предупреждение выдано: {warn!r}")

        print("\n6) Детект ручной правки: портим Остатки → repair чинит")
        stock = ss.worksheet(SHEET_STOCK)
        recs = stock.get_all_records(head=2)
        # найдём строку цемента (данные с 3-й строки: маркер A1, заголовок строка 2)
        target_row = None
        for i, r in enumerate(recs, start=3):
            if str(r.get("Товар", "")).strip() == "цемент":
                target_row = i
                break
        ok(target_row is not None, f"строка цемента найдена: {target_row}")
        stock.update_cell(target_row, 3, 999)  # портим количество
        drift = detect_stock_drift(ss)
        ok(any(d[0] == "цемент" and d[2] == 999 for d in drift), f"drift поймал ручную правку: {drift}")
        repair_full(ss)
        ok(detect_stock_drift(ss) == [], "после repair drift снова пуст")

        print("\nВСЁ ЗЕЛЁНОЕ ✅")
        print(f"Таблица осталась с тестовыми данными — удали её сам: {sid}")


if __name__ == "__main__":
    main()
