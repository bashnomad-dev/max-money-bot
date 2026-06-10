# RUNBOOK — деплой и эксплуатация

## Требования окружения

| Компонент | Версия | Зачем |
|-----------|--------|-------|
| Python | 3.11+ | Runtime |
| ffmpeg | любая | конвертация голоса для GigaAM |
| VPS | 1 vCPU / 1 GB RAM | хостинг бота 24/7 |
| MAX Bot API | — | регистрация бота (юрлицо РФ обязательно) |
| Google Sheets API | service account | запись в таблицу |
| OpenRouter | предоплата USD | парсинг команд (LLM) |
| GigaChat | опц. | резервный LLM-фолбэк (необязателен) |

## Получение ключей

### 1. MAX Bot
- Заходим на **https://business.max.ru/self**, регистрируем и **верифицируем организацию** (одно из ООО Евгения, верификация через Госуслуги). Маршрут через `@MasterBot` устарел и больше не работает.
- «Чат-боты» → «Создать» → заполняем карточку. @-адрес бота присваивается автоматически (вида `idИНН_bot`), выбрать своё имя нельзя.
- Отправляем на **модерацию MAX — до 2 рабочих дней**. Токен появляется только после одобрения, поэтому заводить бота надо заранее, не в день запуска.
- После одобрения: «Чат-боты» → «Интеграция» → «Получить токен» → это `MAX_BOT_TOKEN`. Одна организация — максимум 5 ботов.

### 2. OpenRouter (LLM-парсер, основной)
- Заходим на https://openrouter.ai, создаём API-ключ → это `OPENROUTER_API_KEY`.
- Модель — `anthropic/claude-haiku-4.5` (`OPENROUTER_MODEL`).
- Предоплата в USD. Доступность с RU-IP проверять на самом VPS (см. чек-лист первого запуска).

### 2a. GigaChat (опциональный фолбэк)
- Нужен, только если включаем резерв на падение OpenRouter. По умолчанию `LLM_BACKEND_FALLBACK` пуст — пункт можно пропустить.
- Кабинет https://developers.sber.ru/portal/products/gigachat → `Authorization key` (Base64) в `GIGACHAT_CREDENTIALS`, тариф PERS/B2B/CORP → `GIGACHAT_SCOPE`.

### 3. Google Sheets
- Создаём проект в Google Cloud Console.
- Включаем Google Sheets API + Google Drive API.
- Создаём service account, скачиваем JSON.
- Кладём JSON в `secrets/service-account.json` (не в git!).
- Создаём пустую Google-таблицу в нужном аккаунте Евгения.
- Расшариваем её на email service account из JSON (`client_email`).
- Копируем ID таблицы из URL (между `/d/` и `/edit`) — это `DEFAULT_SHEET_ID`.

### 4. ALLOWED_USER_IDS
- В MAX узнать `user_id` Евгения (бот покажет в логах при первом сообщении).
- Прописать в `.env` через запятую.

## Локальная разработка

```bash
git clone https://github.com/bashnomad-dev/max-money-bot.git
cd max-money-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# заполнить ключи

# Импорт прайса (один раз)
cp docs/intake/evgeny/price-normalized.json data/products-import.json

# Запуск
python -m src.main
```

## Деплой на VPS (Timeweb/Selectel/Aeza, Ubuntu 24.04 = Python 3.12)

### Быстрый путь — скрипт
От root на чистом сервере:
```bash
git clone https://github.com/bashnomad-dev/max-money-bot.git /tmp/mmb && bash /tmp/mmb/deploy/setup-vps.sh
```
Ставит пакеты (python3.12, ffmpeg, git), создаёт пользователя `maxbot`, клонирует
репо в `/home/maxbot/max-money-bot`, поднимает venv, импортирует прайс, ставит
systemd-unit и печатает оставшиеся ручные шаги (секреты).
Обновление кода потом: `bash /home/maxbot/max-money-bot/deploy/update.sh`.

Ниже — те же шаги вручную, если нужен контроль.

### 1. Подготовка VPS (Ubuntu 24.04)
```bash
apt update && apt install -y python3 python3-venv python3-pip ffmpeg git
useradd -m -s /bin/bash maxbot
su - maxbot
```

