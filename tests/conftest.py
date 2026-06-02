"""Общие фикстуры pytest: in-memory мок gspread."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import pytest


# ============================================================
# Мок gspread Worksheet и Spreadsheet
# ============================================================

@dataclass
class FakeWorksheet:
    title: str
    rows: list[list] = field(default_factory=list)  # включая заголовок

    def row_values(self, row: int) -> list:
        if 1 <= row <= len(self.rows):
            return [str(c) if c is not None else "" for c in self.rows[row - 1]]
        return []

    def col_values(self, col: int) -> list:
        return [str(r[col - 1]) if len(r) >= col and r[col - 1] is not None else "" for r in self.rows]

    def cell(self, row: int, col: int):
        class _C:
            def __init__(self, v):
                self.value = v
        if 1 <= row <= len(self.rows) and len(self.rows[row - 1]) >= col:
            return _C(self.rows[row - 1][col - 1])
        return _C(None)

    def update(self, range_str_or_values, values=None, value_input_option=None):
        """Поддерживаем два вызова: ws.update("A1", [[...]]) и ws.update("A1:F5", [[...]])."""
        # Простая реализация для базового теста — переписывает с A1
        if values is None:
            values = range_str_or_values
            range_str = "A1"
        else:
            range_str = range_str_or_values
        # Парсим начальную ячейку
        col_letter = ""
        i = 0
        while i < len(range_str) and range_str[i].isalpha():
            col_letter += range_str[i]
            i += 1
        row_num = int("".join(c for c in range_str[i:] if c.isdigit()) or "1")
        col_idx = sum((ord(c.upper()) - ord("A") + 1) * (26 ** k) for k, c in enumerate(reversed(col_letter))) - 1

        # Расширяем rows если нужно
        for r_offset, row_vals in enumerate(values):
            target_row = row_num - 1 + r_offset
            while len(self.rows) <= target_row:
                self.rows.append([])
            while len(self.rows[target_row]) < col_idx + len(row_vals):
                self.rows[target_row].append("")
            for c_offset, v in enumerate(row_vals):
                self.rows[target_row][col_idx + c_offset] = v

    def append_rows(self, rows, value_input_option=None):
        for row in rows:
            self.rows.append(list(row))

    def append_row(self, row, value_input_option=None):
        self.rows.append(list(row))

    def delete_rows(self, row_index: int, end_index: int | None = None) -> None:
        if 1 <= row_index <= len(self.rows):
            self.rows.pop(row_index - 1)

    def get_all_values(self) -> list[list[str]]:
        return [[str(c) if c is not None else "" for c in r] for r in self.rows]

    def get_all_records(self) -> list[dict]:
        if not self.rows or len(self.rows) < 2:
            return []
        # Headers — первая или вторая строка (если первая — маркер)
        first = self.rows[0]
        if first and str(first[0] or "").startswith("СИСТЕМНЫЙ"):
            headers = [str(c) for c in self.rows[1]]
            data_rows = self.rows[2:]
        else:
            headers = [str(c) for c in self.rows[0]]
            data_rows = self.rows[1:]
        return [
            {h: (row[i] if i < len(row) else "") for i, h in enumerate(headers)}
            for row in data_rows
            if any(c for c in row)
        ]

    def batch_clear(self, ranges: list[str]) -> None:
        # Простая реализация: очищает все строки, начиная с указанной
        for r in ranges:
            try:
                start_row = int("".join(c for c in r.split(":")[0] if c.isdigit()))
                self.rows = self.rows[: start_row - 1]
            except ValueError:
                pass


class WorksheetNotFound(Exception):
    pass


@dataclass
class FakeSpreadsheet:
    title: str = "Тестовая таблица"
    _sheets: dict[str, FakeWorksheet] = field(default_factory=dict)

    def worksheet(self, name: str) -> FakeWorksheet:
        if name not in self._sheets:
            raise WorksheetNotFound(f"Worksheet {name!r} not found")
        return self._sheets[name]

    def add_worksheet(self, title: str, rows: int = 1000, cols: int = 20) -> FakeWorksheet:
        ws = FakeWorksheet(title=title, rows=[])
        self._sheets[title] = ws
        return ws


@pytest.fixture
def fake_spreadsheet() -> FakeSpreadsheet:
    return FakeSpreadsheet()


@pytest.fixture
def gspread_mock(monkeypatch):
    """Подменяет gspread.WorksheetNotFound на наш WorksheetNotFound для setup.ensure_worksheet."""
    import sys
    fake_gspread = type(sys)("gspread")
    fake_gspread.WorksheetNotFound = WorksheetNotFound
    sys.modules["gspread"] = fake_gspread
    yield
    sys.modules.pop("gspread", None)
