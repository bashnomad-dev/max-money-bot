# Модель данных (v2.1)

> Конкретные значения соответствуют клиенту Евгению: 2 точки, 4893 SKU, 9 категорий расходов, 10 единиц измерения. Изменения схемы Sheets — только через обновление кода (см. [SPEC §6](./SPEC.md)).

## 1. Google Sheets

Одна Google-таблица. **3 обязательных листа** + **3 справочных** + **1 опциональный**. Колонки именуются строго — бот ищет по заголовку, не по индексу. Клиент может добавлять любые свои колонки СПРАВА от ботовских.

### 1.1 Лист «Движение денег» (обязательный, 11 колонок)

| # | Колонка | Тип | Источник |
|---|---------|-----|----------|
| 1 | Дата | ДД.ММ.ГГГГ | TZ владельца |
| 2 | Время | ЧЧ:ММ | TZ владельца |
| 3 | Тип операции | enum (§1.4) | LLM |
| 4 | Сумма (₽) | целое число | LLM |
| 5 | Описание | строка | LLM (дословный фрагмент) |
| 6 | Категория | enum (§1.5) или пусто | LLM (только для типа «расход»; «закупка» = автоматом «закупка товара») |
| 7 | Контрагент | строка / «не указано» | LLM |
| 8 | Точка | «Магазин Зинино» / «Магазин Кармалы» | LLM + дефолт |
| 9 | Способ оплаты | enum: наличные/карта/счёт/«не указано» | LLM |
| 10 | tx_id | UUID4 первые 8 hex | бот |
| 11 | Автор | MAX user_id того, кто внёс запись | бот |

### 1.2 Лист «Движение товаров» (обязательный, 13 колонок)

| # | Колонка | Тип | Источник |
|---|---------|-----|----------|
| 1 | Дата | ДД.ММ.ГГГГ | TZ |
| 2 | Время | ЧЧ:ММ | TZ |
| 3 | Тип операции | enum (§1.6) | LLM |
| 4 | Точка | канон из «Точек» | LLM + канонизация |
| 5 | Точка-источник | канон или пусто (для перемещений) | LLM |
| 6 | Товар | канон из «Товары» | LLM + канонизация |
| 7 | Количество | число (может быть дробным) | LLM |
| 8 | Единица | канон из словаря §1.7 | LLM + канонизация |
| 9 | Цена за ед. (₽) | дробное число | бот (для продажи — СВ-цена; для закупки — фактическая) |
| 10 | Контрагент | строка / «не указано» | LLM |
| 11 | Комментарий | строка | LLM |
| 12 | tx_id | UUID4 первые 8 hex | бот (связь с «Движение денег») |
| 13 | Автор | MAX user_id того, кто внёс запись | бот |

### 1.3 Лист «Остатки» (обязательный, 6 колонок) — расчётный

| # | Колонка | Тип | Источник |
|---|---------|-----|----------|
| 1 | Товар | канон из «Товары» | бот |
| 2 | Точка | канон из «Точки» | бот |
| 3 | Количество | число | бот (пересчёт после каждой операции) |
| 4 | Единица | канон | бот |
| 5 | СВ-цена закупки (₽) | дробное число | бот (взвешенное среднее по поступлениям) |
| 6 | Обновлено | ДД.ММ.ГГГГ ЧЧ:ММ | бот |

**Особенности:**
- Лист помечен в A1: `СИСТЕМНЫЙ ЛИСТ — не редактировать вручную`.
- При детекте ручных правок (хэш строк отличается от ожидаемого) — предупреждение в чат, рекомендация `/repair stock`.
- `/repair stock` пересчитывает все строки с нуля из «Движения товаров».

### 1.4 Типы операций денег (8)
1. **продажа** — приход от покупателя за товар
2. **закупка** — расход поставщику за товар
3. **расход** — без товара (аренда, зарплата, налоги, ремонт оборудования...)
4. **прочий приход** — без товара (бонус от поставщика, страховка...)
5. **возврат покупателю** — расход (мы вернули покупателю)
6. **возврат поставщика** — приход (поставщик вернул нам)
7. **внесение** — пополнение кассы из своих средств
8. **изъятие** — забор владельцем на личное

