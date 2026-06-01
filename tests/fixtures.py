"""Тестовые кейсы для парсера, маппера в Sheets и пересчёта остатков.

Источник — SPEC §5 / scenarios.md (магазин стройматериалов, v2.0)."""
from typing import Final


# === Продажи (G1, G2) ===

SALE_CASES: Final = [
    # G1: розничная продажа
    (
        "Продал 10 листов ГКЛ за 5 тысяч, наличными",
        "record_sale",
        {
            "amount_rub": 5000,
            "lines": [{"product": "ГКЛ", "qty": 10, "unit": "лист"}],
            "counterparty": None,
            "payment": "наличные",
        },
    ),
    # G2: оптовая продажа бригаде
    (
        "Бригаде Иванова отгрузил 50 мешков цемента за 30 тысяч на счёт",
        "record_sale",
        {
            "amount_rub": 30000,
            "lines": [{"product": "цемент", "qty": 50, "unit": "мешок"}],
            "counterparty": "бригада Иванова",
            "payment": "счёт",
        },
    ),
]


# === Закупки (G3) ===

PURCHASE_CASES: Final = [
    (
        "Получил от Петровича 100 мешков штукатурки за 25 тысяч, безналом",
        "record_purchase",
        {
            "amount_rub": 25000,
            "lines": [{"product": "штукатурка", "qty": 100, "unit": "мешок"}],
            "supplier": "Петрович",
            "payment": "счёт",
        },
    ),
]


# === Возвраты (G4, G5) ===

RETURN_FROM_CUSTOMER_CASES: Final = [
    (
        "Возврат: вернули 2 листа ГКЛ, отдал тысячу наличными",
        "record_return_from_customer",
        {
            "amount_rub": 1000,
            "lines": [{"product": "ГКЛ", "qty": 2, "unit": "лист"}],
            "payment": "наличные",
        },
    ),
]

RETURN_TO_SUPPLIER_CASES: Final = [
    (
        "Вернул Петровичу 10 мешков штукатурки, получил 2500 на счёт",
        "record_return_to_supplier",
        {
            "amount_rub": 2500,
            "lines": [{"product": "штукатурка", "qty": 10, "unit": "мешок"}],
            "supplier": "Петрович",
            "payment": "счёт",
        },
    ),
]


# === Списания, перемещения (G6, G10) ===

WRITEOFF_CASES: Final = [
    (
        "Списал 3 мешка штукатурки, бой",
        "record_writeoff",
        {
            "lines": [{"product": "штукатурка", "qty": 3, "unit": "мешок"}],
            "reason": "бой",
        },
    ),
]

MOVEMENT_CASES: Final = [
    (
        "Перевёз 20 листов ГКЛ со склада на магазин на Ленина",
        "record_movement",
        {
            "lines": [{"product": "ГКЛ", "qty": 20, "unit": "лист"}],
            "from_location": "склад",
            "to_location": "магазин на Ленина",
        },
    ),
]


# === Деньги без товара (G7, G8, G9) ===

CASHFLOW_CASES: Final = [
    # G7: расход на аренду
    (
        "Заплатил за аренду 80 тысяч на счёт",
        "record_cashflow",
        {
            "op_type": "расход",
            "amount_rub": 80000,
            "category": "аренда помещения",
            "payment": "счёт",
        },
    ),
    # G8: внесение
    (
        "Внёс в кассу 50 тысяч своих",
        "record_cashflow",
        {
            "op_type": "внесение",
            "amount_rub": 50000,
            "category": "внесение",
            "payment": "наличные",
        },
    ),
    # G9: изъятие
    (
        "Снял из кассы 20 тысяч на личные",
        "record_cashflow",
        {
            "op_type": "изъятие",
            "amount_rub": 20000,
            "category": "изъятие",
        },
    ),
]


# === Запросы (G11) ===

STOCK_QUERY_CASES: Final = [
    (
        "Сколько ГКЛ на складе?",
        "query_stock",
        {"product": "ГКЛ", "location": "склад"},
    ),
    (
        "А вообще сколько ГКЛ?",
        "query_stock",
        {"product": "ГКЛ", "location": None},
    ),
    (
        "Остатки",
        "query_stock",
        {"product": None, "location": None},
    ),
]


# === Отчёты (G12, G13, G14) ===

REPORT_PERIOD_CASES: Final = [
    # неоднозначно — нужно уточнение
    (
        "Сделай отчёт за месяц",
        "resolve_report_period",
        {"period_type": "month", "period_is_clear": False, "top_metric": "по выручке"},
    ),
    # с метрикой и фильтром по точке
    (
        "Отчёт за май по прибыли по магазину на Ленина",
        "resolve_report_period",
        {
            "period_type": "month",
            "month": 5,
            "top_metric": "по прибыли",
            "location_filter": "магазин на Ленина",
            "period_is_clear": True,
        },
    ),
    # по количеству
    (
        "Отчёт за квартал по количеству",
        "resolve_report_period",
        {"period_type": "quarter", "top_metric": "по количеству", "period_is_clear": False},
    ),
]


# === Крупные суммы и низкий confidence (E1, E5) ===

LARGE_AMOUNT_CASES: Final = [
    # E1: закупка > 100k → карточка
    (
        "Закупил у Петровича цемент на сто пятьдесят тысяч",
        "record_purchase",
        {
            "amount_rub": 150000,
            "supplier": "Петрович",
            # не хватает кол-ва — может быть clarification, может быть карточка дозаполнения
            "expected_ux": "card_with_missing_qty",
        },
    ),
]

