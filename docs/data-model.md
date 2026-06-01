# Модель данных

## 1. Google Sheets — структура таблицы

Одна Google-таблица на магазин. Три обязательных листа + три справочных + один опциональный технический. Колонки именованы строго — бот ищет по заголовку, не по индексу. Клиент может добавлять свои колонки **только справа** от ботовских (см. SPEC §21).

### 1.1 Лист «Движение денег» (обязательный, 10 колонок)

| # | Колонка | Тип | Источник | Пример |
|---|---------|-----|----------|--------|
| 1 | Дата | ДД.ММ.ГГГГ | TZ владельца | 31.05.2026 |
| 2 | Время | ЧЧ:ММ | TZ владельца | 14:32 |
| 3 | Тип операции | enum (8 значений, см. §1.3) | LLM | продажа |
| 4 | Сумма (₽) | целое число | LLM | 5000 |
| 5 | Категория | enum (см. §1.4) или название типа | автоопределение | продажа |
| 6 | Контрагент | строка / `не указано` | LLM | Петрович |
| 7 | Точка / Склад | канон из «Точки» / `не указано` | LLM + канонизация | магазин на Ленина |
| 8 | Способ оплаты | `наличные` / `карта` / `счёт` / `не указано` | LLM | наличные |
| 9 | Описание | строка | LLM (для связанных — список товаров) | ГКЛ 10 л, цемент 5 мш |
| 10 | tx_id | UUID или пусто | бот | sale_a7f3b2 |

### 1.2 Лист «Движение товаров» (обязательный, 11 колонок)

| # | Колонка | Тип | Источник | Пример |
|---|---------|-----|----------|--------|
| 1 | Дата | ДД.ММ.ГГГГ | TZ | 31.05.2026 |
| 2 | Время | ЧЧ:ММ | TZ | 14:32 |
| 3 | Тип операции | enum (7 значений, §1.5) | LLM | продажа |
| 4 | Точка / Склад | канон из «Точки» | LLM + канон | магазин на Ленина |
| 5 | Точка-источник | канон / пусто (только для перемещений) | LLM | пусто |
| 6 | Контрагент | строка / пусто | LLM | пусто (для продажи) |
| 7 | Товар | канон из «Товары» | LLM + канон | ГКЛ 12,5 |
| 8 | Количество | число (может быть дробным) | LLM | 10 |
| 9 | Единица измерения | канон из словаря §1.6 | LLM + канон | лист |
| 10 | Цена за ед. (₽) | число / пусто | расчёт (сумма / кол-во для поступления) | 250 |
| 11 | Комментарий | строка / пусто | LLM | пусто |
| 12 | tx_id | UUID или пусто | бот (связь с «Движение денег») | sale_a7f3b2 |

> Колонка №12 (tx_id) логически 12-я; «11 колонок» в SPEC — это пользовательские. Технически в листе их 12.

### 1.3 Типы операций «Движение денег» (8 значений)

| Значение | Когда используется | Связь tx_id |
|----------|--------------------|--------------|
| продажа | приход денег за товар | да, с «продажа» в товарах |
| закупка | расход денег за товар | да, с «поступление» в товарах |
| расход | расход без товара (аренда, зарплата...) | нет |
| прочий приход | приход не от продажи | нет |
| возврат покупателю | расход денег при возврате товара | да, с «возврат покупателя» в товарах |
| возврат поставщика | приход денег при возврате поставщику | да, с «возврат поставщику» в товарах |
| внесение | пополнение кассы из личных | нет |
| изъятие | снятие из кассы на личные | нет |

### 1.4 Категории расходов (используется для типов «расход»)

**Дефолтный список (9 категорий)**, редактируется через лист «Категории»:
1. закупка товара (автоматически для типа «закупка»)
2. аренда помещения
3. зарплата
4. коммунальные / связь
5. реклама / маркетинг
6. транспорт / доставка
7. налоги / банк / эквайринг
8. оборудование / ремонт
9. прочее

Для типов, не являющихся «расходом» — категория = название типа («продажа», «внесение», «изъятие», «возврат покупателю», «возврат поставщика», «прочий приход») для удобства фильтрации.

### 1.5 Типы операций «Движение товаров» (7 значений)