### 1.5 Категории расходов (9, для типа «расход»)
1. закупка товара (для типа «закупка» автоматом)
2. аренда помещения
3. зарплата
4. коммунальные / связь
5. реклама / маркетинг
6. транспорт / доставка
7. налоги / банк / эквайринг
8. оборудование / ремонт
9. прочее

Редактируются владельцем в листе «Категории» (§1.10). Бот читает актуальный список при старте.

### 1.6 Типы операций товаров (7)
1. **поступление** — от поставщика на точку (для record_purchase)
2. **продажа** — со склада/точки покупателю (для record_sale)
3. **списание** — брак, недостача (record_writeoff_or_movement)
4. **возврат покупателя** — товар вернулся на точку (record_return: from_customer)
5. **возврат поставщику** — товар уехал поставщику (record_return: to_supplier)
6. **перемещение** — две связанные строки (-source, +destination)
7. **инвентаризация** — корректировка по факту (record_inventory)

### 1.7 Единицы измерения (10 канонических, из прайса Евгения)

| Канон | Принимаемые алиасы | Кол-во SKU в прайсе |
|-------|---------------------|---------------------|
| `шт.` | штука, штуки, штук | 7160 |
| `м2` | квадратный метр, квадраты, кв.м, квадратов | 732 |
| `м3` | кубический метр, куб, кубы, кубометр, кубов | 550 |
| `м.п.` | погонный метр, погонных метров, пог.м, п.м | 421 |
| `рул` | рулон, рулоны, рулонов | 280 |
| `уп.` | упаковка, упаковки, упаковок | 255 |
| `кг` | килограмм, кило, килограммов | 246 |
| `меш.` | мешок, мешки, мешков | 82 |
| `л.` | литр, литры, литров | 46 |
| `м` | метр, метры, метров | 14 |

Канонизация — `src/canonicalize/units.py`. Незнакомая единица → пишется как есть + логируется в SQLite `unknown_units`.

### 1.8 Лист «Товары» (справочный)
Импортируется один раз из `data/products-import.json` (см. `scripts/parse_evgeny_price.py`, выход — 4893 уникальных SKU).

| Колонка | Содержимое |
|---------|------------|
| Канон | Каноническое имя из прайса (например, «25кг Цемент Стерлитамак Хайдел») |
| Алиасы | Список через `;`, накапливается при канонизации |
| Единица по умолчанию | Из прайса |
| Цена розничная (₽) | Из прайса |
| Активен | да/нет |

### 1.9 Лист «Точки» (справочный)
2 строки, импортируются при `/setup`:

| Канон | Алиасы | Адрес |
|-------|--------|-------|
| Магазин Зинино | зинино; на Зинино; в Зинино; магазин Зинино | (опц.) |
| Магазин Кармалы | кармалы; на Кармалы; в Кармалы; магазин Кармалы | (опц.) |

### 1.10 Лист «Категории» (справочный)
9 строк, заполняется дефолтом (§1.5). Владелец может редактировать руками.

| Категория | Активна | Триггеры |
|-----------|---------|----------|
| аренда помещения | да | аренда; за помещение |
| зарплата | да | зарплата; зп; оплата работнику |
| коммунальные / связь | да | свет; вода; интернет; связь |
| ... | | |

### 1.11 Опциональный «Лог обработки»
Создаётся если `ENABLE_PROCESSING_LOG_SHEET=true`. Колонки: Дата, Время, message_id, user_id, Тип входящего, Распознанный текст, JSON после LLM, Статус, Ошибка, Ссылка на строку.

### 1.12 Setup при первом `/link`
1. Проверка прав service account.
2. Создание 3 обязательных листов с заголовками.
3. Создание 3 справочных листов.
4. Импорт прайса из `data/products-import.json` → лист «Товары» (~4900 строк).
5. Импорт «Точек» из ENV/дефолта.
6. Импорт «Категорий» из дефолта.
7. «Остатки» — пустой, заполнится по мере операций.

