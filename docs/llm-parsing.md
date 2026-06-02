# LLM-парсинг (GigaChat function calling)

> Стек v2.1 — российский. Основной LLM: **GigaChat-Max** (Сбер) через `gigachat` Python SDK. Function calling. Fallback: `ClaudeParser` (через `LLM_BACKEND_FALLBACK=claude`) для edge case если GigaChat не справится.
>
> Tools упрощены до **8 штук** (в v2.0 было 14 под Claude). GigaChat менее зрелый в multi-tool сценариях, поэтому объединяем близкие операции в один tool с дискриминатором в поле.

## 1. Зачем function calling

Голос Евгения: «Продал тридцать мешков цемента Стерлитамак Хайдел за восемнадцать тысяч наличными на Зинино». Никакая regex это не вытащит. GigaChat с function calling возвращает структурированный JSON: тип операции, товар, количество, единица, сумма, способ оплаты, точка, контрагент (null).

## 2. Модели

- **Основная:** `GigaChat-Max` — лучшее качество от Сбера, ~600-1500 ₽/мес при потоке Евгения.
- **Fallback:** `GigaChat-Pro` если Max упал или low confidence (`min(text, amount, qty) < 0.7`).
- **Кросс-backend fallback:** `ClaudeParser` через тот же интерфейс `LLMParser` (см. `src/llm/`). Переключение по `LLM_BACKEND=gigachat|claude`.

## 3. Tools (8)

Все tools возвращают `confidence: {text, amount, quantity}` (3 поля 0..1). `critical = min(text, amount, quantity)` — порог для UX-движка.

### 3.1 `record_sale` — продажа товара покупателю
Деньги (приход) + Товары (продажа) + Остатки (−) транзакционно через общий `tx_id`.

```json
{
  "name": "record_sale",
  "description": "Зафиксировать продажу товара. Создаёт приход в Деньгах + выбытие в Товарах + пересчёт Остатков.",
  "parameters": {
    "type": "object",
    "required": ["amount_rub", "lines", "location", "payment",
                 "text_confidence", "amount_confidence", "quantity_confidence"],
    "properties": {
      "amount_rub": {"type": "integer", "description": "Общая сумма продажи в рублях."},
      "lines": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "required": ["name", "qty", "unit"],
          "properties": {
            "name": {"type": "string", "description": "Товар, как сказал пользователь."},
            "qty": {"type": "number", "exclusiveMinimum": 0},
            "unit": {"type": "string"}
          }
        }
      },
      "location": {"type": "string", "enum": ["Магазин Зинино", "Магазин Кармалы"]},
      "customer": {"type": ["string", "null"], "description": "Покупатель если назван (B2B-постоянник). null если разовый."},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "comment": {"type": ["string", "null"]},
      "text_confidence": {"type": "number", "minimum": 0, "maximum": 1},
      "amount_confidence": {"type": "number", "minimum": 0, "maximum": 1},
      "quantity_confidence": {"type": "number", "minimum": 0, "maximum": 1}
    }
  }
}
```

### 3.2 `record_purchase` — закупка товара у поставщика
Деньги (расход) + Товары (поступление) + Остатки (+) + пересчёт СВ-цены.