| Значение | Изменение остатков | tx_id |
|----------|--------------------|--------|
| поступление | +Q | связь с «закупка» |
| продажа | −Q | связь с «продажа» |
| списание | −Q | нет |
| возврат покупателя | +Q | связь с «возврат покупателю» |
| возврат поставщику | −Q | связь с «возврат поставщика» |
| перемещение | две строки: −Q источник, +Q приёмник | внутренний tx_id (без денег) |
| инвентаризация | корректировка до факта (−Q или +Q) | нет |

### 1.6 Лист «Остатки» (обязательный, 6 колонок)

**Расчётный лист, обновляется только ботом.** Владелец руками не правит — для корректировки `/inventory`.

| # | Колонка | Тип | Пример |
|---|---------|-----|--------|
| 1 | Товар | канон | ГКЛ 12,5 |
| 2 | Единица | канон | лист |
| 3 | Точка / Склад | канон | магазин на Ленина |
| 4 | Количество | число | 47 |
| 5 | Средневзвешенная цена закупки (₽) | число / пусто | 248 |
| 6 | Обновлено | ДД.ММ.ГГГГ ЧЧ:ММ | 31.05.2026 14:32 |

Каждая комбинация `(Товар, Точка/Склад)` — отдельная строка. Если на точке товара нет — строки нет (не пишем нули).

### 1.7 Словарь единиц измерения (канонизация)

| Канон | Принимаемые алиасы |
|-------|---------------------|
| `шт` | штука, штуки, штук |
| `м` | метр, метры, метров |
| `пог. м` | погонный метр, погонных метров |
| `м²` | квадратный метр, квадраты, кв.м |
| `м³` | кубический метр, куб, кубов, кубометр |
| `кг` | килограмм, кило, килограммов |
| `т` | тонна, тонн |
| `л` | литр, литры, литров |
| `мешок` | мешки, мешков |
| `лист` | листы, листов |
| `рулон` | рулоны, рулонов |
| `упаковка` | упаковки, упаковок, уп |
| `пачка` | пачки, пачек |
| `комплект` | комплекты, комплектов, компл |
| `ведро` | вёдра, вёдер |
| `банка` | банки, банок |
| `тюбик` | тюбики, тюбиков |
| `бутылка` | бутылки, бутылок |
| `коробка` | коробки, коробок |
| `пакет` | пакеты, пакетов |

Незнакомая единица → пишется как есть, добавляется в SQLite `unknown_units` для пополнения словаря.

### 1.8 Лист «Товары» (справочник, создаётся ботом по первой канонизации)

| Колонка | Тип | Пример |
|---------|-----|--------|
| Канон | строка | ГКЛ 12,5 |
| Алиасы | строка через `;` | гипсокартон 12,5; ГКЛ 12 |
| Единица дефолтная | канон из §1.7 | лист |
| Категория товара | строка (свободная) | гипсокартон |
| Статус | `активный` / `архив` | активный |
| Дата создания | ДД.ММ.ГГГГ | 12.05.2026 |

### 1.9 Лист «Точки» (справочник)

| Колонка | Тип | Пример |
|---------|-----|--------|
| Канон | строка | магазин на Ленина |
| Алиасы | строка через `;` | Ленина; магазин |
| Тип | `магазин` / `склад` | магазин |
| Адрес | строка / пусто | ул. Ленина 42 |
| Статус | `активная` / `закрыта` | активная |
| Дата создания | ДД.ММ.ГГГГ | 01.04.2026 |

### 1.10 Лист «Категории» (опциональный, для управления списком категорий расходов)

| Колонка | Тип | Пример |
|---------|-----|--------|
| Категория | строка | аренда помещения |
| Активна | `да` / `нет` | да |
| Триггеры | через `;` (для LLM-промпта) | аренда; помещение; офис |

Если листа нет — используется дефолт из §1.4. При первом запуске бот может создать лист с дефолтным содержимым по `/init categories`.

### 1.11 Лист «Лог обработки» (опциональный, по флагу `ENABLE_PROCESSING_LOG_SHEET`)

| Колонка | Содержимое |
|---------|------------|
| Дата | дата получения |
| Время | время |
| MAX message_id | для антидубля |
| Тип входящего | `voice` / `text` |
| Распознанный текст | Whisper output |
| Tool | какой tool_use вызвался |
| JSON input | сериализованный input tool |
| Статус | `written` / `awaiting_confirmation` / `cancelled` / `duplicate` / `error` / `pending_write` |
| tx_id | для транзакций |
| Ссылки на строки | `Движение денег!A42, Движение товаров!A15` |
| Ошибка | текст или пусто |

