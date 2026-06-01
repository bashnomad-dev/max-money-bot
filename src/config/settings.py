from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # === Внешние API ===
    max_bot_token: str = Field(default="")
    openai_api_key: str = Field(default="")
    anthropic_api_key: str = Field(default="")
    google_service_account_json: str = Field(default="./secrets/service-account.json")

    # === Sheets ===
    default_sheet_id: str = Field(default="")
    enable_processing_log_sheet: bool = Field(default=False)
    sheets_schema_version: str = Field(default="v2.0")

    # === Доступ ===
    allowed_user_ids: str = Field(default="")
    silent_reject: bool = Field(default=False)
    ops_pin: str = Field(default="", description="PIN для /undo, /edit, /inventory")
    pin_max_attempts: int = Field(default=3, ge=1, le=10)
    pin_lockout_minutes: int = Field(default=10, ge=1, le=120)

    # === Поведение ===
    log_level: str = Field(default="INFO")
    db_path: str = Field(default="./data/bot.sqlite3")
    tz: str = Field(default="Europe/Moscow")
    default_location: str = Field(default="", description="дефолтная точка/склад, если не упомянута")

    # === Отчёты ===
    daily_report_time: str = Field(default="21:00")
    daily_report_max_retries: int = Field(default=5, ge=1, le=20)

    # === Гибридный UX (SPEC §9) ===
    auto_write_confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    clarification_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    large_amount_threshold_rub: int = Field(
        default=100_000, gt=0,
        description="у магазина частые крупные закупки, потому больше прорабского 50k",
    )

    # === Дедупликация и диалоги ===
    dedup_window_minutes: int = Field(default=5, ge=1, le=60)
    dialog_state_ttl_minutes: int = Field(default=5, ge=1, le=60)

    # === Голос ===
    voice_max_duration_sec: int = Field(default=60, gt=0, le=600)
    enable_noise_reduction: bool = Field(default=False)

    # === Канонизация ===
    canon_similarity_threshold: float = Field(
        default=0.8, ge=0.0, le=1.0,
        description="порог fuzzy match для предложения «это известный товар?»",
    )

    # === Остатки и инвентаризация ===
    low_stock_threshold_default: int = Field(
        default=0, ge=0,
        description="0 = алерты выключены; >0 = по дефолту алерт при остатке ниже (v2)",
    )

    # === Бюджет ===
    monthly_api_budget_usd: float = Field(
        default=0.0, ge=0.0,
        description="0 = без лимита; при превышении бот приостанавливает",
    )

    @property
    def allowed_user_id_set(self) -> set[int]:
        return {int(x) for x in self.allowed_user_ids.split(",") if x.strip()}

    @property
    def large_amount_threshold_kopecks(self) -> int:
        return self.large_amount_threshold_rub * 100


settings = Settings()
