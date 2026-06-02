"""Еженедельный бэкап Google Sheets в .xlsx.

Использование (запускается из cron):
    python -m scripts.backup_sheets

Бэкапит таблицу из settings.default_sheet_id (или все привязанные чаты из SQLite).
Файлы кладутся в backups/<sheet_id>-<YYYY-MM-DD>.xlsx, оставляются последние 12.

Зависит от:
- gspread + service account (как и основной бот)
- openpyxl для записи .xlsx

Без жёстких ошибок: пустые/недоступные таблицы логируются и пропускаются.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# чтобы запускался как `python -m scripts.backup_sheets`
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import settings
from src.sheets.setup import open_sheet
from src.storage.db import open_initialized

log = logging.getLogger("backup_sheets")

BACKUPS_DIR = Path("backups")
KEEP_LAST_N = 12


def _collect_sheet_ids() -> list[str]:
    """Собрать все sheet_id: default + все привязанные из SQLite."""
    ids: list[str] = []
    if settings.default_sheet_id:
        ids.append(settings.default_sheet_id)
    try:
        db = open_initialized(settings.db_path)
        rows = db.execute("SELECT DISTINCT sheet_id FROM chat_sheets").fetchall()
        for r in rows:
            sid = r["sheet_id"]
            if sid and sid not in ids:
                ids.append(sid)
    except Exception:
        log.exception("Не смог прочитать chat_sheets из БД — продолжаю без них")
    return ids


def _dump_one(sheet_id: str, out_dir: Path) -> Path | None:
    """Дамп одной таблицы в .xlsx. Возвращает путь или None при ошибке."""
    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError:
        log.error("openpyxl не установлен — pip install openpyxl")
        return None

    try:
        spreadsheet = open_sheet(sheet_id)
    except Exception:
        log.exception("open_sheet(%s) упал", sheet_id)
        return None

    wb = Workbook()
    wb.remove(wb.active)  # удалим пустой дефолтный лист
    written_any = False
    for ws in spreadsheet.worksheets():
        try:
            values = ws.get_all_values()
        except Exception:
            log.exception("worksheet(%s).get_all_values упал", ws.title)
            continue
        new_ws = wb.create_sheet(title=ws.title[:31])  # excel ограничивает 31 символ
        for row in values:
            new_ws.append(row)
        written_any = True

    if not written_any:
        log.warning("sheet=%s: ни одного листа не прочитано", sheet_id)
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    out_path = out_dir / f"{sheet_id[:12]}-{ts}.xlsx"
    wb.save(out_path)
    log.info("backup ok: %s -> %s", sheet_id, out_path)
    return out_path


def _rotate(out_dir: Path, sheet_prefix: str, keep: int) -> int:
    """Оставить последние `keep` бэкапов с данным префиксом. Возвращает кол-во удалённых."""
    files = sorted(out_dir.glob(f"{sheet_prefix}-*.xlsx"), reverse=True)
    removed = 0
    for f in files[keep:]:
        try:
            f.unlink()
            removed += 1
        except OSError:
            log.exception("Не смог удалить %s", f)
    return removed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    ids = _collect_sheet_ids()
    if not ids:
        log.error("Ни одной Google-таблицы не найдено (ни DEFAULT_SHEET_ID, ни в БД).")
        return 1

    out_dir = BACKUPS_DIR
    failed = 0
    for sheet_id in ids:
        path = _dump_one(sheet_id, out_dir)
        if path is None:
            failed += 1
            continue
        removed = _rotate(out_dir, sheet_id[:12], KEEP_LAST_N)
        if removed:
            log.info("ротация: удалено %d старых для %s", removed, sheet_id[:12])

    if failed:
        log.warning("Завершено с ошибками: %d из %d", failed, len(ids))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
