from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.quant_engine.costs import TransactionCostConfig
from personal_alpha_terminal.quant_engine.portfolio.construction import (
    PortfolioConstraints,
)
from personal_alpha_terminal.quant_engine.risk.model import RiskModelConfig
from personal_alpha_terminal.quant_engine.risk.stress import StressRiskConfig
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1Config,
)

DEFAULT_SYMBOLS = (
    "SPY",
    "QQQ",
    "IWM",
    "VTI",
    "TLT",
    "GLD",
    "SHY",
    "^VIX",
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "AVGO",
    "JPM",
    "XOM",
    "UNH",
)
DEFAULT_REQUIRED_SYMBOLS = DEFAULT_SYMBOLS


@dataclass(frozen=True, slots=True)
class BroadUniverseConfig:
    minimum_price: float = 5.0
    minimum_trading_sessions: int = 252
    minimum_average_dollar_volume: float = 10_000_000.0
    minimum_median_dollar_volume: float = 10_000_000.0
    minimum_valid_bar_coverage: float = 0.98
    maximum_missing_ratio: float = 0.02
    include_adr: bool = False
    include_reit: bool = False
    # When False, the production daily path uses the broad current operational
    # universe (CURRENT_OPERATIONAL_PIT).  When True, it stays on the strict
    # certified total-return tier (HISTORICAL_RESEARCH_PIT).
    require_pit_total_return: bool = True
    # Fail-closed guards for the current operational universe.
    minimum_operational_universe: int = 50
    coverage_collapse_ratio: float = 0.5
    # Candidate compression bound feeding the portfolio optimizer.
    candidate_max: int = 100
    candidate_min_alpha: float = 0.0

    def __post_init__(self) -> None:
        if self.minimum_price <= 0 or self.minimum_trading_sessions < 1:
            raise ValueError("broad universe price/history thresholds are invalid")
        if (
            min(
                self.minimum_average_dollar_volume,
                self.minimum_median_dollar_volume,
            )
            <= 0
        ):
            raise ValueError("broad universe liquidity thresholds are invalid")
        if not 0 <= self.minimum_valid_bar_coverage <= 1:
            raise ValueError("broad universe coverage threshold is invalid")
        if not 0 <= self.maximum_missing_ratio <= 1:
            raise ValueError("broad universe missing-data threshold is invalid")
        if self.minimum_operational_universe < 1:
            raise ValueError("broad universe minimum operational size is invalid")
        if not 0 < self.coverage_collapse_ratio <= 1:
            raise ValueError("broad universe coverage collapse ratio is invalid")
        if self.candidate_max < 1:
            raise ValueError("broad universe candidate bound is invalid")


