"""Конфигурация из .env. Соответствует .env.example."""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # === MAX ===
    max_bot_token: str = Field(default="")

    # === LLM (российский стек) ===
    gigachat_credentials: str = Field(default="")
    gigachat_scope: str = Field(default="GIGACHAT_API_PERS")
    gigachat_model: str = Field(default="GigaChat-Max")
    gigachat_verify_ssl: bool = Field(default=False)
    gigachat_timeout_sec: int = Field(default=30, ge=5, le=300)
    llm_backend: str = Field(default="gigachat", description="gigachat | claude | openrouter")
    llm_backend_fallback: str = Field(default="", description="claude / gigachat / openrouter или пусто")

    # === OpenRouter (доступ к Claude/GPT/Gemini единым API) ===
    openrouter_api_key: str = Field(default="")
    openrouter_model: str = Field(
        default="anthropic/claude-haiku-4.5",
        description="anthropic/claude-haiku-4.5 (дёшево, быстро) | anthropic/claude-sonnet-4.6 (точнее) | openai/gpt-5",
    )
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")
    openrouter_timeout_sec: int = Field(default=30, ge=5, le=300)

    # === STT ===
    stt_engine: str = Field(default="gigaam", description="gigaam | whisper")
    gigaam_model: str = Field(default="v2_rnnt")
    openai_api_key: str = Field(default="")  # для whisper fallback
    anthropic_api_key: str = Field(default="")  # для claude fallback

    # === Sheets ===
    google_service_account_json: str = Field(default="./secrets/service-account.json")
    default_sheet_id: str = Field(default="")
    enable_processing_log_sheet: bool = Field(default=False)

    # === Доступ ===
    allowed_user_ids: str = Field(default="")
    silent_reject: bool = Field(default=False)
    ops_pin: str = Field(default="")
    pin_max_attempts: int = Field(default=3, ge=1, le=10)
    pin_lockout_minutes: int = Field(default=10, ge=1, le=120)

    # === Поведение ===
    tz: str = Field(default="Europe/Moscow")
    log_level: str = Field(default="INFO")
    db_path: str = Field(default="./data/bot.sqlite3")
    default_location: str = Field(default="", description="Магазин Зинино или Магазин Кармалы")

    # === Отчёты ===
    daily_report_time: str = Field(default="21:00")
    daily_report_max_retries: int = Field(default=5, ge=1, le=20)

    # === Гибридный UX ===
    auto_write_confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    clarification_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    large_amount_threshold_rub: int = Field(default=150_000, gt=0)

    # === Канонизация ===
    canon_similarity_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    products_import_path: str = Field(default="./data/products-import.json")

    # === Дедуп/диалоги ===
    dedup_window_minutes: int = Field(default=5, ge=1, le=60)
    dialog_state_ttl_minutes: int = Field(default=5, ge=1, le=60)

    # === Голос ===
    voice_max_duration_sec: int = Field(default=120, gt=0, le=600)
    enable_noise_reduction: bool = Field(default=False)

    # === Бюджет ===
    monthly_api_budget_rub: float = Field(default=0.0, ge=0.0)

    @property
    def allowed_user_id_set(self) -> set[int]:
        return {int(x) for x in self.allowed_user_ids.split(",") if x.strip()}

    @property
    def large_amount_threshold_kopecks(self) -> int:
        return self.large_amount_threshold_rub * 100


settings = Settings()
