# LLM-парсинг: голос → структурированная операция

## 1. Зачем LLM, а не regex

Голос свободный. Одна и та же продажа звучит как:
- «Продал 10 листов ГКЛ за 5 тысяч наличными»
- «На пять тыщ ушло, ГКЛ, десять листов, кэшем»
- «10 листов гипсокартона ушло за пятёрку наличкой»

Regex не вытащит. Claude tool_use с типизированными инструментами вытаскивает надёжно.

## 2. Модель и режим
- **Основная:** `claude-haiku-4-5-20251001` — быстро и дёшево, хватает для парсинга.
- **Fallback** при `critical_confidence < 0.7`: повторный вызов на `claude-sonnet-4-6`.
- **Режим:** `tool_choice = {"type": "any"}` — модель обязана вызвать один из инструментов.
- **Prompt caching:** системный промпт + tool definitions кешируются (одинаковы между вызовами).

## 3. Инструменты (14 шт.)

### 3.1 `record_sale` — продажа товара
Триггер: «продал», «продажа», «ушло Q товара за S», «отдал клиенту».

```json
{
  "name": "record_sale",
  "description": "Зафиксировать продажу товара покупателю. Пишет в три листа: Движение денег (приход), Движение товаров (продажа), Остатки (пересчёт).",
  "input_schema": {
    "type": "object",
    "required": ["amount_rub", "lines", "payment",
                 "text_confidence", "amount_confidence", "quantity_confidence"],
    "properties": {
      "amount_rub": {"type": "integer", "minimum": 1, "description": "Сумма продажи в рублях."},
      "lines": {
        "type": "array", "minItems": 1,
        "items": {
          "type": "object",
          "required": ["product", "qty", "unit"],
          "properties": {
            "product": {"type": "string", "description": "Имя товара как услышано."},
            "qty": {"type": "number", "exclusiveMinimum": 0},
            "unit": {"type": "string", "description": "Из словаря или сырая (бот канонизирует)."}
          }
        }
      },
      "counterparty": {"type": ["string", "null"], "description": "Покупатель. Для розницы обычно null."},
      "location": {"type": ["string", "null"], "description": "Точка продажи; null = дефолт из env."},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "text_confidence": {"type": "number", "minimum": 0, "maximum": 1},
      "amount_confidence": {"type": "number", "minimum": 0, "maximum": 1},
      "quantity_confidence": {"type": "number", "minimum": 0, "maximum": 1}
    }
  }
}
```

### 3.2 `record_purchase` — закупка товара
Триггер: «купил», «закупил», «получил от поставщика», «поступило от».

```json
{
  "name": "record_purchase",
  "description": "Зафиксировать закупку товара у поставщика. Пишет: Движение денег (расход), Движение товаров (поступление), Остатки (+Q, пересчёт СВ-цены).",
  "input_schema": {
    "type": "object",
    "required": ["amount_rub", "lines", "supplier", "payment",
                 "text_confidence", "amount_confidence", "quantity_confidence"],
    "properties": {
      "amount_rub": {"type": "integer", "minimum": 1},
      "lines": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/GoodsLine"}},
      "supplier": {"type": "string", "description": "Поставщик — обязательно."},
      "location": {"type": ["string", "null"], "description": "Куда поступило; null = дефолт ('склад')."},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "text_confidence": {"type": "number", "minimum": 0, "maximum": 1},
      "amount_confidence": {"type": "number", "minimum": 0, "maximum": 1},
      "quantity_confidence": {"type": "number", "minimum": 0, "maximum": 1}
    }
  }
}
```

### 3.3 `record_return_from_customer` — возврат от покупателя
Триггер: «возврат», «вернули», «отдал назад клиенту».