@dataclass(frozen=True, slots=True)
class EffectiveRuntimeConfig:
    """The single resolved, immutable configuration used by production code."""

    market: str = "US"
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    benchmark: str = "SPY"
    nasdaq_benchmark: str = "QQQ"
    vix_symbol: str = "^VIX"
    history_start: str = "2015-01-01"
    cache_dir: Path = Path("data/cache")
    report_dir: Path = Path("reports")
    operational_policy_path: Path = Path("var/operational/operational_policy.json")
    operational_universe_baseline_path: Path = Path(
        "var/operational-universe-baseline.json"
    )
    forward_ledger_path: Path = Path("var/forward-ledger.jsonl")
    shadow_ledger_path: Path = Path("var/shadow-ledger.jsonl")
    shadow_registry_path: Path = Path("var/alpha-engine2/research-registry.jsonl")
    # Optional ROUND 8 shadow challenger.  When set, the daily run records
    # what the challenger would recommend (SHADOW) without ever affecting
    # the official recommendation, target or ledger.  Disabled by default.
    shadow_challenger_id: str | None = None
    shadow_coefficients: dict[str, float] | None = None
    primary_provider: str = "yahoo"
    fallback_provider: str = "stooq"
    provider_priority: tuple[str, ...] = (
        "yahoo",
        "stooq",
    )
    independent_provider_priority: tuple[str, ...] = (
        "twelve_data",
        "alpha_vantage",
        "stooq",
    )
    timeout_seconds: int = 20
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    reconciliation_minimum_coverage: float = 0.95
    reconciliation_warning_tolerance: float = 0.01
    reconciliation_blocking_tolerance: float = 0.05
    reconciliation_maximum_blocking_ratio: float = 0.01
    reconciliation_minimum_overlap_sessions: int = 20
    reconciliation_preferred_overlap_sessions: int = 60
    nasdaq_23h_enabled: bool = False
    nasdaq_23h_effective_date: date | None = None
    night_execution_enabled: bool = False
    default_execution_session: str = "REGULAR"
    allow_calendar_fallback: bool = False
    # Stable external portfolio key. Database foreign keys remain integers, while
    # operators select the unique ledger name (normally ``main``).
    portfolio_id: int | str | None = None
    required_symbols: tuple[str, ...] = DEFAULT_REQUIRED_SYMBOLS
    broad_universe: BroadUniverseConfig = field(default_factory=BroadUniverseConfig)
    strategy: USAdaptiveAlphaCoreV1Config = field(default_factory=USAdaptiveAlphaCoreV1Config)
    portfolio_constraints: PortfolioConstraints = field(default_factory=PortfolioConstraints)
    risk_model: RiskModelConfig = field(default_factory=RiskModelConfig)
    stress_risk: StressRiskConfig = field(default_factory=StressRiskConfig)
    transaction_cost: TransactionCostConfig = field(default_factory=TransactionCostConfig)
    settings: Settings = field(default_factory=Settings, repr=False, compare=False)
    source_path: Path | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.market != "US":
            raise ValueError("the production terminal supports market=US only")
        if not self.provider_priority:
            raise ValueError("at least one provider must be configured")
        allowed_independent_providers = {"twelve_data", "alpha_vantage", "stooq"}
        unsupported = set(self.independent_provider_priority) - allowed_independent_providers
        if unsupported:
            names = ", ".join(sorted(unsupported))
            raise ValueError(f"unsupported independent provider(s): {names}")
        if len(set(self.independent_provider_priority)) != len(self.independent_provider_priority):
            raise ValueError("independent provider priority contains duplicates")
        if self.night_execution_enabled:
            raise ValueError("night execution is disabled for manual execution")
        if not 0.5 <= self.reconciliation_minimum_coverage <= 1:
            raise ValueError("reconciliation minimum coverage is invalid")
        if (
            self.reconciliation_preferred_overlap_sessions
            < self.reconciliation_minimum_overlap_sessions
        ):
            raise ValueError("preferred reconciliation overlap must be at least the minimum")

    @property
    def strategy_parameter_hash(self) -> str:
        return self.strategy.parameter_fingerprint

    @property
    def portfolio_constraint_hash(self) -> str:
        values = asdict(self.portfolio_constraints)
        values.pop("model_validation_id", None)
        return fingerprint(values)

    @property
    def risk_model_hash(self) -> str:
        stress_parameters = asdict(self.stress_risk)
        stress_parameters.pop("production_validated")
        stress_parameters.pop("validation_id")
        stress_parameters.pop("provisional_operational")
        return fingerprint({"risk_model": self.risk_model, "stress_risk": stress_parameters})

    @property
    def cost_model_hash(self) -> str:
        return fingerprint(self.transaction_cost)

    @property
    def validation_artifact_dir(self) -> Path:
        return self.report_dir / "validation-artifacts"

    @property
    def runtime_config_hash(self) -> str:
        return fingerprint(self.identity_payload())

    @property
    def canonical_run_config_hash(self) -> str:
        return fingerprint(
            {
                "runtime_config_hash": self.runtime_config_hash,
                "strategy_parameter_hash": self.strategy_parameter_hash,
                "portfolio_constraint_hash": self.portfolio_constraint_hash,
                "risk_model_hash": self.risk_model_hash,
                "cost_model_hash": self.cost_model_hash,
            }
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "market": self.market,
            "symbols": self.symbols,
            "required_symbols": self.required_symbols,
            "benchmark": self.benchmark,
            "nasdaq_benchmark": self.nasdaq_benchmark,
            "vix_symbol": self.vix_symbol,
            "history_start": self.history_start,
            "cache_dir": self.cache_dir,
            "report_dir": self.report_dir,
            "provider_priority": self.provider_priority,
            "independent_provider_priority": self.independent_provider_priority,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "reconciliation_minimum_coverage": self.reconciliation_minimum_coverage,
            "reconciliation_warning_tolerance": self.reconciliation_warning_tolerance,
            "reconciliation_blocking_tolerance": self.reconciliation_blocking_tolerance,
            "reconciliation_maximum_blocking_ratio": self.reconciliation_maximum_blocking_ratio,
            "reconciliation_minimum_overlap_sessions": self.reconciliation_minimum_overlap_sessions,
            "reconciliation_preferred_overlap_sessions": (
                self.reconciliation_preferred_overlap_sessions
            ),
            "nasdaq_23h_enabled": self.nasdaq_23h_enabled,
            "nasdaq_23h_effective_date": self.nasdaq_23h_effective_date,
            "night_execution_enabled": self.night_execution_enabled,
            "default_execution_session": self.default_execution_session,
            "allow_calendar_fallback": self.allow_calendar_fallback,
            "portfolio_id": self.portfolio_id,
            "broad_universe": asdict(self.broad_universe),
            "llm": {
                "provider": self.settings.llm_provider,
                "deepseek_model": self.settings.deepseek_model,
                "deepseek_reasoning_model": self.settings.deepseek_reasoning_model,
                "deepseek_reasoning_mode": self.settings.deepseek_reasoning_mode,
                "deepseek_reasoning_effort": self.settings.deepseek_reasoning_effort,
                "event_intelligence": self.settings.llm_event_intelligence,
                "filing_intelligence": self.settings.llm_filing_intelligence,
                "relation_graph": self.settings.llm_relation_graph,
                "embeddings": self.settings.llm_embeddings,
                "research_agent": self.settings.llm_research_agent,
                "event_prompt_version": "event-extraction-v2",
            },
        }


