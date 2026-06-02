"""Stateful-диалоги: уточнения, канонизация, undo confirm, инвентаризация."""
from src.dialog.engine import DialogEngine, DialogResult, DialogStep
from src.dialog.semantic_hash import semantic_hash

__all__ = ["DialogEngine", "DialogResult", "DialogStep", "semantic_hash"]
