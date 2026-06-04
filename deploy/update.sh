#!/usr/bin/env bash
# Обновление кода max-money-bot на сервере. Запуск от root:  bash update.sh
set -euo pipefail

BOT_USER=maxbot
APP_DIR="/home/$BOT_USER/max-money-bot"

sudo -u "$BOT_USER" git -C "$APP_DIR" pull --ff-only
sudo -u "$BOT_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
systemctl restart maxbot
sleep 2
systemctl --no-pager --lines=10 status maxbot