def resolve_effective_runtime_config(
    path: Path,
    *,
    environment: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, object] | None = None,
) -> EffectiveRuntimeConfig:
    environment = os.environ if environment is None else environment
    scalar, lists, holdings = _read_restricted_yaml(path)
    if holdings:
        raise ValueError("holdings in config.yaml are forbidden; use the real portfolio ledger")
    settings = Settings(_env_file=None)
    config = EffectiveRuntimeConfig(
        market=scalar.get("market", "US").upper(),
        symbols=tuple(item.upper() for item in lists.get("symbols", DEFAULT_SYMBOLS)),
        required_symbols=tuple(
            item.upper() for item in lists.get("required_symbols", DEFAULT_REQUIRED_SYMBOLS)
        ),
        benchmark=scalar.get("benchmark", "SPY").upper(),
        nasdaq_benchmark=scalar.get("nasdaq_benchmark", "QQQ").upper(),
        vix_symbol=scalar.get("vix_symbol", "^VIX").upper(),
        history_start=scalar.get("history_start", "2015-01-01"),
        cache_dir=Path(scalar.get("cache_dir", "data/cache")),
        report_dir=Path(scalar.get("report_dir", "reports")),
        operational_policy_path=Path(
            scalar.get(
                "operational_policy_path",
                str(settings.operational_policy_path),
            )
        ),
        operational_universe_baseline_path=Path(
            scalar.get(
                "operational_universe_baseline_path",
                "var/operational-universe-baseline.json",
            )
        ),
        forward_ledger_path=Path(
            scalar.get("forward_ledger_path", "var/forward-ledger.jsonl")
        ),
        shadow_ledger_path=Path(
            scalar.get("shadow_ledger_path", "var/shadow-ledger.jsonl")
        ),
        shadow_registry_path=Path(
            scalar.get("shadow_registry_path", "var/alpha-engine2/research-registry.jsonl")
        ),
        shadow_challenger_id=_optional_text(scalar, "shadow_challenger_id"),
        shadow_coefficients=_optional_float_map(
            scalar,
            "shadow_momentum_coefficient",
            "shadow_trend_coefficient",
            "shadow_volatility_coefficient",
        ),
        primary_provider=scalar.get("primary_provider", "yahoo").lower(),
        fallback_provider=scalar.get("fallback_provider", "twelve_data").lower(),
        provider_priority=tuple(
            dict.fromkeys(
                item.lower()
                for item in lists.get(
                    "provider_priority",
                    (
                        scalar.get("primary_provider", "yahoo"),
                        scalar.get("fallback_provider", "twelve_data"),
                    ),
                )
            )
        ),
        independent_provider_priority=tuple(
            item.lower()
            for item in lists.get(
                "independent_provider_priority",
                ("twelve_data", "alpha_vantage", "stooq"),
            )
        ),
        timeout_seconds=_integer(scalar, "timeout_seconds", settings.market_data_timeout_seconds),
        max_retries=_integer(scalar, "max_retries", settings.market_data_max_retries),
        retry_backoff_seconds=_number(
            scalar, "retry_backoff_seconds", settings.market_data_retry_backoff_seconds
        ),
        reconciliation_minimum_coverage=_number(
            scalar,
            "reconciliation_minimum_coverage",
            settings.market_data_reconciliation_minimum_coverage,
        ),
        reconciliation_warning_tolerance=_number(
            scalar,
            "reconciliation_warning_tolerance",
            settings.market_data_reconciliation_warning_return_tolerance,
        ),
        reconciliation_blocking_tolerance=_number(
            scalar,
            "maximum_provider_difference",
            settings.market_data_reconciliation_blocking_return_tolerance,
        ),
        reconciliation_maximum_blocking_ratio=_number(
            scalar,
            "reconciliation_maximum_blocking_ratio",
            settings.market_data_reconciliation_maximum_blocking_ratio,
        ),
        reconciliation_minimum_overlap_sessions=_integer(
            scalar,
            "reconciliation_minimum_overlap_sessions",
            settings.market_data_reconciliation_minimum_overlap_sessions,
        ),
        reconciliation_preferred_overlap_sessions=_integer(
            scalar,
            "reconciliation_preferred_overlap_sessions",
            settings.market_data_reconciliation_preferred_overlap_sessions,
        ),
        nasdaq_23h_enabled=_boolean(scalar, "nasdaq_23h_enabled", settings.nasdaq_23h_enabled),
        nasdaq_23h_effective_date=_optional_date(scalar.get("nasdaq_23h_effective_date")),
        night_execution_enabled=_boolean(
            scalar, "night_execution_enabled", settings.night_execution_enabled
        ),
        default_execution_session=scalar.get("default_execution_session", "REGULAR").upper(),
        allow_calendar_fallback=_boolean(scalar, "allow_calendar_fallback", False),
        portfolio_id=_portfolio_key(scalar.get("portfolio_id")),
        broad_universe=BroadUniverseConfig(
            minimum_price=_number(scalar, "universe_minimum_price", 5.0),
            minimum_trading_sessions=_integer(scalar, "universe_minimum_trading_sessions", 252),
            minimum_average_dollar_volume=_number(
                scalar, "universe_minimum_average_dollar_volume", 10_000_000.0
            ),
            minimum_median_dollar_volume=_number(
                scalar, "universe_minimum_median_dollar_volume", 10_000_000.0
            ),
            minimum_valid_bar_coverage=_number(scalar, "universe_minimum_valid_bar_coverage", 0.98),
            maximum_missing_ratio=_number(scalar, "universe_maximum_missing_ratio", 0.02),
            include_adr=_boolean(scalar, "universe_include_adr", False),
            include_reit=_boolean(scalar, "universe_include_reit", False),
            require_pit_total_return=_boolean(
                scalar, "universe_require_pit_total_return", True
            ),
            minimum_operational_universe=_integer(
                scalar, "universe_minimum_operational_universe", 50
            ),
            coverage_collapse_ratio=_number(
                scalar, "universe_coverage_collapse_ratio", 0.5
            ),
            candidate_max=_integer(scalar, "universe_candidate_max", 100),
            candidate_min_alpha=_number(scalar, "universe_candidate_min_alpha", 0.0),
        ),
        stress_risk=StressRiskConfig(
            maximum_cvar_loss=_number(scalar, "stress_maximum_cvar_loss", 0.06),
            maximum_liquidation_days=_number(scalar, "stress_maximum_liquidation_days", 5.0),
            maximum_correlation_spike_loss=_number(
                scalar, "stress_maximum_correlation_spike_loss", 0.08
            ),
            maximum_gap_loss=_number(scalar, "stress_maximum_gap_loss", 0.08),
            maximum_stressed_volatility=_number(scalar, "stress_maximum_stressed_volatility", 0.30),
            maximum_benchmark_crash_loss=_number(
                scalar, "stress_maximum_benchmark_crash_loss", 0.25
            ),
            maximum_single_name_loss=_number(scalar, "stress_maximum_single_name_loss", 0.05),
            maximum_sector_loss=_number(scalar, "stress_maximum_sector_loss", 0.10),
            warning_ratio=_number(scalar, "stress_warning_ratio", 0.80),
        ),
        portfolio_constraints=PortfolioConstraints(
            maximum_holdings=_optional_integer(
                scalar, "portfolio_max_holdings", 10
            ),
            no_trade_band=_number(scalar, "no_trade_band", 0.005),
            minimum_rebalance_weight=_number(
                scalar, "minimum_rebalance_weight", 0.01
            ),
            minimum_trade_value=_number(scalar, "minimum_trade_value", 100.0),
        ),
        settings=settings,
        source_path=path.resolve(),
    )
    config = _apply_environment(config, environment)
    if cli_overrides:
        config = _apply_cli_overrides(config, cli_overrides)
    effective_settings = config.settings.model_copy(
        update={
            "market_data_timeout_seconds": config.timeout_seconds,
            "market_data_max_retries": config.max_retries,
            "market_data_retry_backoff_seconds": config.retry_backoff_seconds,
            "market_data_provider_cache_dir": config.cache_dir,
            "market_data_independent_provider_priority": ",".join(
                config.independent_provider_priority
            ),
            "market_data_reconciliation_minimum_coverage": config.reconciliation_minimum_coverage,
            "market_data_reconciliation_warning_return_tolerance": (
                config.reconciliation_warning_tolerance
            ),
            "market_data_reconciliation_blocking_return_tolerance": (
                config.reconciliation_blocking_tolerance
            ),
            "market_data_reconciliation_maximum_blocking_ratio": (
                config.reconciliation_maximum_blocking_ratio
            ),
            "market_data_reconciliation_minimum_overlap_sessions": (
                config.reconciliation_minimum_overlap_sessions
            ),
            "market_data_reconciliation_preferred_overlap_sessions": (
                config.reconciliation_preferred_overlap_sessions
            ),
            "nasdaq_23h_enabled": config.nasdaq_23h_enabled,
            "nasdaq_23h_effective_date": config.nasdaq_23h_effective_date,
            "night_execution_enabled": False,
            "daily_pipeline_report_path": config.report_dir / "DAILY_PIPELINE_REPORT.md",
        }
    )
    return replace(config, settings=effective_settings)


