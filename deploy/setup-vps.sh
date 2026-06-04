#!/usr/bin/env bash
# Первичная установка max-money-bot на чистый Ubuntu 24.04 (Timeweb VPS).
# Запуск от root:  bash setup-vps.sh
set -euo pipefail

BOT_USER=maxbot
APP_DIR="/home/$BOT_USER/max-money-bot"
REPO="https://github.com/bashnomad-dev/max-money-bot.git"

echo "[1/6] Системные пакеты (python3.12, ffmpeg, git)…"
apt-get update -y
apt-get install -y python3 python3-venv python3-pip ffmpeg git

echo "[2/6] Пользователь $BOT_USER…"
id -u "$BOT_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$BOT_USER"

echo "[3/6] Репозиторий…"
if [ -d "$APP_DIR/.git" ]; then
  sudo -u "$BOT_USER" git -C "$APP_DIR" pull --ff-only
else
  sudo -u "$BOT_USER" git clone "$REPO" "$APP_DIR"
fi

echo "[4/6] venv + зависимости…"
sudo -u "$BOT_USER" bash -lc "cd '$APP_DIR' && python3 -m venv .venv && .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q -r requirements.txt"

echo "[5/6] Каталоги и импорт прайса…"
sudo -u "$BOT_USER" mkdir -p "$APP_DIR/secrets" "$APP_DIR/data" "$APP_DIR/backups"
if [ ! -f "$APP_DIR/data/products-import.json" ] && [ -f "$APP_DIR/docs/intake/evgeny/price-normalized.json" ]; then
  sudo -u "$BOT_USER" cp "$APP_DIR/docs/intake/evgeny/price-normalized.json" "$APP_DIR/data/products-import.json"
fi

echo "[6/6] systemd…"
install -m 644 "$APP_DIR/deploy/maxbot.service" /etc/systemd/system/maxbot.service
systemctl daemon-reload
systemctl enable maxbot

cat <<EOF

✅ Установка завершена. Осталось вручную (секреты в git не лежат):

  1) Заполни конфиг:
       sudo -u $BOT_USER cp $APP_DIR/.env.example $APP_DIR/.env
       sudo -u $BOT_USER nano $APP_DIR/.env
       # MAX_BOT_TOKEN, GIGACHAT_CREDENTIALS, DEFAULT_SHEET_ID, ALLOWED_USER_IDS …

  2) Залей secrets/service-account.json в $APP_DIR/secrets/

  3) Права:
       chmod 600 $APP_DIR/.env $APP_DIR/secrets/service-account.json
       chown $BOT_USER:$BOT_USER $APP_DIR/.env $APP_DIR/secrets/service-account.json

  4) Запуск:
       systemctl start maxbot
       journalctl -u maxbot -f

  Бэкап Sheets (еженедельно) — root crontab -e:
    0 3 * * 0 cd $APP_DIR && sudo -u $BOT_USER .venv/bin/python -m scripts.backup_sheets >> $APP_DIR/backups/backup.log 2>&1
EOF