### 1.12 Инициализация и проверка структуры

При первом `/link` бот:
1. Проверяет права service account на запись.
2. Создаёт обязательные листы (§1.1, §1.2, §1.6) с заголовками.
3. Если листы есть и колонки совпадают — продолжаем.
4. Если есть, но колонки не совпадают — отказ.
5. Справочники (§1.8, §1.9, §1.10) — лениво, при первой записи.
6. В ячейке `A1` каждого обязательного листа — служебный комментарий `«max-money-bot v2.0»`.

При каждом запуске бота и перед записью — повторная проверка заголовков. Расхождение → стоп записи + сообщение владельцу + `pending_writes`.

### 1.13 Иерархия привязки

1. SQLite `chat_sheets[chat_id]` — приоритет.
2. Иначе `DEFAULT_SHEET_ID` из env.
3. Иначе — инструкция сделать `/link <id>`.

---

## 2. Доменные типы (Python)

Все типы в `src/domain/`. Pydantic v2.

### 2.1 Базовые типы

```python
from datetime import datetime
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, Field


class PaymentMethod(StrEnum):
    CASH = "наличные"
    CARD = "карта"
    TRANSFER = "счёт"
    UNKNOWN = "не указано"


class ExpenseCategory(StrEnum):
    GOODS_PURCHASE = "закупка товара"
    RENT = "аренда помещения"
    SALARY = "зарплата"
    UTILITIES = "коммунальные / связь"
    MARKETING = "реклама / маркетинг"
    TRANSPORT = "транспорт / доставка"
    TAXES_BANK = "налоги / банк / эквайринг"
    EQUIPMENT_REPAIR = "оборудование / ремонт"
    OTHER = "прочее"


class Confidence(BaseModel):
    text: float = Field(ge=0.0, le=1.0)
    amount: float = Field(ge=0.0, le=1.0, default=1.0)
    quantity: float = Field(ge=0.0, le=1.0, default=1.0)

    @property
    def critical(self) -> float:
        return min(self.text, self.amount, self.quantity)


class GoodsLine(BaseModel):
    """Одна позиция товара."""
    product: str                    # канон или сырое имя (до канонизации)
    qty: float = Field(gt=0)
    unit: str                       # канон или сырая единица
    price_per_unit_kopecks: int | None = None  # для поступления — расчёт
    comment: str | None = None
```

### 2.2 Операции с одновременным движением денег и товаров

```python
class Sale(BaseModel):
    """Продажа товара покупателю.
    Пишет: Движение денег (продажа), Движение товаров (продажа), Остатки −Q."""
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    counterparty: str | None = None         # покупатель, обычно пусто для розницы
    location: str | None = None             # точка/склад продажи
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


class Purchase(BaseModel):
    """Закупка товара у поставщика.
    Пишет: Движение денег (закупка), Движение товаров (поступление), Остатки +Q,
    обновляет СВ-цену."""
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    supplier: str                            # обязательно для закупки
    location: str | None = None              # куда поступило (склад по умолчанию)
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


class ReturnFromCustomer(BaseModel):
    """Возврат от покупателя.
    Пишет: Движение денег (возврат покупателю −), Движение товаров (возврат +Q), Остатки +Q."""
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    customer: str | None = None
    location: str | None = None              # куда вернули
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str


class ReturnToSupplier(BaseModel):
    """Возврат поставщику.
    Пишет: Движение денег (возврат поставщика +), Движение товаров (возврат поставщику −Q), Остатки −Q."""
    occurred_at: datetime
    amount_kopecks: int = Field(gt=0)
    lines: list[GoodsLine] = Field(min_length=1)
    supplier: str                            # обязательно
    location: str | None = None              # откуда вернули
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    confidence: Confidence
    raw_text: str
```

### 2.3 Операции только с деньгами или только с товарами