def effective_config_from_settings(settings: Settings) -> EffectiveRuntimeConfig:
    """Resolve legacy headless callers into the same canonical object immediately."""

    return EffectiveRuntimeConfig(
        cache_dir=settings.market_data_provider_cache_dir,
        report_dir=settings.daily_pipeline_report_path.parent,
        operational_policy_path=settings.operational_policy_path,
        independent_provider_priority=tuple(
            item.strip().lower()
            for item in settings.market_data_independent_provider_priority.split(",")
            if item.strip()
        ),
        timeout_seconds=settings.market_data_timeout_seconds,
        max_retries=settings.market_data_max_retries,
        retry_backoff_seconds=settings.market_data_retry_backoff_seconds,
        reconciliation_minimum_coverage=(settings.market_data_reconciliation_minimum_coverage),
        reconciliation_warning_tolerance=(
            settings.market_data_reconciliation_warning_return_tolerance
        ),
        reconciliation_blocking_tolerance=(
            settings.market_data_reconciliation_blocking_return_tolerance
        ),
        reconciliation_maximum_blocking_ratio=(
            settings.market_data_reconciliation_maximum_blocking_ratio
        ),
        reconciliation_minimum_overlap_sessions=(
            settings.market_data_reconciliation_minimum_overlap_sessions
        ),
        reconciliation_preferred_overlap_sessions=(
            settings.market_data_reconciliation_preferred_overlap_sessions
        ),
        nasdaq_23h_enabled=settings.nasdaq_23h_enabled,
        nasdaq_23h_effective_date=settings.nasdaq_23h_effective_date,
        night_execution_enabled=False,
        settings=settings,
    )


