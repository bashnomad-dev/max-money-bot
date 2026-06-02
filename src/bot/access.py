"""Whitelist и PIN-защита для опасных команд."""
from __future__ import annotations

from src.config.settings import settings
from src.storage.repositories import PinAttemptsRepo


def is_allowed(user_id: int | str) -> bool:
    """Проверка whitelist по MAX user_id."""
    allowed = settings.allowed_user_id_set
    if not allowed:
        # Если whitelist пуст — для разработки разрешаем всем.
        # В production env обязательно надо задать ALLOWED_USER_IDS.
        return True
    try:
        return int(user_id) in allowed
    except (ValueError, TypeError):
        return False


def check_pin(user_id: str, pin: str | None, repo: PinAttemptsRepo) -> tuple[bool, str | None]:
    """Проверка PIN для опасных команд (/undo, /edit).

    Возвращает (ok, error_msg).
    Если PIN в env не задан — пропускаем без проверки.
    """
    if not settings.ops_pin:
        return True, None

    if repo.is_locked_out(user_id, settings.pin_max_attempts, settings.pin_lockout_minutes):
        return False, f"Слишком много неверных PIN. Команда заблокирована на {settings.pin_lockout_minutes} минут."

    if pin is None or pin != settings.ops_pin:
        repo.record(user_id, success=False)
        left = max(
            0,
            settings.pin_max_attempts
            - repo.failed_count_recent(user_id, settings.pin_lockout_minutes),
        )
        return False, f"Неверный PIN. Осталось попыток: {left}."

    repo.record(user_id, success=True)
    return True, None