```python
class CashflowType(StrEnum):
    EXPENSE = "расход"
    OTHER_INCOME = "прочий приход"
    DEPOSIT = "внесение"
    WITHDRAWAL = "изъятие"


class Cashflow(BaseModel):
    """Денежная операция без движения товара.
    Пишет: только Движение денег."""
    occurred_at: datetime
    op_type: CashflowType
    amount_kopecks: int = Field(gt=0)
    category: ExpenseCategory                 # для расхода — реальная; для прочих — по типу
    counterparty: str | None = None
    location: str | None = None
    payment: PaymentMethod = PaymentMethod.UNKNOWN
    description: str
    confidence: Confidence
    raw_text: str


class Writeoff(BaseModel):
    """Списание товара (брак, недостача).
    Пишет: только Движение товаров (списание), Остатки −Q."""
    occurred_at: datetime
    lines: list[GoodsLine] = Field(min_length=1)
    location: str                             # где списываем
    reason: str                               # бой, недостача, истёк срок и т.п.
    confidence: Confidence
    raw_text: str


class Movement(BaseModel):
    """Перемещение между точками/складами.
    Пишет: две строки в Движение товаров (−Q источник, +Q приёмник), Остатки оба."""
    occurred_at: datetime
    lines: list[GoodsLine] = Field(min_length=1)
    from_location: str
    to_location: str
    confidence: Confidence
    raw_text: str


class InventoryAdjustment(BaseModel):
    """Корректировка остатка по факту инвентаризации.
    Пишет: Движение товаров (инвентаризация, +Q или −Q), Остатки до фактического."""
    occurred_at: datetime
    product: str
    location: str
    actual_qty: float = Field(ge=0)           # фактическое количество
    unit: str
    confidence: Confidence
    raw_text: str
```

### 2.4 Multi-ops

```python
class SalesBatch(BaseModel):
    """Несколько продаж в одной фразе."""
    sales: list[Sale] = Field(min_length=2)
    raw_text: str
```

(Аналогичные batch-типы для покупок и расходов добавляются по мере необходимости.)

### 2.5 Запросы

```python
class StockQuery(BaseModel):
    """Запрос остатков."""
    product: str | None = None       # None = все товары
    location: str | None = None      # None = все точки


class ReportPeriodType(StrEnum):
    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    CUSTOM = "custom"


class TopMetric(StrEnum):
    REVENUE = "по выручке"          # дефолт для магазина
    PROFIT = "по прибыли"
    QUANTITY = "по количеству"


class ReportPeriodRequest(BaseModel):
    period_type: ReportPeriodType
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    quarter: int | None = Field(default=None, ge=1, le=4)
    relative: Literal["current", "previous", None] = None
    top_metric: TopMetric = TopMetric.REVENUE
    location_filter: str | None = None       # отчёт по конкретной точке
    period_is_clear: bool
```

### 2.6 Канонизация и правки

```python
class ProductCanonicalization(BaseModel):
    """Ответ LLM при обнаружении похожего канона товара."""
    decision: Literal["existing", "new"]
    canon: str | None = None                 # если existing
    new_canon: str | None = None             # если new
    default_unit: str | None = None          # для new — единица по умолчанию


class LocationCanonicalization(BaseModel):
    decision: Literal["existing", "new"]
    canon: str | None = None
    new_canon: str | None = None
    location_type: Literal["магазин", "склад", None] = None


class EditLastRequest(BaseModel):
    field: Literal["amount", "qty", "counterparty", "category", "location", "payment", "description"]
    new_value: str | int | float
```

### 2.7 Уточнение

```python
class ClarificationNeeded(BaseModel):
    raw_text: str
    reason: str
    question: str
    intent_hint: Literal["sale", "purchase", "return_customer", "return_supplier",
                          "expense", "writeoff", "movement", "report", None] = None
```

### 2.8 Дискриминированный union — что возвращает парсер

```python
ParsedCommand = (
    Sale | Purchase | ReturnFromCustomer | ReturnToSupplier
    | Cashflow | Writeoff | Movement | InventoryAdjustment
    | SalesBatch
    | StockQuery
    | ReportPeriodRequest
    | ProductCanonicalization | LocationCanonicalization
    | EditLastRequest
    | ClarificationNeeded
)
```

### 2.9 Отчёты