def _apply_environment(
    config: EffectiveRuntimeConfig, environment: Mapping[str, str]
) -> EffectiveRuntimeConfig:
    if "PAT_MARKET_DATA_TIMEOUT_SECONDS" in environment:
        config = replace(
            config,
            timeout_seconds=int(environment["PAT_MARKET_DATA_TIMEOUT_SECONDS"]),
        )
    if "PAT_MARKET_DATA_MAX_RETRIES" in environment:
        config = replace(config, max_retries=int(environment["PAT_MARKET_DATA_MAX_RETRIES"]))
    if "PAT_MARKET_DATA_RETRY_BACKOFF_SECONDS" in environment:
        config = replace(
            config,
            retry_backoff_seconds=float(environment["PAT_MARKET_DATA_RETRY_BACKOFF_SECONDS"]),
        )
    if "PAT_NASDAQ_23H_ENABLED" in environment:
        config = replace(
            config,
            nasdaq_23h_enabled=_parse_bool(environment["PAT_NASDAQ_23H_ENABLED"]),
        )
    if "PAT_NIGHT_EXECUTION_ENABLED" in environment:
        config = replace(
            config,
            night_execution_enabled=_parse_bool(environment["PAT_NIGHT_EXECUTION_ENABLED"]),
        )
    return config


