# max-money-bot

Голосовой бот в MAX для учёта продаж, закупок, остатков и выплат строительного магазина в Google Sheets.

Поток: голосовое сообщение → Whisper → Claude (парсинг в структуру) → подтверждение в чате → запись в нужный лист Google Sheets.

См. [CLAUDE.md](./CLAUDE.md) — стек, структура, конвенции.

## Быстрый старт
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить токены
python -m src.main
```
