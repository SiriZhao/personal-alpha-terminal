import pytest
from pydantic import ValidationError

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig


def test_settings_accept_explicit_sqlite_configuration() -> None:
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///./var/test-config.db",
        log_dir="var/test-config-logs",
        log_level="debug",
    )

    assert settings.database_url.startswith("sqlite:///")
    assert settings.log_level == "DEBUG"


def test_production_requires_secure_postgresql() -> None:
    with pytest.raises(ValidationError, match="requires a PostgreSQL"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="sqlite:///./var/not-production.db",
            database_sslmode="require",
        )

    with pytest.raises(ValidationError, match="sslmode"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+psycopg://pat:secret@localhost/pat",
            database_sslmode="prefer",
        )

    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://pat:secret@localhost/pat",
        database_sslmode="require",
    )
    assert settings.app_env == "production"


def test_settings_reject_unknown_log_level() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="VERBOSE")


def test_relationship_windows_are_normalized_and_validated() -> None:
    settings = Settings(_env_file=None, relationship_rolling_windows="30, 90,180")
    assert settings.relationship_rolling_windows == "30,90,180"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, relationship_rolling_windows="30,30")


def test_event_study_horizons_are_sorted_and_validated() -> None:
    settings = Settings(_env_file=None, event_study_horizons="20, 1,5,3,10")
    assert settings.event_study_horizons == "1,3,5,10,20"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, event_study_horizons="1,5,5")


def test_conditional_probability_horizons_are_validated() -> None:
    settings = Settings(
        _env_file=None,
        conditional_probability_horizons="20, 1,5",
    )
    assert settings.conditional_probability_horizons == "1,5,20"

    with pytest.raises(ValidationError):
        Settings(_env_file=None, conditional_probability_horizons="1,1")


def test_lead_lag_thresholds_are_validated() -> None:
    settings = Settings(
        _env_file=None,
        lead_lag_maximum_lag_days=10,
        lead_lag_minimum_observations=200,
        lead_lag_fdr_alpha=0.05,
    )
    assert settings.lead_lag_maximum_lag_days == 10
    assert settings.lead_lag_minimum_observations == 200

    with pytest.raises(ValidationError):
        Settings(_env_file=None, lead_lag_fdr_alpha=1)


def test_market_regime_parameters_are_validated() -> None:
    settings = Settings(
        _env_file=None,
        regime_calibration_window=300,
        regime_softmax_temperature=0.5,
    )
    assert settings.regime_calibration_window == 300
    assert settings.regime_softmax_temperature == 0.5

    with pytest.raises(ValidationError):
        Settings(_env_file=None, regime_softmax_temperature=0)


def test_factor_research_parameters_are_validated() -> None:
    settings = Settings(
        _env_file=None,
        factor_selection_quantile=0.25,
        factor_holding_period=42,
    )
    assert settings.factor_selection_quantile == 0.25
    assert settings.factor_holding_period == 42

    with pytest.raises(ValidationError):
        Settings(_env_file=None, factor_selection_quantile=0)


def test_portfolio_risk_parameters_are_validated() -> None:
    settings = Settings(
        _env_file=None,
        portfolio_risk_minimum_observations=120,
        portfolio_fx_max_staleness_days=7,
        portfolio_maximum_absolute_beta=4.0,
    )
    assert settings.portfolio_risk_minimum_observations == 120
    assert settings.portfolio_fx_max_staleness_days == 7

    with pytest.raises(ValidationError):
        Settings(_env_file=None, portfolio_maximum_absolute_beta=0)


def test_effective_config_rejects_unknown_or_duplicate_independent_provider() -> None:
    assert (
        EffectiveRuntimeConfig(
            independent_provider_priority=()
        ).independent_provider_priority
        == ()
    )

    with pytest.raises(ValueError, match="unsupported independent provider"):
        EffectiveRuntimeConfig(independent_provider_priority=("unknown",))

    with pytest.raises(ValueError, match="contains duplicates"):
        EffectiveRuntimeConfig(
            independent_provider_priority=("twelve_data", "twelve_data")
        )
