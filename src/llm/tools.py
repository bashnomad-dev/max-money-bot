"""Определения 8 tools для LLM function calling.

Эти схемы используются и GigaChat, и Claude (через адаптацию).
См. полное описание — docs/llm-parsing.md §3.
"""

UNITS_ENUM = ["шт.", "м2", "м3", "м.п.", "рул", "уп.", "кг", "меш.", "л.", "м"]
LOCATIONS_ENUM = ["Магазин Зинино", "Магазин Кармалы"]
PAYMENT_ENUM = ["наличные", "карта", "счёт", "не указано"]
EXPENSE_CATEGORIES = [
    "аренда помещения", "зарплата", "коммунальные / связь",
    "реклама / маркетинг", "транспорт / доставка",
    "налоги / банк / эквайринг", "оборудование / ремонт", "прочее",
]


def _goods_line_schema() -> dict:
    return {
        "type": "object",
        "required": ["name", "qty", "unit"],
        "properties": {
            "name": {"type": "string"},
            "qty": {"type": "number", "exclusiveMinimum": 0},
            "unit": {"type": "string"},  # не enum: модель может ошибиться, канонизация на стороне бота
        },
    }


def _confidence_fields() -> dict:
    return {
        "text_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "amount_confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "quantity_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    }


TOOLS = [
    {
        "name": "record_sale",
        "description": "Зафиксировать продажу товара. Создаёт приход в Деньгах + выбытие в Товарах + пересчёт Остатков транзакционно.",
        "parameters": {
            "type": "object",
            "required": [
                "amount_rub", "lines", "location", "payment",
                "text_confidence", "amount_confidence", "quantity_confidence",
            ],
            "properties": {
                "amount_rub": {"type": "integer"},
                "lines": {"type": "array", "minItems": 1, "items": _goods_line_schema()},
                "location": {"type": "string", "enum": LOCATIONS_ENUM},
                "customer": {"type": ["string", "null"]},
                "payment": {"type": "string", "enum": PAYMENT_ENUM},
                "comment": {"type": ["string", "null"]},
                **_confidence_fields(),
            },
        },
    },
    {
        "name": "record_purchase",
        "description": "Зафиксировать закупку товара. Расход в Деньгах + поступление в Товарах + пересчёт Остатков и СВ-цены.",
        "parameters": {
            "type": "object",
            "required": [
                "amount_rub", "supplier", "lines", "destination", "payment",
                "text_confidence", "amount_confidence", "quantity_confidence",
            ],
            "properties": {
                "amount_rub": {"type": "integer"},
                "supplier": {"type": "string"},
                "lines": {"type": "array", "minItems": 1, "items": _goods_line_schema()},
                "destination": {"type": "string", "enum": LOCATIONS_ENUM},
                "payment": {"type": "string", "enum": PAYMENT_ENUM},
                "comment": {"type": ["string", "null"]},
                **_confidence_fields(),
            },
        },
    },
    {
        "name": "record_return",
        "description": "Возврат. direction='from_customer' — покупатель вернул товар, мы вернули деньги. direction='to_supplier' — обратно.",
        "parameters": {
            "type": "object",
            "required": [
                "direction", "amount_rub", "counterparty", "lines", "location",
                "text_confidence", "amount_confidence", "quantity_confidence",
            ],
            "properties": {
                "direction": {"type": "string", "enum": ["from_customer", "to_supplier"]},
                "amount_rub": {"type": "integer"},
                "counterparty": {"type": "string"},
                "lines": {"type": "array", "minItems": 1, "items": _goods_line_schema()},
                "location": {"type": "string", "enum": LOCATIONS_ENUM},
                "payment": {"type": "string", "enum": PAYMENT_ENUM},
                "comment": {"type": ["string", "null"]},
                **_confidence_fields(),
            },
        },
    },
    {
        "name": "record_cashflow",
        "description": "Финансовая операция без движения товара: аренда, зарплата, налоги, внесение из своих, изъятие на личное, прочий приход.",
        "parameters": {
            "type": "object",
            "required": ["op_type", "amount_rub", "description", "payment",
                         "text_confidence", "amount_confidence"],
            "properties": {
                "op_type": {"type": "string", "enum": ["расход", "прочий приход", "внесение", "изъятие"]},
                "amount_rub": {"type": "integer"},
                "description": {"type": "string"},
                "category": {"type": ["string", "null"], "enum": [*EXPENSE_CATEGORIES, None]},
                "counterparty": {"type": ["string", "null"]},
                "location": {"type": ["string", "null"], "enum": [*LOCATIONS_ENUM, None]},
                "payment": {"type": "string", "enum": PAYMENT_ENUM},
                "text_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "amount_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
    {
        "name": "record_writeoff_or_movement",
        "description": "Товарная операция без денег. op_type='списание' — брак/недостача. op_type='перемещение' — между точками.",
        "parameters": {
            "type": "object",
            "required": ["op_type", "lines", "text_confidence", "quantity_confidence"],
            "properties": {
                "op_type": {"type": "string", "enum": ["списание", "перемещение"]},
                "location": {"type": ["string", "null"], "enum": [*LOCATIONS_ENUM, None]},
                "source": {"type": ["string", "null"], "enum": [*LOCATIONS_ENUM, None]},
                "destination": {"type": ["string", "null"], "enum": [*LOCATIONS_ENUM, None]},
                "lines": {"type": "array", "minItems": 1, "items": _goods_line_schema()},
                "comment": {"type": ["string", "null"]},
                "text_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "quantity_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
    {
        "name": "record_inventory",
        "description": "Факт инвентаризации: для каждой позиции — фактическое количество. Бот сравнит с расчётным и запишет корректировку.",
        "parameters": {
            "type": "object",
            "required": ["location", "facts", "text_confidence", "quantity_confidence"],
            "properties": {
                "location": {"type": "string", "enum": LOCATIONS_ENUM},
                "facts": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["name", "qty", "unit"],
                        "properties": {
                            "name": {"type": "string"},
                            "qty": {"type": "number", "minimum": 0},
                            "unit": {"type": "string"},
                        },
                    },
                },
                "text_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "quantity_confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
    },
    {
        "name": "query_or_report",
        "description": "Запрос данных. type='stock' — остатки. type='period_report' — финансовый отчёт за период.",
        "parameters": {
            "type": "object",
            "required": ["type"],
            "properties": {
                "type": {"type": "string", "enum": ["stock", "period_report"]},
                "product_query": {"type": ["string", "null"]},
                "location": {"type": ["string", "null"], "enum": [*LOCATIONS_ENUM, None]},
                "period_type": {"type": ["string", "null"], "enum": ["day", "month", "quarter", "year", "custom", None]},
                "year": {"type": ["integer", "null"]},
                "month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
                "quarter": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
                "relative": {"type": ["string", "null"], "enum": ["current", "previous", None]},
                "top_metric": {"type": "string", "enum": ["выручка", "прибыль", "количество"]},
                "period_is_clear": {"type": "boolean"},
            },
        },
    },
    {
        "name": "request_clarification",
        "description": "Использовать когда непонятно или нет критичных полей. Запись не выполняется.",
        "parameters": {
            "type": "object",
            "required": ["reason", "question", "intent_hint"],
            "properties": {
                "reason": {"type": "string"},
                "question": {"type": "string"},
                "intent_hint": {
                    "type": ["string", "null"],
                    "enum": ["sale", "purchase", "return", "cashflow", "writeoff", "inventory", "report", None],
                },
            },
        },
    },
]


def tool_names() -> list[str]:
    return [t["name"] for t in TOOLS]