def _apply_cli_overrides(
    config: EffectiveRuntimeConfig, overrides: Mapping[str, object]
) -> EffectiveRuntimeConfig:
    supported = {"portfolio_id", "report_dir", "cache_dir"}
    unknown = set(overrides) - supported
    if unknown:
        raise ValueError(f"unsupported CLI configuration override: {sorted(unknown)}")
    portfolio_id = overrides.get("portfolio_id")
    if portfolio_id is not None:
        if not isinstance(portfolio_id, (int, str)):
            raise ValueError("portfolio_id CLI override must be an integer or ledger name")
        if isinstance(portfolio_id, str) and not portfolio_id.strip():
            raise ValueError("portfolio_id CLI override must not be empty")
        config = replace(config, portfolio_id=portfolio_id)
    report_dir = overrides.get("report_dir")
    if report_dir is not None:
        config = replace(config, report_dir=Path(str(report_dir)))
    cache_dir = overrides.get("cache_dir")
    if cache_dir is not None:
        config = replace(config, cache_dir=Path(str(cache_dir)))
    return config


def _optional_text(scalar: dict[str, str], key: str) -> str | None:
    value = scalar.get(key)
    return value.strip() if value and value.strip() else None


def _optional_float_map(
    scalar: dict[str, str],
    momentum_key: str,
    trend_key: str,
    volatility_key: str,
) -> dict[str, float] | None:
    output: dict[str, float] = {}
    momentum = scalar.get(momentum_key)
    trend = scalar.get(trend_key)
    volatility = scalar.get(volatility_key)
    if momentum is not None:
        output["momentum_coefficient"] = float(momentum)
    if trend is not None:
        output["trend_coefficient"] = float(trend)
    if volatility is not None:
        output["low_volatility_coefficient"] = float(volatility)
    return output or None


def _portfolio_key(value: str | None) -> int | str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return int(normalized) if normalized.isdigit() else normalized


