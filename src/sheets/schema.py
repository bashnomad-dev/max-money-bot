"""Структура Google-таблицы: имена листов и заголовки колонок (v2.1).

Бот ищет колонки по имени (не по индексу). Append-only: клиент может добавлять
любые свои колонки СПРАВА — бот их не трогает.

См. docs/data-model.md §1.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# === Имена обязательных листов ===
SHEET_MONEY = "Движение денег"
SHEET_GOODS = "Движение товаров"
SHEET_STOCK = "Остатки"

# === Имена справочных листов ===
SHEET_PRODUCTS = "Товары"
SHEET_LOCATIONS = "Точки"
SHEET_CATEGORIES = "Категории"

# === Опциональный ===
SHEET_PROC_LOG = "Лог обработки"


# === Колонки ===

MONEY_HEADERS = [
    "Дата", "Время", "Тип операции", "Сумма (₽)", "Описание",
    "Категория", "Контрагент", "Точка", "Способ оплаты", "tx_id", "Автор",
]

GOODS_HEADERS = [
    "Дата", "Время", "Тип операции", "Точка", "Источник",
    "Товар", "Количество", "Единица", "Цена за ед. (₽)",
    "Контрагент", "Комментарий", "tx_id", "Автор",
]

STOCK_HEADERS = [
    "Товар", "Точка", "Количество", "Единица",
    "СВ-цена закупки (₽)", "Обновлено",
]

PRODUCTS_HEADERS = [
    "Канон", "Алиасы", "Единица по умолчанию", "Цена розничная (₽)", "Активен",
]

LOCATIONS_HEADERS = [
    "Канон", "Алиасы", "Адрес",
]

CATEGORIES_HEADERS = [
    "Категория", "Активна", "Триггеры",
]

PROC_LOG_HEADERS = [
    "Дата", "Время", "message_id", "user_id", "Тип входящего",
    "Распознанный текст", "JSON после LLM", "Статус", "Ошибка", "Ссылка на строку",
]


@dataclass(frozen=True)
class SheetSpec:
    name: str
    headers: list[str]
    is_required: bool = True
    a1_marker: str | None = None  # для системных листов (например, Остатки)


SPECS: dict[str, SheetSpec] = {
    SHEET_MONEY: SheetSpec(SHEET_MONEY, MONEY_HEADERS, is_required=True),
    SHEET_GOODS: SheetSpec(SHEET_GOODS, GOODS_HEADERS, is_required=True),
    SHEET_STOCK: SheetSpec(
        SHEET_STOCK,
        STOCK_HEADERS,
        is_required=True,
        a1_marker="СИСТЕМНЫЙ ЛИСТ — не редактировать вручную",
    ),
    SHEET_PRODUCTS: SheetSpec(SHEET_PRODUCTS, PRODUCTS_HEADERS, is_required=True),
    SHEET_LOCATIONS: SheetSpec(SHEET_LOCATIONS, LOCATIONS_HEADERS, is_required=True),
    SHEET_CATEGORIES: SheetSpec(SHEET_CATEGORIES, CATEGORIES_HEADERS, is_required=True),
    SHEET_PROC_LOG: SheetSpec(SHEET_PROC_LOG, PROC_LOG_HEADERS, is_required=False),
}


# === Дефолтные данные для справочников при setup ===

DEFAULT_LOCATIONS: list[list[str]] = [
    ["Магазин Зинино", "зинино;на Зинино;в Зинино;магазин Зинино;зенино", ""],
    ["Магазин Кармалы", "кармалы;на Кармалы;в Кармалы;магазин Кармалы;кормалы", ""],
]

DEFAULT_CATEGORIES: list[list[str]] = [
    ["аренда помещения", "да", "аренда;за помещение;за аренду"],
    ["зарплата", "да", "зарплата;зп;оплата работнику;премия"],
    ["коммунальные / связь", "да", "свет;вода;интернет;связь;электричество;газ"],
    ["реклама / маркетинг", "да", "реклама;продвижение;объявления;листовки"],
    ["транспорт / доставка", "да", "бензин;транспорт;доставка;газель;парковка"],
    ["налоги / банк / эквайринг", "да", "налог;банк;эквайринг;комиссия;расчётный счёт"],
    ["оборудование / ремонт", "да", "оборудование;ремонт;инструмент;стеллаж"],
    ["прочее", "да", ""],
]