---

## 2. Доменные типы (Python, pydantic v2)

### 2.1 Базовые
```python
class Confidence(BaseModel):
    text: float = Field(ge=0, le=1)
    amount: float = Field(ge=0, le=1)
    quantity: float = Field(ge=0, le=1)

    @property
    def critical(self) -> float:
        return min(self.text, self.amount, self.quantity)

class Location(StrEnum):
    ZININO = "Магазин Зинино"
    KARMALY = "Магазин Кармалы"

class PaymentMethod(StrEnum):
    CASH = "наличные"
    CARD = "карта"
    TRANSFER = "счёт"
    UNKNOWN = "не указано"

class GoodsLine(BaseModel):
    name: str                    # как сказал пользователь, до канонизации
    qty: float = Field(gt=0)
    unit: str                    # канонизированная или как услышал
    price_per_unit_rub: float | None = None
    comment: str | None = None
```

### 2.2 Операции — типы из tool_use
```python
class Sale(BaseModel):
    tx_id: str
    occurred_at: datetime
    amount_kopecks: int
    lines: list[GoodsLine]
    location: Location
    customer: str | None
    payment: PaymentMethod
    comment: str | None
    confidence: Confidence
    raw_text: str

class Purchase(BaseModel):
    tx_id: str
    occurred_at: datetime
    amount_kopecks: int
    supplier: str
    lines: list[GoodsLine]
    destination: Location
    payment: PaymentMethod
    comment: str | None
    confidence: Confidence
    raw_text: str

class ReturnDirection(StrEnum):
    FROM_CUSTOMER = "from_customer"
    TO_SUPPLIER = "to_supplier"

class Return(BaseModel):
    tx_id: str
    direction: ReturnDirection
    occurred_at: datetime
    amount_kopecks: int
    counterparty: str
    lines: list[GoodsLine]
    location: Location
    payment: PaymentMethod
    comment: str | None
    confidence: Confidence
    raw_text: str

class CashflowType(StrEnum):
    EXPENSE = "расход"
    OTHER_INCOME = "прочий приход"
    DEPOSIT = "внесение"
    WITHDRAWAL = "изъятие"

class ExpenseCategory(StrEnum):
    GOODS_PURCHASE = "закупка товара"
    RENT = "аренда помещения"
    SALARY = "зарплата"
    UTILITIES = "коммунальные / связь"
    MARKETING = "реклама / маркетинг"
    TRANSPORT = "транспорт / доставка"
    TAXES_BANK = "налоги / банк / эквайринг"
    EQUIPMENT = "оборудование / ремонт"
    OTHER = "прочее"

class Cashflow(BaseModel):
    tx_id: str
    occurred_at: datetime
    op_type: CashflowType
    amount_kopecks: int
    description: str
    category: ExpenseCategory | None
    counterparty: str | None
    location: Location | None
    payment: PaymentMethod
    confidence: Confidence
    raw_text: str

class WriteoffOrMovementType(StrEnum):
    WRITEOFF = "списание"
    MOVEMENT = "перемещение"

class WriteoffOrMovement(BaseModel):
    tx_id: str
    occurred_at: datetime
    op_type: WriteoffOrMovementType
    location: Location | None              # для writeoff
    source: Location | None                # для movement
    destination: Location | None           # для movement
    lines: list[GoodsLine]
    comment: str | None
    confidence: Confidence
    raw_text: str

class InventoryFact(BaseModel):
    name: str
    qty: float = Field(ge=0)              # 0 допустимо (товар закончился)
    unit: str

class Inventory(BaseModel):
    tx_id: str
    occurred_at: datetime
    location: Location
    facts: list[InventoryFact]
    confidence: Confidence
    raw_text: str
```