```python
class TopItem(BaseModel):
    name: str                                # товар или точка
    metric_value_kopecks: int | None = None  # для метрик в рублях
    metric_qty: float | None = None          # для метрики "по количеству"
    revenue_kopecks: int = 0
    cost_kopecks: int = 0                    # для прибыли


class FinancialReport(BaseModel):
    period_label: str
    sales_kopecks: int                       # выручка
    sales_count: int
    purchases_kopecks: int                   # закупки товара
    expenses_kopecks: int                    # прочие расходы
    expenses_breakdown: dict[str, int] = Field(default_factory=dict)  # по категориям
    returns_from_customers_kopecks: int = 0
    returns_to_suppliers_kopecks: int = 0
    deposits_kopecks: int = 0
    withdrawals_kopecks: int = 0
    top_products: list[TopItem] = Field(default_factory=list, max_length=3)
    top_locations: list[TopItem] = Field(default_factory=list, max_length=5)
    top_metric: TopMetric = TopMetric.REVENUE

    @property
    def cash_balance_kopecks(self) -> int:
        return (
            self.sales_kopecks + self.returns_to_suppliers_kopecks + self.deposits_kopecks
            - self.purchases_kopecks - self.expenses_kopecks
            - self.returns_from_customers_kopecks - self.withdrawals_kopecks
        )


class StockSnapshot(BaseModel):
    product: str
    unit: str
    location: str
    qty: float
    avg_purchase_price_kopecks: int | None = None
    updated_at: datetime


class StockReport(BaseModel):
    items: list[StockSnapshot]
    product_filter: str | None = None
    location_filter: str | None = None
```

---

## 3. SQLite — технический слой

Файл `data/bot.sqlite3`. **Не дублирует учётные данные.** Только тех. состояние.

### 3.1 Таблицы

```sql
-- маппинг чата → таблица
CREATE TABLE chat_sheets (
    chat_id TEXT PRIMARY KEY,
    sheet_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,        -- 'v2.0' и т.п. — для миграций
    linked_at TEXT NOT NULL,
    linked_by_user_id TEXT NOT NULL
);

-- идемпотентность по message_id
CREATE TABLE idempotency_log (
    message_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    result TEXT NOT NULL                 -- 'written'|'cancelled'|'duplicate'|'pending'
);

-- семантическая дедупликация (5 мин)
CREATE TABLE dedup_window (
    semantic_hash TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    operation_summary TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (semantic_hash, chat_id)
);
CREATE INDEX idx_dedup_expires ON dedup_window(expires_at);

-- состояние диалогов
CREATE TABLE dialog_state (
    chat_id TEXT PRIMARY KEY,
    intent TEXT NOT NULL,                -- 'clarify_money'|'clarify_goods'|'period_report'|
                                          -- 'confirm_undo'|'canonicalize_product'|
                                          -- 'canonicalize_location'|'dedup_check'|
                                          -- 'inventory_step'|'edit_last'
    awaiting_field TEXT,
    partial_data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX idx_dialog_expires ON dialog_state(expires_at);

-- журнал успешных транзакций (для /undo и audit; НЕ дублирует учётные данные)
CREATE TABLE operations_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id TEXT NOT NULL,                 -- общий для связанных строк
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    op_kind TEXT NOT NULL,               -- 'sale'|'purchase'|'return_customer'|...
    sheet_rows_json TEXT NOT NULL,       -- [{"sheet": "Движение денег", "row": 42}, ...]
    stock_changes_json TEXT NOT NULL,    -- [{"product": "ГКЛ", "location": "склад", "delta": -10}]
    summary TEXT NOT NULL,
    created_at TEXT NOT NULL,
    undone_at TEXT
);
CREATE INDEX idx_oplog_chat_created ON operations_log(chat_id, created_at DESC);
CREATE INDEX idx_oplog_tx ON operations_log(tx_id);

-- очередь записей при недоступности Sheets
CREATE TABLE pending_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tx_id TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,          -- готовая транзакция (все нужные записи)
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);

-- кэш канонов товаров
CREATE TABLE products_cache (
    canon TEXT PRIMARY KEY,
    aliases_json TEXT NOT NULL,
    default_unit TEXT,
    category TEXT,
    status TEXT NOT NULL,                -- 'активный'|'архив'
    last_synced_at TEXT NOT NULL
);

-- кэш канонов точек
CREATE TABLE locations_cache (
    canon TEXT PRIMARY KEY,
    aliases_json TEXT NOT NULL,
    type TEXT,                           -- 'магазин'|'склад'
    status TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);

-- неизвестные единицы для расширения словаря
CREATE TABLE unknown_units (
    unit TEXT PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1
);

-- журнал сбоев ежедневного отчёта
CREATE TABLE missed_reports (
    report_date TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT
);
```

