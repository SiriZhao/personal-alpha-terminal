from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    """Validated application configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PAT_",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    runtime_profile: Literal["PRODUCTION_DESKTOP", "DEVELOPMENT", "TEST"] = "DEVELOPMENT"
    database_url: str = "sqlite:///./var/personal_alpha.db"
    sql_echo: bool = False
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: int = Field(default=30, ge=1, le=300)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    database_statement_timeout_ms: int = Field(default=120_000, ge=1000, le=3_600_000)
    database_lock_timeout_ms: int = Field(default=10_000, ge=100, le=300_000)
    database_sslmode: Literal[
        "disable",
        "allow",
        "prefer",
        "require",
        "verify-ca",
        "verify-full",
    ] = "prefer"
    database_application_name: str = "personal-alpha-terminal"
    database_backup_dir: Path = Path("var/backups/postgresql")
    database_backup_retention_days: int = Field(default=30, ge=7, le=3650)
    database_pg_dump_path: str = "pg_dump"
    database_pg_restore_path: str = "pg_restore"
    database_restore_test_url: str | None = None
    daily_pipeline_timezone: str = "Asia/Shanghai"
    daily_pipeline_max_attempts: int = Field(default=3, ge=1, le=10)
    daily_pipeline_retry_backoff_seconds: float = Field(default=5.0, ge=0, le=60)
    daily_pipeline_analysis_lookback_days: int = Field(default=730, ge=30, le=3650)
    daily_pipeline_max_event_jobs: int = Field(default=10, ge=1, le=100)
    daily_pipeline_max_probability_jobs: int = Field(default=10, ge=1, le=100)
    daily_pipeline_report_path: Path = Path("DAILY_PIPELINE_REPORT.md")
    daily_pipeline_quality_report_path: Path = Path("DATA_QUALITY_REPORT.md")
    daily_pipeline_lock_path: Path = Path("var/run/daily_pipeline.lock")
    daily_pipeline_lock_stale_hours: int = Field(default=12, ge=1, le=168)
    log_level: str = "INFO"
    log_dir: Path = Path("var/logs")
    llm_provider: Literal[
        "auto",
        "openai",
        "deepseek",
        "anthropic",
        "custom",
        "mock",
        "disabled",
    ] = "disabled"
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    deepseek_api_key: str | None = Field(default=None, validation_alias="DEEPSEEK_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    custom_api_key: str | None = Field(default=None, validation_alias="CUSTOM_API_KEY")
    openai_model: str = "gpt-5.6-terra"
    deepseek_model: str = "deepseek-v4-flash"
    anthropic_model: str = "claude-sonnet-4-5"
    custom_model: str = "local-model"
    deepseek_base_url: str = "https://api.deepseek.com"
    anthropic_base_url: str = "https://api.anthropic.com"
    custom_base_url: str = "https://localhost:8000/v1"
    llm_temperature: float = Field(default=0.2, ge=0, le=2)
    llm_timeout_seconds: float = Field(default=60.0, ge=1, le=600)
    llm_max_retries: int = Field(default=2, ge=0, le=10)
    intelligence_max_requests_per_run: int = Field(default=100, ge=1, le=10_000)
    intelligence_max_tokens_per_run: int = Field(default=100_000, ge=100, le=10_000_000)
    intelligence_max_cost_per_run: float = Field(default=10.0, ge=0, le=100_000)
    intelligence_scanner_quant_weight: float = Field(default=0.75, ge=0, le=1)
    intelligence_scanner_probability_weight: float = Field(default=0.15, ge=0, le=1)
    intelligence_scanner_event_weight: float = Field(default=0.10, ge=0, le=0.25)
    intelligence_scanner_risk_penalty_weight: float = Field(default=0.20, ge=0, le=1)
    intelligence_expected_return_scale: float = Field(default=0.03, gt=0, le=1)
    intelligence_max_event_contribution: float = Field(default=0.10, ge=0, le=0.25)
    intelligence_max_ai_contribution: float = Field(default=0.0, ge=0, le=0.0)
    # Engineering defaults only. P1 features remain zero-weight until real-data OOS approval.
    intelligence_scanner_narrative_weight: float = Field(default=0.0, ge=0, le=0.10)
    intelligence_scanner_relationship_weight: float = Field(default=0.0, ge=0, le=0.10)
    intelligence_scanner_hypothesis_weight: float = Field(default=0.0, ge=0, le=0.10)
    intelligence_max_narrative_contribution: float = Field(default=0.05, ge=0, le=0.10)
    intelligence_max_relationship_contribution: float = Field(default=0.05, ge=0, le=0.10)
    intelligence_max_hypothesis_contribution: float = Field(default=0.05, ge=0, le=0.10)
    intelligence_narrative_half_life_days: float = Field(default=14.0, gt=0, le=365)
    intelligence_narrative_momentum_window_days: int = Field(default=7, ge=1, le=90)
    intelligence_narrative_single_event_cap: float = Field(default=0.25, gt=0, le=0.5)
    intelligence_narrative_minimum_emerging_sources: int = Field(default=2, ge=2, le=20)
    intelligence_narrative_source_diversity_target: int = Field(default=4, ge=2, le=50)
    intelligence_narrative_entity_breadth_target: int = Field(default=8, ge=2, le=500)
    intelligence_narrative_persistence_days: int = Field(default=30, ge=1, le=365)
    intelligence_relationship_windows: str = "20,60,120"
    intelligence_relationship_minimum_sample: int = Field(default=60, ge=30, le=5000)
    intelligence_relationship_maximum_lag: int = Field(default=5, ge=1, le=60)
    intelligence_relationship_fdr_threshold: float = Field(default=0.05, gt=0, lt=1)
    intelligence_relationship_minimum_effect: float = Field(default=0.20, ge=0, le=1)
    intelligence_relationship_minimum_oos_survival: float = Field(
        default=0.50, ge=0, le=1
    )
    intelligence_hypothesis_max_per_run: int = Field(default=25, ge=1, le=1000)
    intelligence_hypothesis_max_parameter_combinations: int = Field(
        default=100, ge=1, le=10_000
    )
    intelligence_hypothesis_max_threshold_combinations: int = Field(
        default=25, ge=1, le=1000
    )
    intelligence_hypothesis_max_horizon_combinations: int = Field(
        default=5, ge=1, le=100
    )
    intelligence_hypothesis_minimum_sample: int = Field(default=60, ge=30, le=10_000)
    intelligence_hypothesis_minimum_oos_sample: int = Field(default=20, ge=10, le=5000)
    intelligence_hypothesis_fdr_threshold: float = Field(default=0.05, gt=0, lt=1)
    intelligence_hypothesis_minimum_effect: float = Field(default=0.001, gt=0, le=1)
    intelligence_hypothesis_minimum_oos_stability: float = Field(default=0.50, ge=0, le=1)
    intelligence_hypothesis_minimum_regime_stability: float = Field(
        default=0.50, ge=0, le=1
    )
    intelligence_hypothesis_maximum_drawdown: float = Field(default=0.30, ge=0, le=1)
    intelligence_hypothesis_maximum_turnover: float = Field(default=2.0, ge=0, le=100)
    market_data_default_start: date = date(2010, 1, 1)
    market_data_overlap_days: int = Field(default=5, ge=0, le=30)
    market_data_max_retries: int = Field(default=2, ge=0, le=10)
    market_data_retry_backoff_seconds: float = Field(default=1.0, ge=0, le=60)
    market_data_timeout_seconds: int = Field(default=20, ge=1, le=120)
    market_data_provider_cache_dir: Path = Path("var/cache/providers")
    nasdaq_23h_enabled: bool = Field(
        default=False,
        validation_alias="NASDAQ_23H_ENABLED",
    )
    nasdaq_23h_effective_date: date | None = Field(
        default=None,
        validation_alias="NASDAQ_23H_EFFECTIVE_DATE",
    )
    night_execution_enabled: bool = False
    console_initial_history_days: int = Field(default=730, ge=90, le=3650)
    console_data_stale_days: int = Field(default=7, ge=1, le=31)
    console_auto_sync: bool = True
    dashboard_major_indices: str = "A:sh000001,HK:^HSI,US:^GSPC"
    dashboard_default_history_days: int = Field(default=365, ge=30, le=3650)
    dashboard_annual_risk_free_rate: float = Field(default=0.0, ge=-1, le=1)
    relationship_rolling_windows: str = "30,90,180"
    relationship_min_observations: int = Field(default=20, ge=2, le=1000)
    relationship_max_entities: int = Field(default=25, ge=2, le=100)
    relationship_baseline_window: int = Field(default=90, ge=2, le=1000)
    relationship_current_window: int = Field(default=30, ge=2, le=1000)
    relationship_change_threshold: float = Field(default=0.35, ge=0, le=2)
    event_study_horizons: str = "1,3,5,10,20"
    event_study_max_targets: int = Field(default=25, ge=1, le=100)
    event_study_default_cooldown_days: int = Field(default=5, ge=1, le=1000)
    event_study_minimum_sample_size: int = Field(default=30, ge=30, le=10000)
    event_study_confidence_level: float = Field(default=0.95, gt=0, lt=1)
    event_study_bootstrap_resamples: int = Field(default=10_000, ge=1000, le=100_000)
    event_study_default_win_threshold: float = Field(default=0.0, ge=-1, le=10)
    conditional_probability_horizons: str = "1,5,20"
    conditional_probability_minimum_sample_size: int = Field(
        default=30,
        ge=2,
        le=10000,
    )
    conditional_probability_confidence_level: float = Field(
        default=0.95,
        gt=0,
        lt=1,
    )
    conditional_probability_max_targets: int = Field(default=25, ge=1, le=100)
    conditional_probability_prior_alpha: float = Field(default=1.0, gt=0, le=100)
    conditional_probability_prior_beta: float = Field(default=1.0, gt=0, le=100)
    market_graph_minimum_observations: int = Field(default=60, ge=10, le=5000)
    market_graph_maximum_nodes: int = Field(default=30, ge=2, le=200)
    market_graph_correlation_threshold: float = Field(default=0.5, ge=0, le=1)
    market_graph_maximum_lag_days: int = Field(default=5, ge=1, le=60)
    market_graph_lead_threshold: float = Field(default=0.3, ge=0, le=1)
    market_graph_lead_improvement: float = Field(default=0.05, ge=0, le=1)
    market_graph_capital_threshold: float = Field(default=0.25, ge=0, le=1)
    market_graph_flow_lookback_days: int = Field(default=20, ge=2, le=252)
    market_graph_maximum_paths: int = Field(default=20, ge=1, le=500)
    market_graph_significance_alpha: float = Field(default=0.05, gt=0, lt=1)
    market_graph_significance_method: Literal["fdr", "bonferroni"] = "fdr"
    lead_lag_maximum_assets: int = Field(default=20, ge=2, le=100)
    lead_lag_maximum_lag_days: int = Field(default=5, ge=1, le=60)
    lead_lag_minimum_observations: int = Field(default=120, ge=20, le=10000)
    lead_lag_minimum_abs_correlation: float = Field(default=0.2, ge=0, le=1)
    lead_lag_fdr_alpha: float = Field(default=0.1, gt=0, lt=1)
    regime_rate_change_window: int = Field(default=20, ge=2, le=252)
    regime_dollar_trend_window: int = Field(default=20, ge=2, le=252)
    regime_index_trend_window: int = Field(default=60, ge=5, le=504)
    regime_breadth_window: int = Field(default=50, ge=5, le=504)
    regime_calibration_window: int = Field(default=252, ge=20, le=1260)
    regime_minimum_calibration_observations: int = Field(
        default=60,
        ge=20,
        le=1260,
    )
    regime_minimum_breadth_assets: int = Field(default=10, ge=2, le=10000)
    regime_maximum_breadth_assets: int = Field(default=2000, ge=2, le=10000)
    regime_softmax_temperature: float = Field(default=0.75, gt=0.05, le=10)
    regime_neutral_bias: float = Field(default=0.5, ge=-5, le=5)
    regime_probability_label_horizon: int = Field(default=20, ge=1, le=252)
    regime_probability_return_threshold: float = Field(default=0.02, gt=0, lt=1)
    regime_probability_minimum_training_observations: int = Field(
        default=252,
        ge=30,
        le=5000,
    )
    regime_probability_minimum_oos_observations: int = Field(
        default=126,
        ge=30,
        le=5000,
    )
    regime_probability_minimum_class_observations: int = Field(
        default=20,
        ge=2,
        le=1000,
    )
    regime_probability_calibration_bins: int = Field(default=5, ge=2, le=20)
    regime_probability_minimum_bin_observations: int = Field(
        default=10,
        ge=2,
        le=1000,
    )
    regime_probability_minimum_brier_improvement: float = Field(
        default=0.001,
        ge=0,
        le=1,
    )
    factor_momentum_lookback: int = Field(default=252, ge=20, le=1260)
    factor_momentum_skip: int = Field(default=21, ge=0, le=252)
    factor_volatility_window: int = Field(default=63, ge=10, le=504)
    factor_minimum_categories: int = Field(default=3, ge=1, le=5)
    factor_minimum_scored_stocks: int = Field(default=5, ge=2, le=10000)
    factor_maximum_universe_size: int = Field(default=2000, ge=2, le=10000)
    factor_selection_quantile: float = Field(default=0.2, gt=0, le=1)
    factor_rebalance_interval: int = Field(default=21, ge=1, le=252)
    factor_holding_period: int = Field(default=21, ge=1, le=252)
    factor_annual_risk_free_rate: float = Field(default=0.0, ge=-1, le=1)
    portfolio_risk_minimum_observations: int = Field(
        default=60,
        ge=2,
        le=5000,
    )
    portfolio_fx_max_staleness_days: int = Field(default=5, ge=0, le=31)
    portfolio_price_max_staleness_days: int = Field(default=7, ge=0, le=31)
    portfolio_maximum_absolute_beta: float = Field(default=3.0, gt=0, le=20)
    portfolio_risk_annual_risk_free_rate: float = Field(
        default=0.0,
        ge=-1,
        le=1,
    )
    portfolio_stress_max_scenarios: int = Field(default=10, ge=1, le=100)
    portfolio_rebalance_drift_threshold: float = Field(default=0.05, ge=0, le=1)
    portfolio_minimum_rebalance_value: float = Field(default=100.0, ge=0)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized

    @field_validator(
        "openai_api_key",
        "deepseek_api_key",
        "anthropic_api_key",
        "custom_api_key",
    )
    @classmethod
    def normalize_optional_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("openai_model", "deepseek_model", "anthropic_model", "custom_model")
    @classmethod
    def validate_llm_model(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("LLM model name cannot be empty")
        return normalized

    @field_validator("deepseek_base_url", "anthropic_base_url", "custom_base_url")
    @classmethod
    def validate_llm_base_url(cls, value: str) -> str:
        from urllib.parse import urlparse

        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("external LLM Base URL must be a valid HTTPS URL")
        return normalized

    @model_validator(mode="after")
    def validate_production_database(self) -> "Settings":
        url = make_url(self.database_url)
        if self.app_env != "production":
            return self
        if url.get_backend_name() != "postgresql":
            raise ValueError("production environment requires a PostgreSQL database URL")
        if self.database_sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("production PostgreSQL requires sslmode=require or stronger")
        if not url.username or not url.database:
            raise ValueError("production PostgreSQL URL requires a user and database name")
        return self

    @model_validator(mode="after")
    def validate_intelligence_guardrails(self) -> "Settings":
        if (
            self.intelligence_scanner_event_weight
            > self.intelligence_max_event_contribution
        ):
            raise ValueError(
                "scanner event weight exceeds the intelligence contribution guardrail"
            )
        guardrails = (
            (
                self.intelligence_scanner_narrative_weight,
                self.intelligence_max_narrative_contribution,
                "narrative",
            ),
            (
                self.intelligence_scanner_relationship_weight,
                self.intelligence_max_relationship_contribution,
                "relationship",
            ),
            (
                self.intelligence_scanner_hypothesis_weight,
                self.intelligence_max_hypothesis_contribution,
                "hypothesis",
            ),
        )
        for weight, maximum, name in guardrails:
            if weight > maximum:
                raise ValueError(
                    f"scanner {name} weight exceeds the intelligence contribution guardrail"
                )
        return self

    @field_validator("intelligence_relationship_windows")
    @classmethod
    def validate_intelligence_relationship_windows(cls, value: str) -> str:
        try:
            windows = tuple(int(item.strip()) for item in value.split(",") if item.strip())
        except ValueError as error:
            raise ValueError("intelligence relationship windows must contain integers") from error
        if not windows or tuple(sorted(set(windows))) != windows or min(windows) < 3:
            raise ValueError("intelligence relationship windows must be sorted and unique")
        return ",".join(str(window) for window in windows)

    @field_validator("daily_pipeline_timezone")
    @classmethod
    def validate_daily_pipeline_timezone(cls, value: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError("daily_pipeline_timezone must be an IANA timezone") from error
        return value

    @field_validator("relationship_rolling_windows")
    @classmethod
    def validate_relationship_rolling_windows(cls, value: str) -> str:
        try:
            windows = tuple(int(item.strip()) for item in value.split(",") if item.strip())
        except ValueError as error:
            raise ValueError("relationship_rolling_windows must contain integers") from error
        if not windows or any(window < 2 or window > 1000 for window in windows):
            raise ValueError("relationship rolling windows must be between 2 and 1000")
        if len(set(windows)) != len(windows):
            raise ValueError("relationship rolling windows must be unique")
        return ",".join(str(window) for window in windows)

    @field_validator("event_study_horizons")
    @classmethod
    def validate_event_study_horizons(cls, value: str) -> str:
        try:
            horizons = tuple(int(item.strip()) for item in value.split(",") if item.strip())
        except ValueError as error:
            raise ValueError("event_study_horizons must contain integers") from error
        if not horizons or any(horizon < 1 or horizon > 1000 for horizon in horizons):
            raise ValueError("event study horizons must be between 1 and 1000")
        if len(set(horizons)) != len(horizons):
            raise ValueError("event study horizons must be unique")
        return ",".join(str(horizon) for horizon in sorted(horizons))

    @field_validator("conditional_probability_horizons")
    @classmethod
    def validate_conditional_probability_horizons(cls, value: str) -> str:
        try:
            horizons = tuple(int(item.strip()) for item in value.split(",") if item.strip())
        except ValueError as error:
            raise ValueError("conditional_probability_horizons must contain integers") from error
        if not horizons or any(horizon < 1 or horizon > 1000 for horizon in horizons):
            raise ValueError("conditional probability horizons must be between 1 and 1000")
        if len(set(horizons)) != len(horizons):
            raise ValueError("conditional probability horizons must be unique")
        return ",".join(str(horizon) for horizon in sorted(horizons))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