### 2.3 Запросы и уточнения
```python
class StockQuery(BaseModel):
    product_query: str | None
    location: Location | None

class ReportPeriodType(StrEnum):
    DAY = "day"; MONTH = "month"; QUARTER = "quarter"; YEAR = "year"; CUSTOM = "custom"

class TopMetric(StrEnum):
    REVENUE = "выручка"
    PROFIT = "прибыль"
    QUANTITY = "количество"

class PeriodReportRequest(BaseModel):
    period_type: ReportPeriodType
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    quarter: int | None = Field(default=None, ge=1, le=4)
    relative: Literal["current", "previous", None] = None
    location: Location | None = None
    top_metric: TopMetric = TopMetric.REVENUE
    period_is_clear: bool

class ClarificationNeeded(BaseModel):
    raw_text: str
    reason: str
    question: str
    intent_hint: Literal["sale", "purchase", "return", "cashflow",
                         "writeoff", "inventory", "report", None] = None

ParsedCommand = (
    Sale | Purchase | Return | Cashflow | WriteoffOrMovement
    | Inventory | StockQuery | PeriodReportRequest | ClarificationNeeded
)
```

### 2.4 Остатки и отчёты
```python
class StockItem(BaseModel):
    product: str
    location: Location
    qty: float
    unit: str
    avg_cost_kopecks: int
    updated_at: datetime

class TopItem(BaseModel):
    label: str
    revenue_kopecks: int
    profit_kopecks: int
    quantity: float

class FinancialReport(BaseModel):
    period_label: str
    income_kopecks: int
    expense_kopecks: int
    income_count: int
    expense_count: int
    by_location: dict[Location, int]              # net (приход − расход) на точку
    top_products: list[TopItem]
    top_locations: list[TopItem]

    @property
    def balance_kopecks(self) -> int:
        return self.income_kopecks - self.expense_kopecks
```

---

## 3. SQLite — технический слой

Файл `data/bot.sqlite3`. Не дублирует учётные данные.

```sql
-- маппинг чата на таблицу
CREATE TABLE chat_sheets (
    chat_id TEXT PRIMARY KEY,
    sheet_id TEXT NOT NULL,
    linked_at TEXT NOT NULL,
    linked_by_user_id TEXT NOT NULL
);

-- идемпотентность по message_id
CREATE TABLE idempotency_log (
    message_id TEXT PRIMARY KEY,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    result TEXT NOT NULL                     -- 'written' | 'cancelled' | 'duplicate' | 'pending'
);

-- семантическая дедупликация
CREATE TABLE dedup_window (
    semantic_hash TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    operation_summary TEXT NOT NULL,
    sheet_row_refs TEXT NOT NULL,            -- JSON: список ссылок (несколько листов)
    expires_at TEXT NOT NULL,
    PRIMARY KEY (semantic_hash, chat_id)
);
CREATE INDEX idx_dedup_expires ON dedup_window(expires_at);

-- состояние диалогов уточнения
CREATE TABLE dialog_state (
    chat_id TEXT PRIMARY KEY,
    intent TEXT NOT NULL,                    -- 'clarify_sale' | 'clarify_purchase' | 'clarify_return'
                                              -- | 'clarify_cashflow' | 'clarify_writeoff' | 'clarify_movement'
                                              -- | 'period_report' | 'confirm_undo' | 'canonicalize_product'
                                              -- | 'canonicalize_location' | 'dedup_check' | 'inventory'
    awaiting_field TEXT,
    partial_data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX idx_dialog_expires ON dialog_state(expires_at);

-- журнал записанных операций (для /undo и аудита; НЕ дублирует данные)
CREATE TABLE operations_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    tx_id TEXT NOT NULL,
    op_kind TEXT NOT NULL,                   -- 'sale' | 'purchase' | 'return' | 'cashflow' | ...
    sheet_refs TEXT NOT NULL,                -- JSON: [{sheet, row_index}, ...]
    summary TEXT NOT NULL,                   -- человекочитаемое
    created_at TEXT NOT NULL,
    undone_at TEXT
);
CREATE INDEX idx_oplog_chat_created ON operations_log(chat_id, created_at DESC);
CREATE INDEX idx_oplog_tx ON operations_log(tx_id);

-- очередь при недоступности Sheets
CREATE TABLE pending_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,              -- полная транзакция (несколько листов)
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL
);

-- кеши справочников (синк с Sheets раз в час)
CREATE TABLE products_cache (
    canon TEXT PRIMARY KEY,
    aliases_json TEXT NOT NULL,              -- ["алиас1", "алиас2"]
    default_unit TEXT,
    retail_price_kopecks INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE locations_cache (
    canon TEXT PRIMARY KEY,
    aliases_json TEXT NOT NULL,
    last_synced_at TEXT NOT NULL
);

CREATE TABLE categories_cache (
    name TEXT PRIMARY KEY,
    is_active INTEGER NOT NULL DEFAULT 1,
    triggers_json TEXT,
    last_synced_at TEXT NOT NULL
);

-- журнал неизвестных единиц
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

-- лог PIN-попыток (для лок-аута)
CREATE TABLE pin_attempts (
    user_id TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL
);
CREATE INDEX idx_pin_user ON pin_attempts(user_id, attempted_at DESC);
```

