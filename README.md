# max-money-bot

Голосовой бот в MAX для владельца розничного строительного магазина (Евгений, 2 точки: «Магазин Зинино» + «Магазин Кармалы», ~4900 SKU). Учёт продаж, закупок, возвратов, расходов, перемещений и инвентаризации в Google-таблице с автоматическим пересчётом остатков. Дневной автоотчёт в 21:00 МСК и сводные отчёты по голосу.

**Стек (российский):** Python 3.11 · `maxapi` · GigaChat function calling · GigaAM (локально) · Google Sheets · SQLite · APScheduler. Fallback на Claude/Whisper переключается одной переменной env.

**Документация:** см. [docs/](docs/) — `SPEC.md` (главное ТЗ v2.1), `data-model.md`, `llm-parsing.md`, `scenarios.md`, `intake/evgeny/` (материалы клиента).

---

## Быстрый старт

```bash
# 1. Окружение
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Внешние требования (для STT)
brew install ffmpeg   # или apt install ffmpeg

# 3. Конфиг
cp .env.example .env
# заполнить минимум: MAX_BOT_TOKEN, GIGACHAT_CREDENTIALS, GOOGLE_SERVICE_ACCOUNT_JSON,
# ALLOWED_USER_IDS, DEFAULT_SHEET_ID

# 4. Импорт прайса Евгения для канонизации
cp docs/intake/evgeny/price-normalized.json data/products-import.json

# 5. Запуск
python -m src.main
```

При первом сообщении в MAX-чате — `/link <sheet_id>` затем `/setup`. После этого можно диктовать операции голосом.

## Тесты

```bash
pytest                      # 67 тестов
pytest -q --no-header       # компактный вывод
```

## CLI (без MAX)

Полезно для отладки парсера и канонизации без MAX-чата:

```bash
# С GigaChat (нужны credentials в .env):
python -m scripts.cli "Продал 30 мешков цемента за 18 тысяч наличными на Зинино"

# Демо без GigaChat (упрощённый мок-парсер):
python -m scripts.cli --mock-llm "Продал 30 мешков цемента за 18к наличными на Зинино"

# Интерактивный режим:
python -m scripts.cli --interactive
```

## Команды бота

| Команда | Действие |
|---------|----------|
| `/start` | Приветствие |
| `/help` | Полный список команд |
| `/link <sheet_id>` | Привязать Google-таблицу к чату |
| `/setup` | Создать листы + импорт прайса (один раз) |
| `/today` | Сводка за сегодня |
| `/last [N]` | Последние N операций |
| `/undo` | Откатить последнюю (с PIN) |
| `/cancel` | Сбросить активный диалог уточнения |
| `/report` | Сводный отчёт за период |
| `/stock [товар] [точка]` | Остатки |
| `/locations` | Список точек |
| `/products <фрагмент>` | Найти в каталоге |
| `/inventory` | Инвентаризация |
| `/version` | Версия |

## Деплой

См. [RUNBOOK.md](RUNBOOK.md).

## Структура проекта

```
src/
  bot/          MAX-клиент, контекст, хендлеры, роутер, pipeline, access
  llm/          GigaChat + Claude (fallback), 8 tools, common мап в domain
  stt/          GigaAM (основное) + Whisper (fallback)
  sheets/       схема, setup с импортом прайса, writer с компенсацией
  stock/        пересчёт остатков, СВ-цена, /repair
  reports/      daily, period, stock
  dialog/       semantic_hash, decision engine
  canonicalize/ единицы (60+ алиасов), точки, товары (rapidfuzz)
  storage/      SQLite-слой (12 таблиц, 11 репозиториев)
  scheduler/    APScheduler для дневного отчёта и фоновых тасков
  domain/       pydantic-модели всех типов операций
  config/       env, whitelist, пороги

docs/           ТЗ, модель данных, LLM-промпт, сценарии, intake клиента
scripts/        CLI runner, парсер прайса
tests/          67 тестов (unit + integration с мок-gspread)
data/           SQLite + импорт-файлы (в .gitignore)
secrets/        service account JSON (в .gitignore)
```
