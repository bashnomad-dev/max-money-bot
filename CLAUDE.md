# max-money-bot

## Что это
Голосовой бот в мессенджере MAX для владельца розничного магазина стройматериалов с несколькими точками. Голосом надиктовываются операции (продажи, закупки, возвраты, списания, перемещения, расходы), бот распознаёт через Whisper, парсит через Claude tool_use, **одновременно** обновляет три листа Google-таблицы (Движение денег, Движение товаров, Остатки) транзакционно через общий `tx_id`. В 21:00 МСК — текстовый автоотчёт с разбивкой по типам и топ-3 товара / точкам. По голосу — сводный отчёт за период с метриками выручка / прибыль / количество. Запросы остатков голосом в любой момент: «сколько ГКЛ на складе?».

Один пользователь (владелец). Один магазин (single-tenant). Несколько точек / складов в рамках одного магазина.

## Документация
- `docs/SPEC.md` — **итоговое ТЗ v2.0**, source of truth.
- `docs/data-model.md` — структура Sheets, pydantic-типы, SQLite-схема.
- `docs/llm-parsing.md` — 14 tool_use инструментов, промпт, примеры.
- `docs/scenarios.md` — все G/C/E/F/T/V кейсы.
- `docs/archive/` — старые версии (v1.0 «прораб», исходный шаблонный бриф). Не использовать.

## Стек
- Runtime: Python 3.11+
- Bot framework: MAX Bot API (long-polling в MVP; готовой Python-обёртки может не быть — план B тонкий httpx-клиент)
- STT: OpenAI Whisper API (`whisper-1`, `language="ru"`)
- LLM: Anthropic Claude (`claude-haiku-4-5-20251001` основной, `claude-sonnet-4-6` fallback при `critical_confidence < 0.7`)
- Google Sheets: `gspread` + service account
- SQLite — технический слой (idempotency, dedup, dialog_state, operations_log для `/undo`, pending_writes, products_cache, locations_cache)
- Deploy: VPS + systemd

## Команды
```bash
# install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# dev (long-polling)
python -m src.main

# tests
pytest

# lint / typecheck
ruff check src tests
mypy src
```

## Env vars
Полный список — `.env.example`. Никогда не коммитить `.env`, `secrets/`.

Ключевые группы:
- **API:** `MAX_BOT_TOKEN`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_SERVICE_ACCOUNT_JSON`
- **Sheets:** `DEFAULT_SHEET_ID`, `ENABLE_PROCESSING_LOG_SHEET`, `SHEETS_SCHEMA_VERSION`
- **Доступ:** `ALLOWED_USER_IDS`, `SILENT_REJECT`, `OPS_PIN`, `PIN_MAX_ATTEMPTS`, `PIN_LOCKOUT_MINUTES`
- **Поведение:** `TZ` (Europe/Moscow), `DEFAULT_LOCATION`, `DAILY_REPORT_TIME` (21:00)
- **Гибридный UX:** `AUTO_WRITE_CONFIDENCE_THRESHOLD` (0.85), `CLARIFICATION_THRESHOLD` (0.5), `LARGE_AMOUNT_THRESHOLD_RUB` (100000)
- **Канонизация:** `CANON_SIMILARITY_THRESHOLD` (0.8)
- **Дедуп/диалоги:** `DEDUP_WINDOW_MINUTES` (5), `DIALOG_STATE_TTL_MINUTES` (5)
- **Голос:** `VOICE_MAX_DURATION_SEC` (60), `ENABLE_NOISE_REDUCTION`
- **Бюджет:** `MONTHLY_API_BUDGET_USD` (0 = без лимита)

## Структура
```
src/
  main.py            — точка входа, long-polling
  bot/               — MAX-клиент, роутер апдейтов, обработчики команд
  stt/               — Whisper-обёртка, опц. noisereduce
  llm/               — Claude tool_use парсер (14 инструментов) → ParsedCommand
  sheets/            — gspread, маппинг ParsedCommand → строки в 3 листах, инициализация структуры
  stock/             — пересчёт Остатков, СВ-цена, защита от ручных правок, /repair stock
  domain/            — pydantic: Sale, Purchase, Return*, Cashflow, Writeoff, Movement, InventoryAdjustment, Confidence, GoodsLine, FinancialReport, StockSnapshot, enums
  reports/           — сводные отчёты из Sheets с топами по 3 метрикам + разбивка по точкам
  scheduler/         — дневной автоотчёт по cron + ретраи
  storage/           — SQLite: idempotency, dedup, dialog_state, operations_log, pending_writes, products_cache, locations_cache
  dialog/            — stateful-диалоги: уточнения, канонизация (товаров/точек), undo, dedup_check, inventory
  config/            — env, whitelist, пороги