**GC и TTL:**
- `dedup_window`, `dialog_state` — фоновый sweep каждые 60 сек по `expires_at`.
- `idempotency_log` — 30 дней.
- `operations_log` — 90 дней. `/undo` работает только для записей моложе 90 дней.
- `pending_writes` — после успешной записи удаляются; > 100 неуспешных попыток → алерт.
- `pin_attempts` — 7 дней.

---

## 4. Пример заполненной таблицы

### «Движение денег»
| Дата | Время | Тип | Сумма | Описание | Категория | Контрагент | Точка | Способ | tx_id | Автор |
|------|-------|-----|-------|----------|-----------|------------|-------|--------|-------|
| 02.06.2026 | 09:14 | продажа | 18000 | цемент 30 мешков | | не указано | Магазин Зинино | наличные | a7f3b2e1 |
| 02.06.2026 | 11:40 | закупка | 25000 | штукатурка 100 меш. | закупка товара | Петрович | Магазин Кармалы | счёт | b8e4c3f2 |
| 02.06.2026 | 14:02 | расход | 80000 | аренда | аренда помещения | | Магазин Зинино | счёт | c9f5d4a3 |
| 02.06.2026 | 16:30 | возврат покупателю | 800 | ГКЛ 2 листа | | Иванов | Магазин Зинино | наличные | d0a6e5b4 |

### «Движение товаров»
| Дата | Время | Тип | Точка | Источник | Товар | Кол-во | Ед. | Цена/ед | Контрагент | Комментарий | tx_id | Автор |
|------|-------|-----|-------|----------|-------|--------|-----|---------|------------|-------------|-------|
| 02.06.2026 | 09:14 | продажа | Магазин Зинино | | 25кг Цемент Стерлитамак Хайдел | 30 | меш. | 313.45 | | | a7f3b2e1 |
| 02.06.2026 | 11:40 | поступление | Магазин Кармалы | | штукатурка | 100 | меш. | 250.00 | Петрович | | b8e4c3f2 |
| 02.06.2026 | 16:30 | возврат покупателя | Магазин Зинино | | гипсокартон 12,5 | 2 | лист | 400.00 | Иванов | | d0a6e5b4 |

### «Остатки»
| Товар | Точка | Кол-во | Ед. | СВ-цена | Обновлено |
|-------|-------|--------|-----|---------|-----------|
| 25кг Цемент Стерлитамак Хайдел | Магазин Зинино | 47 | меш. | 313.45 | 02.06.2026 09:14 |
| 25кг Цемент Стерлитамак Хайдел | Магазин Кармалы | 23 | меш. | 313.45 | 30.05.2026 18:20 |
| штукатурка | Магазин Кармалы | 120 | меш. | 248.50 | 02.06.2026 11:40 |
| гипсокартон 12,5 | Магазин Зинино | 27 | лист | 400.00 | 02.06.2026 16:30 |