```json
{
  "name": "record_return_from_customer",
  "description": "Возврат товара от покупателя. Пишет: Движение денег (расход 'возврат покупателю'), Движение товаров (возврат +Q), Остатки.",
  "input_schema": {
    "type": "object",
    "required": ["amount_rub", "lines", "payment",
                 "text_confidence", "amount_confidence", "quantity_confidence"],
    "properties": {
      "amount_rub": {"type": "integer", "minimum": 1},
      "lines": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/GoodsLine"}},
      "customer": {"type": ["string", "null"]},
      "location": {"type": ["string", "null"]},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "text_confidence": {"type": "number"}, "amount_confidence": {"type": "number"}, "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.4 `record_return_to_supplier` — возврат поставщику
Триггер: «вернул поставщику», «отдал назад X», «возврат на склад X».

```json
{
  "name": "record_return_to_supplier",
  "description": "Возврат товара поставщику. Пишет: Движение денег (приход 'возврат поставщика'), Движение товаров (возврат поставщику −Q), Остатки.",
  "input_schema": {
    "type": "object",
    "required": ["amount_rub", "lines", "supplier", "payment",
                 "text_confidence", "amount_confidence", "quantity_confidence"],
    "properties": {
      "amount_rub": {"type": "integer", "minimum": 1},
      "lines": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/GoodsLine"}},
      "supplier": {"type": "string"},
      "location": {"type": ["string", "null"]},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "text_confidence": {"type": "number"}, "amount_confidence": {"type": "number"}, "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.5 `record_cashflow` — деньги без товара
Триггер: «заплатил за аренду», «зарплата», «внёс в кассу», «снял из кассы», «прочий приход».

```json
{
  "name": "record_cashflow",
  "description": "Денежная операция без движения товара: расход (аренда/зарплата/коммуналка/реклама и т.п.), прочий приход, внесение или изъятие из кассы. Только Движение денег.",
  "input_schema": {
    "type": "object",
    "required": ["op_type", "amount_rub", "category", "description", "payment",
                 "text_confidence", "amount_confidence"],
    "properties": {
      "op_type": {"type": "string", "enum": ["расход", "прочий приход", "внесение", "изъятие"]},
      "amount_rub": {"type": "integer", "minimum": 1},
      "category": {
        "type": "string",
        "enum": ["закупка товара", "аренда помещения", "зарплата", "коммунальные / связь",
                 "реклама / маркетинг", "транспорт / доставка", "налоги / банк / эквайринг",
                 "оборудование / ремонт", "прочее",
                 "внесение", "изъятие", "прочий приход"],
        "description": "Для 'расход' — реальная категория; для остальных типов — имя типа."
      },
      "counterparty": {"type": ["string", "null"]},
      "location": {"type": ["string", "null"]},
      "payment": {"type": "string", "enum": ["наличные", "карта", "счёт", "не указано"]},
      "description": {"type": "string"},
      "text_confidence": {"type": "number"},
      "amount_confidence": {"type": "number"}
    }
  }
}
```

### 3.6 `record_writeoff` — списание товара
Триггер: «списал», «бой», «недостача», «истёк срок».

```json
{
  "name": "record_writeoff",
  "description": "Списание товара (брак, недостача). Только Движение товаров и Остатки. Деньги не трогаются.",
  "input_schema": {
    "type": "object",
    "required": ["lines", "location", "reason",
                 "text_confidence", "quantity_confidence"],
    "properties": {
      "lines": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/GoodsLine"}},
      "location": {"type": "string", "description": "Откуда списываем."},
      "reason": {"type": "string", "description": "бой, недостача, истёк срок и т.п."},
      "text_confidence": {"type": "number"},
      "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.7 `record_movement` — перемещение между точками
Триггер: «перевёз», «переместил», «перекинул со склада в магазин».

```json
{
  "name": "record_movement",
  "description": "Перемещение товара между точками/складами. Пишет две строки в Движение товаров и обновляет Остатки на обеих точках. Деньги не трогаются.",
  "input_schema": {
    "type": "object",
    "required": ["lines", "from_location", "to_location",
                 "text_confidence", "quantity_confidence"],
    "properties": {
      "lines": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/GoodsLine"}},
      "from_location": {"type": "string"},
      "to_location": {"type": "string"},
      "text_confidence": {"type": "number"},
      "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.8 `record_inventory_adjustment` — корректировка факта
Триггер: «инвентаризация», «по факту», ответ в `/inventory` диалоге.

```json
{
  "name": "record_inventory_adjustment",
  "description": "Корректировка остатка товара по факту инвентаризации. Пишет в Движение товаров (тип 'инвентаризация') и Остатки.",
  "input_schema": {
    "type": "object",
    "required": ["product", "location", "actual_qty", "unit",
                 "text_confidence", "quantity_confidence"],
    "properties": {
      "product": {"type": "string"},
      "location": {"type": "string"},
      "actual_qty": {"type": "number", "minimum": 0},
      "unit": {"type": "string"},
      "text_confidence": {"type": "number"},
      "quantity_confidence": {"type": "number"}
    }
  }
}
```

### 3.9 `query_stock` — запрос остатков
Триггер: «сколько», «остатки», «что на складе», «есть ли X».

```json
{
  "name": "query_stock",
  "description": "Запросить остатки товаров. Бот читает лист Остатки и отвечает.",
  "input_schema": {
    "type": "object",
    "properties": {
      "product": {"type": ["string", "null"], "description": "null = все товары"},
      "location": {"type": ["string", "null"], "description": "null = все точки"}
    }
  }
}
```

### 3.10 `resolve_report_period` — парсинг периода для отчёта
Триггер: «отчёт за», «сводка за», `/report`.

```json
{
  "name": "resolve_report_period",
  "description": "Извлечь период отчёта и опц. метрику топа.",
  "input_schema": {
    "type": "object",
    "required": ["period_type", "period_is_clear"],
    "properties": {
      "period_type": {"type": "string", "enum": ["day", "month", "quarter", "year", "custom"]},
      "year": {"type": ["integer", "null"]},
      "month": {"type": ["integer", "null"], "minimum": 1, "maximum": 12},
      "quarter": {"type": ["integer", "null"], "minimum": 1, "maximum": 4},
      "relative": {"type": ["string", "null"], "enum": ["current", "previous", null]},
      "top_metric": {"type": "string", "enum": ["по выручке", "по прибыли", "по количеству"],
                     "description": "Дефолт 'по выручке'."},
      "location_filter": {"type": ["string", "null"], "description": "Отчёт по конкретной точке."},
      "period_is_clear": {"type": "boolean"}
    }
  }
}
```

### 3.11 `canonicalize_product` — выбор канона товара
Используется только внутри диалога канонизации (бот спросил «это X или новый?»).

```json
{
  "name": "canonicalize_product",
  "description": "Решить, относится ли произнесённое имя товара к существующему канону или это новый товар.",
  "input_schema": {
    "type": "object",
    "required": ["decision"],
    "properties": {
      "decision": {"type": "string", "enum": ["existing", "new"]},
      "canon": {"type": ["string", "null"], "description": "Если existing — выбранный канон."},
      "new_canon": {"type": ["string", "null"], "description": "Если new — каноническое имя для нового."},
      "default_unit": {"type": ["string", "null"], "description": "Для new — единица по умолчанию."}
    }
  }
}
```

### 3.12 `canonicalize_location` — выбор канона точки
Аналогично §3.11.

```json
{
  "name": "canonicalize_location",
  "input_schema": {
    "type": "object",
    "required": ["decision"],
    "properties": {
      "decision": {"type": "string", "enum": ["existing", "new"]},
      "canon": {"type": ["string", "null"]},
      "new_canon": {"type": ["string", "null"]},
      "location_type": {"type": ["string", "null"], "enum": ["магазин", "склад", null]}
    }
  }
}
```

### 3.13 `apply_edit` — правка последней операции
```json
{
  "name": "apply_edit",
  "description": "Применить точечную правку к последней операции пользователя.",
  "input_schema": {
    "type": "object",
    "required": ["field", "new_value"],
    "properties": {
      "field": {"type": "string", "enum": ["amount", "qty", "counterparty", "category", "location", "payment", "description"]},
      "new_value": {"type": ["string", "integer", "number"]}
    }
  }
}
```

### 3.14 `request_clarification` — нужно уточнение
```json
{
  "name": "request_clarification",
  "description": "Использовать когда смысл фразы непонятен или критичные поля отсутствуют. Запись не делается.",
  "input_schema": {
    "type": "object",
    "required": ["reason", "question", "intent_hint"],
    "properties": {
      "reason": {"type": "string"},
      "question": {"type": "string"},
      "intent_hint": {
        "type": ["string", "null"],
        "enum": ["sale", "purchase", "return_customer", "return_supplier",
                 "expense", "writeoff", "movement", "report", null]
      }
    }
  }
}
```

### 3.15 Shared definition `GoodsLine`
```json
{
  "GoodsLine": {
    "type": "object",
    "required": ["product", "qty", "unit"],
    "properties": {
      "product": {"type": "string"},
      "qty": {"type": "number", "exclusiveMinimum": 0},
      "unit": {"type": "string"},
      "comment": {"type": ["string", "null"]}
    }
  }
}
```

## 4. Системный промпт

```
Ты — модуль извлечения данных для голосового MAX-бота розничного магазина стройматериалов.

ВХОД: текст, расшифрованный из голосового сообщения владельца магазина.
ВЫХОД: ровно один tool_use вызов. Никакого свободного текста.

ВЫБОР ИНСТРУМЕНТА (по интенту):

ТОВАР + ДЕНЬГИ (всегда вместе):
- "продал X за Y / клиенту отдал Z" → record_sale
- "купил у поставщика P товар X за Y / получил от P, оплатил" → record_purchase
- "возврат: вернули товар X, отдал Y денег / клиент сдал" → record_return_from_customer
- "вернул поставщику P товар X, получил Y денег" → record_return_to_supplier

ТОЛЬКО ДЕНЬГИ:
- "заплатил аренду / зарплату / коммуналку / интернет / рекламу / налоги / банк / эквайринг / транспорт" → record_cashflow с op_type='расход'
- "внёс в кассу / положил в кассу / пополнил" → record_cashflow с op_type='внесение'
- "снял из кассы / забрал на личные / изъял" → record_cashflow с op_type='изъятие'
- "прочий приход / пришло (не от продажи)" → record_cashflow с op_type='прочий приход'

ТОЛЬКО ТОВАР:
- "списал X / бой / недостача / истёк срок" → record_writeoff
- "перевёз / переместил / перекинул с X на Y" → record_movement
- "по факту X штук / инвентаризация X" → record_inventory_adjustment

ЗАПРОСЫ:
- "сколько X / остатки / что на складе / есть ли X" → query_stock
- "отчёт за период / сводка за месяц" → resolve_report_period

ДИАЛОГИ (только когда бот ждёт ответ):
- ответ в диалоге канонизации товара → canonicalize_product
- ответ в диалоге канонизации точки → canonicalize_location
- правка («не 15, а 50», «измени сумму на 50») → apply_edit

ЕСЛИ НЕПОНЯТНО / НЕТ КРИТИЧНЫХ ПОЛЕЙ:
- request_clarification

КРИТИЧНЫЕ ПОЛЯ (без них — clarification, не угадывать):
- Продажа: сумма И товар И количество.
- Закупка: сумма И товар И количество И поставщик.
- Возврат покупателю: сумма И товар И количество.
- Возврат поставщику: сумма И товар И количество И поставщик.
- Расход (cashflow): сумма И категория.
- Списание: товар И количество И причина (хотя бы "не указано").
- Перемещение: товар И количество И обе точки.
- Инвентаризация: товар И фактическое количество.

ЧИСЛИТЕЛЬНЫЕ:
- "пятнадцать тысяч" = 15000, "полторы тысячи" = 1500, "восемь с половиной тысяч" = 8500.
- "тыщ"/"к"/"тыс" — тысячи. "лям"/"миллион" — миллионы. "пятёрка" = 5000 (в контексте денег).
- Двусмысленные числа (двадцать/двести, пятнадцать/пятьдесят) — выбирай вероятный вариант, но снижай amount_confidence или quantity_confidence до 0.5–0.65.

ТОВАРЫ:
- Сохраняй имя ТАК КАК СКАЗАЛ ПОЛЬЗОВАТЕЛЬ ("ГКЛ", "гипсокартон 12,5", "клей плиточный"). Канонизацию делает бот сам, не ты.
- НЕ объединяй разные товары в один lines-элемент. Каждая позиция — свой элемент массива.

ЕДИНИЦЫ ИЗМЕРЕНИЯ:
- Из словаря: шт, м, м², м³, кг, т, л, мешок, лист, рулон, упаковка, пачка, комплект, ведро, банка, тюбик, бутылка, коробка, пакет, пог. м.
- Если не услышал — пытайся из контекста ("ГКЛ — лист", "цемент — мешок", "краска — банка/литр").
- Если совсем непонятно — ставь "шт" или сырое слово.

КАТЕГОРИИ (для record_cashflow с op_type='расход'):
- "аренда / помещение / офис" → "аренда помещения"
- "зарплата / зп / премия / продавцу / грузчику" → "зарплата"
- "коммуналка / свет / вода / интернет / связь / телефон" → "коммунальные / связь"
- "реклама / маркетинг / таргет / соцсети / визитки" → "реклама / маркетинг"
- "доставка / транспорт / бензин / парковка / такси" → "транспорт / доставка"
- "налоги / банк / эквайринг / комиссия" → "налоги / банк / эквайринг"
- "оборудование / ремонт / стеллажи / тележка / весы" → "оборудование / ремонт"
- иначе → "прочее"

ТОЧКИ:
- Сохраняй как сказал ("на Ленина", "склад", "магазин"). Канонизация бот сам.
- Если "склад" без уточнения — это название точки "склад".
- Если не упомянуто — оставляй null. Бот подставит DEFAULT_LOCATION.

ОПИСАНИЕ:
- Дословный фрагмент о сути, без вводных слов.
- Не суммаризируй, не сокращай по смыслу.

CONFIDENCE:
- text_confidence: насколько уверен в распознанном Whisper тексте. 0.95+ если связно, 0.5–0.7 при подозрениях.
- amount_confidence: 0.9+ если число прозвучало однозначно, 0.5–0.7 при путанице.
- quantity_confidence: то же для количества товара.

ДЕФОЛТЫ ГОДА В ОТЧЁТАХ:
- "за январь" без года → текущий год.
- Если получившаяся дата в будущем (в январе спросили "за декабрь") → прошлый год.

ОТСУТСТВУЮЩИЕ ПОЛЯ:
- counterparty, location — если не упомянуты, ставь null. НЕ выдумывай.
- payment — если не упомянут, "не указано".

ПРИМЕРЫ:
- "Продал 10 листов ГКЛ за 5 тысяч наличными" → record_sale
- "Купил у Петровича 100 мешков штукатурки за 25 тысяч безналом" → record_purchase
- "Списал 3 мешка штукатурки бой" → record_writeoff
- "Перевёз 20 листов ГКЛ со склада в магазин" → record_movement
- "Заплатил аренду 80 тысяч на счёт" → record_cashflow расход
- "Внёс в кассу 50 тысяч" → record_cashflow внесение
- "Сколько ГКЛ на складе?" → query_stock
- "Отчёт за месяц" → resolve_report_period
- "Не пять, а пятьдесят" → apply_edit
- "Запиши штукатурку 100 мешков" (нет суммы и поставщика для закупки) → request_clarification
```

## 5. Примеры

### 5.1 Розничная продажа (S1)
**Input:** «Продал 10 листов ГКЛ за 5 тысяч, наличными»

```json
{
  "tool": "record_sale",
  "input": {
    "amount_rub": 5000,
    "lines": [{"product": "ГКЛ", "qty": 10, "unit": "лист"}],
    "counterparty": null,
    "location": null,
    "payment": "наличные",
    "text_confidence": 0.95,
    "amount_confidence": 0.95,
    "quantity_confidence": 0.95
  }
}
```

### 5.2 Оптовая продажа (S2)
**Input:** «Бригаде Иванова отгрузил 50 мешков цемента за 30 тысяч на счёт»

```json
{
  "tool": "record_sale",
  "input": {
    "amount_rub": 30000,
    "lines": [{"product": "цемент", "qty": 50, "unit": "мешок"}],
    "counterparty": "бригада Иванова",
    "location": null,
    "payment": "счёт",
    "text_confidence": 0.94, "amount_confidence": 0.93, "quantity_confidence": 0.95
  }
}
```

### 5.3 Закупка (S3)
**Input:** «Получил от Петровича 100 мешков штукатурки за 25 тысяч, безналом»

```json
{
  "tool": "record_purchase",
  "input": {
    "amount_rub": 25000,
    "lines": [{"product": "штукатурка", "qty": 100, "unit": "мешок"}],
    "supplier": "Петрович",
    "location": null,
    "payment": "счёт",
    "text_confidence": 0.96, "amount_confidence": 0.95, "quantity_confidence": 0.96
  }
}
```

### 5.4 Возврат от покупателя (S4)
**Input:** «Возврат: вернули 2 листа ГКЛ, отдал тысячу наличными»

```json
{
  "tool": "record_return_from_customer",
  "input": {
    "amount_rub": 1000,
    "lines": [{"product": "ГКЛ", "qty": 2, "unit": "лист"}],
    "customer": null,
    "location": null,
    "payment": "наличные",
    "text_confidence": 0.93, "amount_confidence": 0.94, "quantity_confidence": 0.95
  }
}
```

### 5.5 Возврат поставщику (S5)
**Input:** «Вернул Петровичу 10 мешков штукатурки, получил 2500 на счёт»

```json
{
  "tool": "record_return_to_supplier",
  "input": {
    "amount_rub": 2500,
    "lines": [{"product": "штукатурка", "qty": 10, "unit": "мешок"}],
    "supplier": "Петрович",
    "location": null,
    "payment": "счёт",
    "text_confidence": 0.95, "amount_confidence": 0.93, "quantity_confidence": 0.95
  }
}
```

### 5.6 Списание (S6)
**Input:** «Списал 3 мешка штукатурки, бой»

```json
{
  "tool": "record_writeoff",
  "input": {
    "lines": [{"product": "штукатурка", "qty": 3, "unit": "мешок"}],
    "location": null,
    "reason": "бой",
    "text_confidence": 0.97, "quantity_confidence": 0.95
  }
}
```

### 5.7 Расход без товара (S7)
**Input:** «Заплатил за аренду 80 тысяч на счёт»

```json
{
  "tool": "record_cashflow",
  "input": {
    "op_type": "расход",
    "amount_rub": 80000,
    "category": "аренда помещения",
    "counterparty": null,
    "location": null,
    "payment": "счёт",
    "description": "аренда",
    "text_confidence": 0.96, "amount_confidence": 0.95
  }
}
```

### 5.8 Внесение в кассу (S8)
**Input:** «Внёс в кассу 50 тысяч своих»

```json
{
  "tool": "record_cashflow",
  "input": {
    "op_type": "внесение",
    "amount_rub": 50000,
    "category": "внесение",
    "counterparty": "владелец",
    "location": null,
    "payment": "наличные",
    "description": "пополнение кассы из личных",
    "text_confidence": 0.97, "amount_confidence": 0.95
  }
}
```

### 5.9 Перемещение (S9)
**Input:** «Перевёз 20 листов ГКЛ со склада на магазин на Ленина»

```json
{
  "tool": "record_movement",
  "input": {
    "lines": [{"product": "ГКЛ", "qty": 20, "unit": "лист"}],
    "from_location": "склад",
    "to_location": "магазин на Ленина",
    "text_confidence": 0.94, "quantity_confidence": 0.95
  }
}
```

### 5.10 Запрос остатков (S10)
**Input:** «Сколько ГКЛ на складе?»

```json
{
  "tool": "query_stock",
  "input": {"product": "ГКЛ", "location": "склад"}
}
```

### 5.11 Инвентаризация (S11)
**Input (в диалоге `/inventory`):** «Сорок пять»

```json
{
  "tool": "record_inventory_adjustment",
  "input": {
    "product": "ГКЛ 12,5",
    "location": "склад",
    "actual_qty": 45,
    "unit": "лист",
    "text_confidence": 0.95, "quantity_confidence": 0.95
  }
}
```

### 5.12 Multi-ops продажа (S12)
**Input:** «Сегодня продал: цемент 30 мешков за 18 тысяч, ГКЛ 10 листов за 5 тысяч, всё наличными»

В MVP это **две** последовательные `record_sale` (бот сам разобьёт). Альтернатива — `record_sales_batch` (см. data-model §2.4) если LLM однозначно понимает что это батч.

### 5.13 Двусмысленная сумма → низкий amount_confidence (E)
**Input:** «Продал ГКЛ десять листов за двести наличными»

```json
{
  "tool": "record_sale",
  "input": {
    "amount_rub": 200,
    "lines": [{"product": "ГКЛ", "qty": 10, "unit": "лист"}],
    "counterparty": null,
    "location": null,
    "payment": "наличные",
    "text_confidence": 0.85,
    "amount_confidence": 0.5,
    "quantity_confidence": 0.95
  }
}
```
> Бот покажет карточку: «Я понял: 200 ₽. Если 200 000 — поправь».

### 5.14 Отчёт с метрикой и фильтром
**Input:** «Отчёт за май по прибыли по магазину на Ленина»

```json
{
  "tool": "resolve_report_period",
  "input": {
    "period_type": "month",
    "month": 5,
    "year": 2026,
    "top_metric": "по прибыли",
    "location_filter": "магазин на Ленина",
    "period_is_clear": true
  }
}
```

### 5.15 Канонизация товара (новый)
**Input (после вопроса бота «Не нашёл «жидкие гвозди». Завести как новый товар? Единица — банка?»):** «Да, банка»

```json
{
  "tool": "canonicalize_product",
  "input": {
    "decision": "new",
    "new_canon": "жидкие гвозди",
    "default_unit": "банка"
  }
}
```

### 5.16 Уточнение (нет суммы для закупки)
**Input:** «Получил от Петровича штукатурку»

```json
{
  "tool": "request_clarification",
  "input": {
    "reason": "не указана сумма и количество",
    "question": "На какую сумму и сколько мешков?",
    "intent_hint": "purchase"
  }
}
```

## 6. Стоимость и латентность

Грубая оценка на одну операцию (Haiku):
- Input: ~2200 токенов (системный промпт + 14 tool definitions + контекст диалога) — почти весь кешируется.
- Output: ~150 токенов.
- ~1.2¢ за вызов.

При 80 операциях/день — ~$1/день, ~$30/мес. С fallback на Sonnet (~15%) — +$5/мес.

Whisper: $0.006/мин. 10 сек = $0.001. 80 операций × 10 сек = $0.08/день = $2.4/мес.

**Итого внешние API: ~$30–40/мес.** Бюджет настраивается через `MONTHLY_API_BUDGET_USD`.