tests/               — pytest, фикстуры из SPEC §17 / scenarios.md
docs/                — проектная документация
docs/archive/        — старые версии доки
```

## Конвенции репо
- **Async-only:** все I/O через `asyncio` / `httpx.AsyncClient`.
- **LLM-парсер** возвращает строго типизированный `ParsedCommand` через Claude tool_use — никаких regex.
- **Гибридный UX** (SPEC §9.2) применяется в порядке: канонизация → большая сумма → дедуп → confidence.
- **Sheets — единственный источник правды для учёта.** SQLite не дублирует операционные данные.
- **Транзакционность:** связанные записи (Деньги + Товары + Остатки) пишутся атомарно через общий `tx_id`. Двухфазный паттерн с компенсацией при частичном сбое (SPEC §14.4).
- **Лист «Остатки» расчётный** — обновляется только ботом, защита от ручных правок через хэш.
- **Канонизация:** товаров и точек — обязательно; контрагентов — v2.
- **Даты в Sheets** — `ДД.ММ.ГГГГ`, время — `ЧЧ:ММ`, отсутствующие поля — `не указано`.
- **Деньги в домене** — копейки `int`. В Sheets — целые рубли. Количество товара — `float`.
- **Append-only:** клиент может добавлять свои колонки справа от ботовских, бот их не трогает. Удаление/переименование ботовских колонок не разрешено.

## Доменная специфика
Полная схема — `docs/data-model.md`.

**3 обязательных листа:**
- «Движение денег» (10 кол.): 8 типов операций (продажа, закупка, расход, прочий приход, возврат покупателю, возврат поставщика, внесение, изъятие).
- «Движение товаров» (12 кол. с tx_id): 7 типов (поступление, продажа, списание, возврат покупателя, возврат поставщику, перемещение, инвентаризация).
- «Остатки» (6 кол.): автообновляется, владелец не правит руками.

**3 справочных:** Товары (канон), Точки (канон), Категории (редактируемые).

**Tool_use (14):** record_sale / record_purchase / record_return_from_customer / record_return_to_supplier / record_cashflow / record_writeoff / record_movement / record_inventory_adjustment / query_stock / resolve_report_period / canonicalize_product / canonicalize_location / apply_edit / request_clarification.

**Команды MVP:** `/start`, `/help`, `/link`, `/today`, `/last [N]`, `/undo`, `/edit last`, `/cancel`, `/report`, `/stock [товар] [точка]`, `/locations`, `/products [фильтр]`, `/inventory`, `/version`.

**Отчёты:**
- `/today` — промежуточный итог дня.
- Ежедневный автоотчёт 21:00 (с разбивкой продажи/закупки/расходы + топ-3 товара + точки). Ретрай 5 раз при сбое.
- Сводный за период по голосу с метрикой топа: выручка / прибыль / количество. Опц. фильтр по точке.
- `/stock` — остатки голосом или командой.

## Деплой
- VPS 1 vCPU / 1 GB RAM (Selectel/Timeweb/Aeza).
- systemd, автоперезапуск.
- Секреты: `.env` (600), `secrets/service-account.json` (600).
- Бэкап Sheets → `.xlsx` еженедельно (cron).
- Логи: journald.

## Известные подводные камни
- **MAX Bot API молодой.** Разведка `dev.max.ru` до начала кодинга. План B: httpx-клиент. Long-polling на MVP.
- **Whisper и числа.** Митигация: карточка для крупных (> 100k), разделённый `amount_confidence` и `quantity_confidence`, опц. noisereduce.
- **Транзакционность Sheets API.** Sheets не транзакционна — двухфазная запись с компенсацией (SPEC §14.4).
- **Канонизация товаров.** Каждый новый товар требует подтверждения — иначе остатки расползутся.
- **Защита Остатков.** Лист защищён от ручных правок через хэш. Детект → запрос `/repair stock`.
- **Категория «прочее».** Минимизировать — список из 9 расширяемый через лист «Категории».

## Ссылки
- Repo: TBD (создать в bashnomad-dev)
- MAX Bot API docs: https://dev.max.ru/ (проверить актуальность)
- gspread: https://docs.gspread.org/
- Anthropic Claude: https://docs.claude.com/