AMBIGUOUS_AMOUNT_CASES: Final = [
    # E5: двусмысленная сумма → низкий amount_confidence → карточка
    (
        "Продал ГКЛ десять листов за двести наличными",
        "record_sale",
        {
            "amount_rub": 200,
            "lines": [{"product": "ГКЛ", "qty": 10, "unit": "лист"}],
            "expected_amount_confidence_below": 0.7,
        },
    ),
]


# === Канонизация (E2, E3, E4) ===

PRODUCT_CANONICALIZATION_CASES: Final = [
    # E2: ответ в диалоге канонизации нового товара
    (
        "Да, банка",
        "canonicalize_product",
        {"decision": "new", "default_unit": "банка"},
    ),
    # E3: ответ в диалоге «это известный?»
    (
        "Это «штукатурка»",
        "canonicalize_product",
        {"decision": "existing"},
    ),
]

LOCATION_CANONICALIZATION_CASES: Final = [
    # E4: ответ про новую точку
    (
        "Магазин",
        "canonicalize_location",
        {"decision": "new", "location_type": "магазин"},
    ),
]


# === Multi-ops (E8) ===

MULTI_OPS_CASES: Final = [
    (
        "Сегодня продал: цемент 30 мешков за 18 тысяч, ГКЛ 10 листов за 5 тысяч, всё наличными",
        "record_sales_batch_or_two_sales",
        {
            "sales_count": 2,
            "totals_by_product": {"цемент": 18000, "ГКЛ": 5000},
        },
    ),
]


# === Правки (C4) ===

EDIT_CASES: Final = [
    (
        "Не пять, а пятьдесят",
        "apply_edit",
        {"field": "amount", "new_value": 50000},
    ),
    (
        "Измени количество на 12",
        "apply_edit",
        {"field": "qty", "new_value": 12},
    ),
]


# === Уточнения (F2, ТЗ §30 эквиваленты) ===

CLARIFICATION_CASES: Final = [
    # F2: нерелевантно
    (
        "Как дела бот",
        "request_clarification",
        {"intent_hint": None},
    ),
    # нет суммы для продажи
    (
        "Продал 10 листов ГКЛ",
        "request_clarification",
        {"intent_hint": "sale"},
    ),
    # нет товара
    (
        "Закупка 25 тысяч у Петровича",
        "request_clarification",
        {"intent_hint": "purchase"},
    ),
    # нет количества для перемещения
    (
        "Перевёз ГКЛ со склада в магазин",
        "request_clarification",
        {"intent_hint": "movement"},
    ),
]


# === Дневной отчёт (G12) — формат ===

DAILY_REPORT_CASE: Final = {
    "rows_in_money": [
        {"op_type": "продажа", "amount_rub": 87000, "count": 15},
        {"op_type": "закупка", "amount_rub": 35200, "count": 2},
        {"op_type": "расход", "amount_rub": 8500, "count": 3,
         "by_category": {"зарплата": 8000, "прочее": 500}},
        {"op_type": "возврат покупателю", "amount_rub": 2000, "count": 1},
    ],
    "expected_text_contains": [
        "Продажи: 87 000 ₽ (15 операций)",
        "Закупки: 35 200 ₽ (2)",
        "Прочие расходы: 8 500 ₽",
        "Итог по кассе: +41 300 ₽",
    ],
}

EMPTY_DAY_REPORT_CASE: Final = {
    "rows_in_money": [],
    "expected_text_contains": [
        "Продажи: 0 ₽",
        "Закупки: 0 ₽",
        "Итог по кассе: 0 ₽",
        "Сегодня операций не было.",
    ],
}


# === Дедупликация (E7) ===

DEDUP_CASE: Final = {
    "first_text": "Продал 10 листов ГКЛ за 5 тысяч наличными",
    "first_at": "2026-05-31T14:30:00+03:00",
    "duplicate_text": "Продал 10 листов ГКЛ за 5 тысяч наличными",
    "duplicate_at": "2026-05-31T14:34:00+03:00",
    "expected_dedup_triggered": True,
}


# === Инвентаризация (C8) ===

INVENTORY_CASES: Final = [
    # ответ в /inventory диалоге
    (
        "Сорок пять",
        "record_inventory_adjustment",
        {"actual_qty": 45},
    ),
]


# === Транзакционность (T1, T2, T3) ===

TRANSACTION_CASES: Final = {
    "sale_full_transaction": {
        "input": "Продал 10 листов ГКЛ за 5 тысяч наличными",
        "expected_writes": {
            "Движение денег": 1,
            "Движение товаров": 1,
            "Остатки": "update",
        },
        "tx_id_present": True,
    },
    "purchase_full_transaction": {
        "input": "Получил от Петровича 100 мешков штукатурки за 25 тысяч безналом",
        "expected_writes": {
            "Движение денег": 1,
            "Движение товаров": 1,
            "Остатки": "update_with_avg_price",
        },
        "tx_id_present": True,
    },
    "movement_two_rows_one_tx": {
        "input": "Перевёз 20 листов ГКЛ со склада на магазин на Ленина",
        "expected_writes": {
            "Движение денег": 0,
            "Движение товаров": 2,
            "Остатки": "update_both_locations",
        },
        "tx_id_present": True,
    },
    "expense_money_only": {
        "input": "Заплатил аренду 80 тысяч на счёт",
        "expected_writes": {
            "Движение денег": 1,
            "Движение товаров": 0,
            "Остатки": "no_change",
        },
        "tx_id_present": False,
    },
}