```json
{
  "name": "record_purchase",
  "description": "Зафиксировать закупку товара. Создаёт расход в Деньгах + поступление в Товарах + пересчёт Остатков и средневзвешенной цены.",
  "parameters": {
    "type": "object",
    "required": ["amount_rub", "supplier", "lines", "destination", "payment",
                 "text_confidence", "amount_confidence", "quantity_confidence"],
    "properties": {
      "amount_rub": {"type": "integer"},
      "supplier": {"type": "string", "description": "Поставщик (контрагент)."},
      "lines": {
        "type": "array",
        "minItems": 1,
        "items": {
          "type": "object",
          "required": ["name", "qty", "unit"],
          "properties": {
            "name": {"type": "string"},
            "qty": {"type": "number", "exclusiveMinimum": 0},
            "unit": {"type": "string"},
            "price_per_unit": {"type": ["number", "null"], "description": "Цена за ед. если названа отдельно. Иначе вычислим amount/qty."}
          }
        }
      },
      "destination": {"type": "string", "enum": ["Магазин Зинино", "Магазин Кармалы"]},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "comment": {"type": ["string", "null"]},
      "text_confidence": {"type": "number"},
      "amount_confidence": {"type": "number"},
      "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.3 `record_return` — возврат (от покупателя или поставщику)
Объединяет два сценария через поле `direction`.

```json
{
  "name": "record_return",
  "description": "Зафиксировать возврат. direction='from_customer' — покупатель вернул товар, мы вернули деньги. direction='to_supplier' — мы вернули товар поставщику, он вернул деньги.",
  "parameters": {
    "type": "object",
    "required": ["direction", "amount_rub", "counterparty", "lines", "location",
                 "text_confidence", "amount_confidence", "quantity_confidence"],
    "properties": {
      "direction": {"type": "string", "enum": ["from_customer", "to_supplier"]},
      "amount_rub": {"type": "integer"},
      "counterparty": {"type": "string"},
      "lines": {"type": "array", "minItems": 1, "items": {
        "type": "object", "required": ["name", "qty", "unit"],
        "properties": {"name": {"type": "string"}, "qty": {"type": "number"}, "unit": {"type": "string"}}
      }},
      "location": {"type": "string", "enum": ["Магазин Зинино", "Магазин Кармалы"]},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "comment": {"type": ["string", "null"]},
      "text_confidence": {"type": "number"},
      "amount_confidence": {"type": "number"},
      "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.4 `record_cashflow` — приход/расход без товара
Аренда, зарплата, налоги, внесения, изъятия — всё через один tool с типом.

```json
{
  "name": "record_cashflow",
  "description": "Финансовая операция без движения товара: аренда, зарплата, налоги, внесение из своих, изъятие на личное, прочий приход.",
  "parameters": {
    "type": "object",
    "required": ["op_type", "amount_rub", "description", "location",
                 "text_confidence", "amount_confidence"],
    "properties": {
      "op_type": {"type": "string", "enum": ["расход", "прочий приход", "внесение", "изъятие"]},
      "amount_rub": {"type": "integer"},
      "description": {"type": "string", "description": "Дословный фрагмент о сути."},
      "category": {
        "type": ["string", "null"],
        "enum": [
          "аренда помещения", "зарплата", "коммунальные / связь",
          "реклама / маркетинг", "транспорт / доставка",
          "налоги / банк / эквайринг", "оборудование / ремонт", "прочее", null
        ]
      },
      "counterparty": {"type": ["string", "null"]},
      "location": {"type": ["string", "null"], "enum": ["Магазин Зинино", "Магазин Кармалы", null]},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "text_confidence": {"type": "number"},
      "amount_confidence": {"type": "number"}
    }
  }
}
```

### 3.5 `record_writeoff_or_movement` — списание или перемещение между точками
Только Товары + Остатки. Деньги не трогаются.

```json
{
  "name": "record_writeoff_or_movement",
  "description": "Только товарная операция без денег. op_type='списание' — брак/недостача (минус с точки). op_type='перемещение' — между точками (минус с source, плюс на destination).",
  "parameters": {
    "type": "object",
    "required": ["op_type", "lines", "text_confidence", "quantity_confidence"],
    "properties": {
      "op_type": {"type": "string", "enum": ["списание", "перемещение"]},
      "location": {"type": ["string", "null"], "enum": ["Магазин Зинино", "Магазин Кармалы", null]},
      "source": {"type": ["string", "null"], "enum": ["Магазин Зинино", "Магазин Кармалы", null], "description": "Только для перемещения — откуда."},
      "destination": {"type": ["string", "null"], "enum": ["Магазин Зинино", "Магазин Кармалы", null], "description": "Только для перемещения — куда."},
      "lines": {"type": "array", "minItems": 1, "items": {
        "type": "object", "required": ["name", "qty", "unit"],
        "properties": {"name": {"type": "string"}, "qty": {"type": "number"}, "unit": {"type": "string"}}
      }},
      "comment": {"type": ["string", "null"], "description": "Причина списания: «бой», «недостача», «просрочка»."},
      "text_confidence": {"type": "number"},
      "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.6 `record_inventory` — инвентаризация (корректировка факта)
Бот сравнит с расчётным остатком, разницу запишет как корректировку.

```json
{
  "name": "record_inventory",
  "description": "Зафиксировать факт инвентаризации: для каждой позиции — фактическое количество на точке. Бот сравнит с расчётным и запишет корректировку.",
  "parameters": {
    "type": "object",
    "required": ["location", "facts", "text_confidence", "quantity_confidence"],
    "properties": {
      "location": {"type": "string", "enum": ["Магазин Зинино", "Магазин Кармалы"]},
      "facts": {"type": "array", "minItems": 1, "items": {
        "type": "object", "required": ["name", "qty", "unit"],
        "properties": {"name": {"type": "string"}, "qty": {"type": "number", "minimum": 0}, "unit": {"type": "string"}}
      }},
      "text_confidence": {"type": "number"},
      "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.7 `query_or_report` — запрос данных (остатки или отчёт за период)
Объединяет «сколько X на складе?» и «отчёт за май».

```json
{
  "name": "query_or_report",
  "description": "Запрос данных. type='stock' — спросить остатки. type='period_report' — финансовый отчёт за период.",
  "parameters": {
    "type": "object",
    "required": ["type"],
    "properties": {
      "type": {"type": "string", "enum": ["stock", "period_report"]},
      "product_query": {"type": ["string", "null"], "description": "Для stock: фильтр по товару (фрагмент названия)."},
      "location": {"type": ["string", "null"], "enum": ["Магазин Зинино", "Магазин Кармалы", null]},
      "period_type": {"type": ["string", "null"], "enum": ["day", "month", "quarter", "year", "custom", null]},
      "year": {"type": ["integer", "null"]},
      "month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
      "quarter": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
      "relative": {"type": ["string", "null"], "enum": ["current", "previous", null]},
      "top_metric": {"type": "string", "enum": ["выручка", "прибыль", "количество"], "default": "выручка"},
      "period_is_clear": {"type": "boolean", "description": "Для period_report: false если не уточнили текущий или конкретный."}
    }
  }
}
```

### 3.8 `request_clarification` — нужно уточнение
Когда непонятно или нет обязательных полей. Запись не делается.

```json
{
  "name": "request_clarification",
  "description": "Использовать когда смысл фразы непонятен или критичные поля отсутствуют (нет суммы, нет товара/количества). Запись не выполняется.",
  "parameters": {
    "type": "object",
    "required": ["reason", "question", "intent_hint"],
    "properties": {
      "reason": {"type": "string", "description": "Что именно неясно (для лога)."},
      "question": {"type": "string", "description": "Вопрос пользователю (точный текст)."},
      "intent_hint": {"type": ["string", "null"], "enum": ["sale", "purchase", "return", "cashflow", "writeoff", "inventory", "report", null]}
    }
  }
}
```

## 4. Системный промпт (для GigaChat)

GigaChat лучше работает с короткими директивными промптами без длинных абстракций. Промпт прячем в системное сообщение, обновляем редко (cache-friendly).

```
Ты — модуль парсинга голосовых команд для бота учёта в строительном магазине.
Бизнес: магазин «Магазин Зинино» + магазин «Магазин Кармалы», ассортимент — пиломатериалы, цемент, метизы, отделка.

ВЫВОД: вызов ровно одного из инструментов. НИКАКОГО свободного текста.

ВЫБОР ИНСТРУМЕНТА:
- Продажа товара (есть товар + сумма) → record_sale
- Закупка товара у поставщика → record_purchase
- Возврат от покупателя / поставщику → record_return
- Деньги без товара (аренда, зарплата, налоги, внесение, изъятие) → record_cashflow
- Списание (брак, недостача) или перемещение между точками → record_writeoff_or_movement
- Инвентаризация (сверка факта) → record_inventory
- Запрос остатков или отчёта → query_or_report
- Непонятно / нет критичных полей → request_clarification

КРИТИЧНЫЕ ПОЛЯ:
- Sale, purchase, return: сумма И товар И количество.
- Cashflow: тип И сумма.
- Writeoff/movement: товар И количество (для movement ещё source И destination).
- Inventory: location И минимум один товар с количеством.
Если нет — request_clarification.

ЧИСЛИТЕЛЬНЫЕ:
- «пятнадцать тысяч» = 15000, «полторы тысячи» = 1500, «восемь с половиной тысяч» = 8500.
- «тридцать мешков» qty=30.
- «полтора куба» qty=1.5.
- Двусмысленность (двадцать/двести, пятнадцать/пятьдесят) → снижай amount_confidence/quantity_confidence до 0.5–0.7, но делай лучшую догадку.

ТОЧКИ (всегда одна из двух или null):
- «Зинино», «магазин Зинино», «на Зинино» → "Магазин Зинино"
- «Кармалы», «магазин Кармалы», «на Кармалы» → "Магазин Кармалы"
- Не упомянуто и не подразумевается → null (бот сам выберет дефолт или спросит).

ТОВАРЫ:
- Сохраняй как сказал пользователь (без нормализации) — канонизацию делает бот сам после.
- Пример: «доска 50 на 150 на 6», «цемент 25 кг», «гипсокартон 12,5».

ЕДИНИЦЫ ИЗМЕРЕНИЯ (10 канонических):
шт., м2, м3, м.п. (погонный метр), рул (рулон), уп. (упаковка), кг, меш. (мешок), л. (литр), м.
Если в речи другая форма («штук», «мешков», «квадратов») — пиши каноническую.

КАТЕГОРИИ РАСХОДА (для record_cashflow с op_type=расход):
аренда помещения, зарплата, коммунальные / связь, реклама / маркетинг,
транспорт / доставка, налоги / банк / эквайринг, оборудование / ремонт, прочее.

CONFIDENCE:
- text_confidence: насколько уверен в распознанном тексте (Whisper/GigaAM).
- amount_confidence: уверенность в сумме.
- quantity_confidence: уверенность в количестве.
Высокий 0.9+, средний 0.7-0.9, низкий <0.7.

ДЕФОЛТ ГОДА в отчётах:
- «за январь» без года → текущий год.
- Если получится будущая дата → прошлый год.

Не выдумывай поля. Если не сказано — null или omit.
```

## 5. Примеры

### 5.1 Продажа
**Input:** «Продал тридцать мешков цемента Стерлитамак Хайдел за восемнадцать тысяч наличными на Зинино»

**Tool:**
```json
{
  "tool": "record_sale",
  "input": {
    "amount_rub": 18000,
    "lines": [{"name": "цемент Стерлитамак Хайдел", "qty": 30, "unit": "меш."}],
    "location": "Магазин Зинино",
    "customer": null,
    "payment": "наличные",
    "text_confidence": 0.95,
    "amount_confidence": 0.93,
    "quantity_confidence": 0.95
  }
}
```

### 5.2 Закупка
**Input:** «Получил от Петровича сто мешков штукатурки за двадцать пять тысяч по счёту, на Кармалы»

**Tool:**
```json
{
  "tool": "record_purchase",
  "input": {
    "amount_rub": 25000,
    "supplier": "Петрович",
    "lines": [{"name": "штукатурка", "qty": 100, "unit": "меш."}],
    "destination": "Магазин Кармалы",
    "payment": "счёт",
    "text_confidence": 0.92,
    "amount_confidence": 0.94,
    "quantity_confidence": 0.93
  }
}
```

### 5.3 Возврат от покупателя
**Input:** «Возврат от Иванова, вернул два листа гипсокартона, отдал восемьсот рублей наличными, Зинино»

**Tool:**
```json
{
  "tool": "record_return",
  "input": {
    "direction": "from_customer",
    "amount_rub": 800,
    "counterparty": "Иванов",
    "lines": [{"name": "гипсокартон", "qty": 2, "unit": "лист"}],
    "location": "Магазин Зинино",
    "payment": "наличные",
    "text_confidence": 0.93,
    "amount_confidence": 0.95,
    "quantity_confidence": 0.95
  }
}
```

### 5.4 Расход (аренда)
**Input:** «Заплатил аренду восемьдесят тысяч по счёту за Зинино»

**Tool:**
```json
{
  "tool": "record_cashflow",
  "input": {
    "op_type": "расход",
    "amount_rub": 80000,
    "description": "аренда",
    "category": "аренда помещения",
    "counterparty": null,
    "location": "Магазин Зинино",
    "payment": "счёт",
    "text_confidence": 0.96,
    "amount_confidence": 0.97
  }
}
```

### 5.5 Списание
**Input:** «Списал три мешка штукатурки на Зинино, бой»

**Tool:**
```json
{
  "tool": "record_writeoff_or_movement",
  "input": {
    "op_type": "списание",
    "location": "Магазин Зинино",
    "lines": [{"name": "штукатурка", "qty": 3, "unit": "меш."}],
    "comment": "бой",
    "text_confidence": 0.94,
    "quantity_confidence": 0.95
  }
}
```

### 5.6 Перемещение
**Input:** «Перевёз двадцать листов гипсокартона из Зинино в Кармалы»

**Tool:**
```json
{
  "tool": "record_writeoff_or_movement",
  "input": {
    "op_type": "перемещение",
    "source": "Магазин Зинино",
    "destination": "Магазин Кармалы",
    "lines": [{"name": "гипсокартон", "qty": 20, "unit": "лист"}],
    "text_confidence": 0.93,
    "quantity_confidence": 0.95
  }
}
```

### 5.7 Инвентаризация (батч)
**Input:** «Инвентаризация Зинино: цемент Стерлитамак сорок семь мешков, доска пятьдесят на сто пятьдесят двенадцать штук, гипсокартон двенадцать с половиной восемнадцать листов»

**Tool:**
```json
{
  "tool": "record_inventory",
  "input": {
    "location": "Магазин Зинино",
    "facts": [
      {"name": "цемент Стерлитамак", "qty": 47, "unit": "меш."},
      {"name": "доска 50х150", "qty": 12, "unit": "шт."},
      {"name": "гипсокартон 12,5", "qty": 18, "unit": "лист"}
    ],
    "text_confidence": 0.88,
    "quantity_confidence": 0.9
  }
}
```

### 5.8 Запрос остатков
**Input:** «Сколько цемента в Зинино?»

**Tool:**
```json
{
  "tool": "query_or_report",
  "input": {
    "type": "stock",
    "product_query": "цемент",
    "location": "Магазин Зинино"
  }
}
```

### 5.9 Отчёт за месяц с метрикой
**Input:** «Отчёт за май по прибыли»

**Tool:**
```json
{
  "tool": "query_or_report",
  "input": {
    "type": "period_report",
    "period_type": "month",
    "month": 5,
    "year": 2026,
    "top_metric": "прибыль",
    "period_is_clear": true
  }
}
```

### 5.10 Уточнение периода
**Input:** «Сделай отчёт за месяц»

**Tool:**
```json
{
  "tool": "query_or_report",
  "input": {
    "type": "period_report",
    "period_type": "month",
    "top_metric": "выручка",
    "period_is_clear": false
  }
}
```
→ Бот: «За какой месяц — текущий или конкретный?»

### 5.11 Уточнение (нет суммы)
**Input:** «Продал тридцать мешков цемента»

**Tool:**
```json
{
  "tool": "request_clarification",
  "input": {
    "reason": "продажа без указания суммы",
    "question": "За сколько продал 30 мешков цемента?",
    "intent_hint": "sale"
  }
}
```

### 5.12 Двусмысленная сумма
**Input:** «Продал доску за двести рублей»

**Tool:**
```json
{
  "tool": "record_sale",
  "input": {
    "amount_rub": 200,
    "lines": [{"name": "доска", "qty": 1, "unit": "шт."}],
    "location": "Магазин Зинино",
    "payment": "не указано",
    "text_confidence": 0.85,
    "amount_confidence": 0.55,
    "quantity_confidence": 0.7
  }
}
```
→ Бот показывает карточку: «Я понял 200 ₽ за 1 доску. Если 200 000 — поправь».

## 6. LLM-абстракция в коде

`src/llm/base.py`:
```python
class LLMParser(Protocol):
    async def parse(self, text: str, system_prompt: str) -> ParsedCommand: ...
```

`src/llm/gigachat_parser.py` — основная реализация через `gigachat` SDK.
`src/llm/claude_parser.py` — fallback через `anthropic` SDK для случая если GigaChat не справляется.
`src/llm/factory.py` — `get_parser()` читает `LLM_BACKEND` из env.

Переключение `GigaChat ↔ Claude` — одна переменная в `.env`. Системный промпт и tool definitions хранятся в `src/llm/prompts.py` и `src/llm/tools.py` — общие для обоих backend.

## 7. Стоимость

**GigaAM** (STT) — 0 ₽ (локально на VPS, бесплатно после загрузки модели ~1 ГБ).

**GigaChat-Max** (LLM) на потоке Евгения (~50-100 операций/день):
- Input: ~1500 токенов (системный промпт + tools + текст) — кешируется.
- Output: ~100 токенов.
- Тариф Сбера: токенозависимый, ~600-1500 ₽/мес.

**Итого LLM+STT: 600-1500 ₽/мес** (в десятки раз дешевле, чем Whisper+Claude).

Бюджет владельца через `MONTHLY_API_BUDGET_RUB` — при превышении предупреждение в чат.