### 3.2 Очистка / TTL
- `dedup_window`, `dialog_state` — GC по `expires_at` каждые 60 сек.
- `idempotency_log` — 30 дней.
- `operations_log` — 90 дней (после `/undo` не работает для старых).
- `pending_writes` — после успешной записи удаляются; после 100 неуспешных попыток — алерт.

### 3.3 Двухслойная идемпотентность
1. **По `message_id`:** webhook retry / двойной long-polling poll.
2. **Семантическая (`semantic_hash`):** повторная диктовка пользователем в окне 5 мин.

---

## 4. Пример заполненной таблицы

### Лист «Движение денег»

| Дата | Время | Тип | Сумма | Категория | Контрагент | Точка | Способ | Описание | tx_id |
|------|-------|-----|-------|-----------|------------|-------|--------|----------|-------|
| 31.05.2026 | 09:14 | прочий приход | 50000 | внесение | владелец | магазин на Ленина | наличные | внёс в кассу | |
| 31.05.2026 | 10:30 | закупка | 25000 | закупка товара | Петрович | склад | счёт | штукатурка 100 мш | pur_a7f3 |
| 31.05.2026 | 11:45 | продажа | 5000 | продажа | | магазин на Ленина | наличные | ГКЛ 10 л | sal_b2e1 |
| 31.05.2026 | 12:30 | продажа | 18000 | продажа | бригада Иванова | магазин на Ленина | счёт | цемент 30 мш | sal_c8d4 |
| 31.05.2026 | 13:15 | возврат покупателю | 1000 | возврат покупателю | | магазин на Ленина | наличные | ГКЛ 2 л | rfc_e3a2 |
| 31.05.2026 | 16:00 | расход | 80000 | аренда помещения | Сбер недвижимость | | счёт | аренда июнь | |

### Лист «Движение товаров»

| Дата | Время | Тип | Точка | Источник | Контрагент | Товар | Кол-во | Ед. | Цена | Комментарий | tx_id |
|------|-------|-----|-------|----------|------------|-------|--------|-----|------|-------------|-------|
| 31.05.2026 | 10:30 | поступление | склад | | Петрович | штукатурка | 100 | мешок | 250 | | pur_a7f3 |
| 31.05.2026 | 11:45 | продажа | магазин на Ленина | | | ГКЛ 12,5 | 10 | лист | | | sal_b2e1 |
| 31.05.2026 | 12:30 | продажа | магазин на Ленина | | бригада Иванова | цемент М500 | 30 | мешок | | | sal_c8d4 |
| 31.05.2026 | 13:15 | возврат покупателя | магазин на Ленина | | | ГКЛ 12,5 | 2 | лист | | | rfc_e3a2 |
| 31.05.2026 | 14:00 | списание | склад | | | штукатурка | 3 | мешок | | бой | |
| 31.05.2026 | 15:30 | перемещение | магазин на Ленина | склад | | штукатурка | 20 | мешок | | | mov_f1b9 |
| 31.05.2026 | 15:30 | перемещение | склад | | | штукатурка | -20 | мешок | | (источник) | mov_f1b9 |

### Лист «Остатки»

| Товар | Единица | Точка | Кол-во | СВ-цена | Обновлено |
|-------|---------|-------|--------|---------|-----------|
| штукатурка | мешок | склад | 77 | 250 | 31.05.2026 15:30 |
| штукатурка | мешок | магазин на Ленина | 20 | 250 | 31.05.2026 15:30 |
| ГКЛ 12,5 | лист | магазин на Ленина | 32 | 480 | 31.05.2026 13:15 |
| цемент М500 | мешок | магазин на Ленина | 70 | 380 | 31.05.2026 12:30 |

### Лист «Товары»

| Канон | Алиасы | Единица | Категория | Статус | Создан |
|-------|--------|---------|-----------|--------|--------|
| ГКЛ 12,5 | гипсокартон 12,5; ГКЛ 12 | лист | гипсокартон | активный | 12.05.2026 |
| цемент М500 | цемент 500; портландцемент | мешок | цементы | активный | 15.05.2026 |
| штукатурка | гипсовая штукатурка | мешок | смеси | активный | 18.05.2026 |

### Лист «Точки»

| Канон | Алиасы | Тип | Адрес | Статус | Создан |
|-------|--------|-----|-------|--------|--------|
| магазин на Ленина | Ленина; магазин | магазин | ул. Ленина 42 | активная | 01.04.2026 |
| склад | база; основной склад | склад | ул. Зорге 18 | активная | 01.04.2026 |