### 2. Установка проекта
```bash
git clone https://github.com/bashnomad-dev/max-money-bot.git
cd max-money-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Секреты
```bash
mkdir -p secrets data
# Скопировать .env и secrets/service-account.json (через scp или редактор)
chmod 600 .env secrets/service-account.json

cp docs/intake/evgeny/price-normalized.json data/products-import.json
```

### 4. systemd unit
Создать `/etc/systemd/system/maxbot.service` от root:

```ini
[Unit]
Description=max-money-bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=maxbot
WorkingDirectory=/home/maxbot/max-money-bot
ExecStart=/home/maxbot/max-money-bot/.venv/bin/python -m src.main
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now maxbot
systemctl status maxbot
journalctl -u maxbot -f       # логи в реальном времени
```

### 5. Бэкап Sheets
Скрипт `scripts/backup_sheets.py` выгружает все привязанные таблицы (DEFAULT_SHEET_ID + `chat_sheets`) в `backups/<sheet>-<YYYY-MM-DD-HHMM>.xlsx`, ротация — последние 12.

```bash
.venv/bin/pip install openpyxl   # одноразово, если не было
# проверка вручную
.venv/bin/python -m scripts.backup_sheets

# crontab -e (каждое воскресенье в 03:00)
0 3 * * 0 cd /home/maxbot/max-money-bot && .venv/bin/python -m scripts.backup_sheets >> /home/maxbot/backup.log 2>&1
```

## Обновление кода

```bash
su - maxbot
cd max-money-bot
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart maxbot
```

## Чек-лист первого запуска у клиента

1. [ ] `MAX_BOT_TOKEN` получен (после модерации) и в `.env`.
2. [ ] `OPENROUTER_API_KEY` получен и в `.env` (+ `OPENROUTER_MODEL`).
3. [ ] `secrets/service-account.json` скопирован, права 600.
4. [ ] Google-таблица создана, расшарена на service account.
5. [ ] `DEFAULT_SHEET_ID` в `.env`.
6. [ ] `ALLOWED_USER_IDS` в `.env` содержит MAX user_id Евгения.
7. [ ] `data/products-import.json` на месте.
8. [ ] `python -m scripts.cli "продал 30 мешков цемента за 18к на Зинино"` отрабатывает без ошибок.
9. [ ] `systemctl start maxbot` запускается, логи без ERROR.
10. [ ] Евгений пишет `/start` в MAX-чате с ботом — бот отвечает приветствием.
11. [ ] Евгений делает `/link <sheet_id>` затем `/setup` — импортируется 4883 SKU.
12. [ ] Тестовая операция: «продал 1 мешок цемента за 500 рублей наличными на Зинино» — попала в таблицу.

## Типовые проблемы

| Симптом | Причина | Решение |
|---------|---------|---------|
| `OPENROUTER_API_KEY не задан` при старте | Пустой `.env` | Заполнить ключ |
| `MAX_BOT_TOKEN не задан` | То же | То же |
| OpenRouter не отвечает с VPS | RU-IP/блокировка | проверить с сервера; включить `LLM_BACKEND_FALLBACK=gigachat` |
| Голосовые не распознаются | Нет ffmpeg | `apt install ffmpeg` |
| GigaAM долго грузится | Первый запуск качает модель ~1 GB | подождать; модель кешируется |
| Sheets «not found» | Не расшарили на service account | расшарить через UI Google Sheets |
| Бот молчит на сообщения | user_id не в whitelist | добавить в `ALLOWED_USER_IDS` |
| Карточка на каждую операцию | confidence порог слишком высокий | подкрутить `AUTO_WRITE_CONFIDENCE_THRESHOLD` |
| Карточка при каждой закупке | сумма > `LARGE_AMOUNT_THRESHOLD_RUB` | поднять порог (у Евгения отгрузки часто крупные) |

## Откат

```bash
git log --oneline             # найти прошлый рабочий коммит
git reset --hard <hash>
sudo systemctl restart maxbot
```

SQLite + Sheets не теряются — учётные данные в Sheets, технический state в `data/bot.sqlite3` обратно совместим.
