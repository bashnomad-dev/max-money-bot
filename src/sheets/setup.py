"""Инициализация Google-таблицы при первом /link и /setup.

Создаёт листы с заголовками, заливает справочники Точек/Категорий,
импортирует прайс Евгения (~4883 SKU) в лист «Товары».

Импорт прайса требует data/products-import.json (готовится через scripts/parse_evgeny_price.py
+ копирование price-normalized.json -> data/products-import.json).

См. docs/data-model.md §1.12.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.config.settings import settings
from src.sheets.schema import (
    DEFAULT_CATEGORIES,
    DEFAULT_LOCATIONS,
    SHEET_CATEGORIES,
    SHEET_GOODS,
    SHEET_LOCATIONS,
    SHEET_MONEY,
    SHEET_PRODUCTS,
    SHEET_STOCK,
    SPECS,
    SheetSpec,
)

log = logging.getLogger(__name__)


class SheetsSetupError(Exception):
    pass


def open_sheet(sheet_id: str):
    """Открыть таблицу по ID. Возвращает gspread.Spreadsheet.

    На транзиентные 5xx (Google периодически отдаёт 503) — короткий retry
    с backoff 1с → 3с.
    """
    import time as _time

    import gspread  # type: ignore
    from google.oauth2.service_account import Credentials  # type: ignore
    from gspread.exceptions import APIError  # type: ignore

    creds = Credentials.from_service_account_file(
        settings.google_service_account_json,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    client = gspread.authorize(creds)

    last_exc: Exception | None = None
    for pause in (0, 1, 3):
        if pause:
            _time.sleep(pause)
        try:
            return client.open_by_key(sheet_id)
        except APIError as e:
            last_exc = e
            code = getattr(getattr(e, "response", None), "status_code", 0)
            if code in (500, 502, 503, 504):
                continue
            raise
    assert last_exc is not None
    raise last_exc


def ensure_worksheet(spreadsheet, spec: SheetSpec) -> tuple[object, bool]:
    """Гарантировать что лист существует с правильными заголовками.

    Возвращает (worksheet, created) где created=True если был создан с нуля.
    Если лист есть, но заголовки не совпадают — поднимает SheetsSetupError.
    """
    import gspread  # type: ignore

    try:
        ws = spreadsheet.worksheet(spec.name)
        # Лист с системным маркером (например «Остатки») держит заголовки в строке 2.
        if spec.a1_marker and ws.row_values(1)[:1] == [spec.a1_marker]:
            header_row = 2
        else:
            header_row = 1
        existing_headers = ws.row_values(header_row)
        if existing_headers and existing_headers[: len(spec.headers)] != spec.headers:
            # Миграция старой схемы: если существующие заголовки — точный префикс
            # новых (например, ещё нет колонки «Автор»), дописываем недостающие.
            # Иначе — реальное расхождение, не трогаем (могут быть пользовательские колонки).
            if spec.headers[: len(existing_headers)] == existing_headers:
                ws.update(f"A{header_row}", [spec.headers])
                log.info("Лист «%s»: заголовки обновлены до новой схемы (+%d)",
                         spec.name, len(spec.headers) - len(existing_headers))
            else:
                raise SheetsSetupError(
                    f"Лист «{spec.name}» имеет несовпадающие заголовки.\n"
                    f"  Ожидаем: {spec.headers}\n"
                    f"  Найдено: {existing_headers[: len(spec.headers)]}"
                )
        if not existing_headers:
            ws.update(f"A{header_row}", [spec.headers])
        return ws, False
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(
            title=spec.name,
            rows=max(1000, len(spec.headers) + 10),
            cols=len(spec.headers) + 5,  # запас для пользовательских колонок
        )
        if spec.a1_marker:
            # Маркер в A1 над заголовками
            ws.update("A1", [[spec.a1_marker]])
            ws.update("A2", [spec.headers])
        else:
            ws.update("A1", [spec.headers])
        log.info("Создан лист «%s» с %d заголовками", spec.name, len(spec.headers))
        return ws, True


def populate_locations(ws) -> int:
    """Заполнить лист Точек дефолтом (2 строки). Возвращает количество добавленных."""
    existing = ws.get_all_values()[1:]  # без заголовка
    if existing:
        log.info("Лист «%s» уже имеет %d строк, пропуск", SHEET_LOCATIONS, len(existing))
        return 0
    ws.append_rows(DEFAULT_LOCATIONS, value_input_option="USER_ENTERED")
    return len(DEFAULT_LOCATIONS)


def populate_categories(ws) -> int:
    existing = ws.get_all_values()[1:]
    if existing:
        log.info("Лист «%s» уже имеет %d строк, пропуск", SHEET_CATEGORIES, len(existing))
        return 0
    ws.append_rows(DEFAULT_CATEGORIES, value_input_option="USER_ENTERED")
    return len(DEFAULT_CATEGORIES)


def append_product_to_sheet(spreadsheet, canon: str, default_unit: str = "") -> bool:
    """Добавить один новый канон в лист «Товары» если его там ещё нет.

    Возвращает True если добавили, False если уже был. Тихо игнорирует
    ошибки чтения (например, лист пустой / Sheets 5xx) — не критично для
    основной записи операции.
    """
    try:
        ws = spreadsheet.worksheet(SHEET_PRODUCTS)
    except Exception:
        log.exception("append_product: лист «Товары» недоступен")
        return False
    try:
        existing = {row[0].strip().lower() for row in ws.get_all_values()[1:] if row and row[0].strip()}
    except Exception:
        log.exception("append_product: чтение листа упало")
        return False
    if canon.strip().lower() in existing:
        return False
    try:
        ws.append_row(
            [canon, "", default_unit or "", "", "да"],
            value_input_option="USER_ENTERED",
        )
        return True
    except Exception:
        log.exception("append_product: запись %r упала", canon)
        return False


def populate_products(ws, import_path: Path) -> int:
    """Импортировать прайс Евгения. Дедуп по канону (в прайсе один товар в 2 точках)."""
    existing = ws.get_all_values()[1:]
    if existing:
        log.info("Лист «%s» уже имеет %d строк, пропуск", SHEET_PRODUCTS, len(existing))
        return 0

    if not import_path.exists():
        raise SheetsSetupError(
            f"Файл импорта прайса не найден: {import_path}. "
            f"Положи туда docs/intake/evgeny/price-normalized.json."
        )

    data = json.loads(import_path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    rows: list[list[str | float]] = []
    for p in data["products"]:
        canon = p["name"]
        if canon in seen:
            continue
        seen.add(canon)
        rows.append(
            [
                canon,
                "",                                 # Алиасы — пустые на старте
                p.get("unit") or "",
                p.get("price_rub") or "",
                "да",
            ]
        )
    # Заливаем батчами по 1000 для скорости
    BATCH = 1000
    for i in range(0, len(rows), BATCH):
        ws.append_rows(rows[i : i + BATCH], value_input_option="USER_ENTERED")
        log.info("Импортировано %d/%d товаров", min(i + BATCH, len(rows)), len(rows))
    return len(rows)


def setup_sheet(sheet_id: str, import_prices: bool = True) -> dict:
    """Полная инициализация при первом /link.

    Возвращает отчёт-словарь:
      {'created_sheets': [...], 'imported_products': N, 'imported_locations': N, 'imported_categories': N}
    """
    spreadsheet = open_sheet(sheet_id)
    report: dict = {
        "spreadsheet_title": spreadsheet.title,
        "created_sheets": [],
        "imported_products": 0,
        "imported_locations": 0,
        "imported_categories": 0,
    }

    # Создаём листы в нужном порядке
    order = [
        SHEET_MONEY,
        SHEET_GOODS,
        SHEET_STOCK,
        SHEET_LOCATIONS,
        SHEET_CATEGORIES,
        SHEET_PRODUCTS,
    ]
    worksheets: dict[str, object] = {}
    for name in order:
        ws, created = ensure_worksheet(spreadsheet, SPECS[name])
        worksheets[name] = ws
        if created:
            report["created_sheets"].append(name)

    # Опциональный лист
    if settings.enable_processing_log_sheet:
        ws, created = ensure_worksheet(spreadsheet, SPECS["Лог обработки"])
        worksheets["Лог обработки"] = ws
        if created:
            report["created_sheets"].append("Лог обработки")

    # Заполнение справочников
    report["imported_locations"] = populate_locations(worksheets[SHEET_LOCATIONS])
    report["imported_categories"] = populate_categories(worksheets[SHEET_CATEGORIES])

    if import_prices:
        report["imported_products"] = populate_products(
            worksheets[SHEET_PRODUCTS],
            Path(settings.products_import_path),
        )

    return report