def _read_restricted_yaml(
    path: Path,
) -> tuple[dict[str, str], dict[str, tuple[str, ...]], dict[str, float]]:
    if not path.exists():
        raise FileNotFoundError(f"Configuration file is missing: {path}")
    scalar: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    holdings: dict[str, float] = {}
    active_list: str | None = None
    in_holdings = False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        content = raw.split("#", 1)[0].rstrip()
        if not content.strip():
            continue
        stripped = content.strip()
        if stripped.startswith("-"):
            if active_list is None:
                raise ValueError(f"{path}:{number}: list item has no list key")
            lists.setdefault(active_list, []).append(_text(stripped[1:]))
            continue
        if raw.startswith((" ", "\t")):
            if not in_holdings or ":" not in stripped:
                raise ValueError(f"{path}:{number}: unsupported indented configuration")
            key, value = (part.strip() for part in stripped.split(":", 1))
            holdings[key.upper()] = float(_text(value))
            continue
        if ":" not in stripped:
            raise ValueError(f"{path}:{number}: expected key: value")
        key, value = (part.strip() for part in stripped.split(":", 1))
        active_list = None
        in_holdings = key == "holdings"
        if not value:
            if key in {
                "symbols",
                "required_symbols",
                "provider_priority",
                "independent_provider_priority",
            }:
                active_list = key
            elif key != "holdings":
                raise ValueError(f"{path}:{number}: empty value is not supported")
            continue
        scalar[key] = _text(value)
    return scalar, {key: tuple(value) for key, value in lists.items()}, holdings


def _text(value: str) -> str:
    return value.strip().strip("\"'")


def _integer(values: Mapping[str, str], key: str, default: int) -> int:
    return int(values.get(key, str(default)))


def _optional_integer(
    values: Mapping[str, str], key: str, default: int | None
) -> int | None:
    if key not in values:
        return default
    normalized = values[key].strip().lower()
    if normalized in {"none", "null", "unlimited", ""}:
        return None
    return int(values[key])


def _number(values: Mapping[str, str], key: str, default: float) -> float:
    return float(values.get(key, str(default)))


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean: {value}")


def _boolean(values: Mapping[str, str], key: str, default: bool) -> bool:
    return _parse_bool(values.get(key, str(default)))


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def default_config_text() -> str:
    return """# Personal Alpha Terminal effective production configuration
market: US
benchmark: SPY
nasdaq_benchmark: QQQ
vix_symbol: ^VIX
history_start: 2015-01-01
cache_dir: data/cache
report_dir: reports
operational_policy_path: var/operational/operational_policy.json
primary_provider: yahoo
fallback_provider: stooq
provider_priority:
  - yahoo
  - stooq
independent_provider_priority:
  - twelve_data
  - alpha_vantage
  - stooq
timeout_seconds: 20
max_retries: 2
retry_backoff_seconds: 0.5
universe_minimum_price: 5.0
universe_minimum_trading_sessions: 252
universe_minimum_average_dollar_volume: 10000000
universe_minimum_median_dollar_volume: 10000000
universe_minimum_valid_bar_coverage: 0.98
universe_maximum_missing_ratio: 0.02
universe_include_adr: false
universe_include_reit: false
reconciliation_minimum_coverage: 0.95
reconciliation_warning_tolerance: 0.01
maximum_provider_difference: 0.05
reconciliation_maximum_blocking_ratio: 0.01
reconciliation_minimum_overlap_sessions: 20
reconciliation_preferred_overlap_sessions: 60
nasdaq_23h_enabled: false
night_execution_enabled: false
default_execution_session: REGULAR
allow_calendar_fallback: false
stress_maximum_cvar_loss: 0.06
portfolio_max_holdings: 10
stress_maximum_liquidation_days: 5.0
stress_maximum_correlation_spike_loss: 0.08
stress_maximum_gap_loss: 0.08
stress_maximum_stressed_volatility: 0.30
stress_maximum_benchmark_crash_loss: 0.25
stress_maximum_single_name_loss: 0.05
stress_maximum_sector_loss: 0.10
stress_warning_ratio: 0.80
"""


def user_config_text(root: Path) -> str:
    return (
        default_config_text()
        .replace("cache_dir: data/cache", f"cache_dir: {(root / 'cache').resolve().as_posix()}")
        .replace("report_dir: reports", f"report_dir: {(root / 'reports').resolve().as_posix()}")
    )
