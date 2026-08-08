from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "VOO", "QQQM")
DEFAULT_REQUIRED_SYMBOLS = ("SPY", "QQQ", "^VIX")


@dataclass(frozen=True, slots=True)
class TerminalConfig:
    """Dependency-light configuration for the terminal-first daily workflow."""

    market: str = "US"
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS
    benchmark: str = "SPY"
    nasdaq_benchmark: str = "QQQ"
    vix_symbol: str = "^VIX"
    history_start: str = "2015-01-01"
    cache_dir: Path = Path("data/cache")
    report_dir: Path = Path("reports")
    primary_provider: str = "yahoo"
    fallback_provider: str = "stooq"
    provider_priority: tuple[str, ...] = ("yahoo", "stooq")
    timeout_seconds: int = 20
    max_retries: int = 2
    retry_backoff_seconds: float = 0.5
    data_safe_threshold: float = 80.0
    data_watch_threshold: float = 65.0
    maximum_provider_difference: float = 0.02
    nasdaq_23h_enabled: bool = False
    nasdaq_23h_effective_date: date | None = None
    night_execution_enabled: bool = False
    default_execution_session: str = "REGULAR"
    portfolio_id: int | None = None
    required_symbols: tuple[str, ...] = DEFAULT_REQUIRED_SYMBOLS
    holdings: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.market != "US":
            raise ValueError("the terminal daily product currently supports market=US only")
        if not self.provider_priority:
            raise ValueError("at least one provider must be configured")
        if not 0 <= self.data_watch_threshold <= self.data_safe_threshold <= 100:
            raise ValueError("data quality thresholds are invalid")
        if not 0 <= self.maximum_provider_difference <= 1:
            raise ValueError("maximum_provider_difference must be in [0, 1]")
        if self.night_execution_enabled:
            raise ValueError("night execution is not supported in this manual-execution release")


def default_config_text() -> str:
    return """# Personal Alpha Terminal terminal-first configuration
market: US
benchmark: SPY
nasdaq_benchmark: QQQ
vix_symbol: ^VIX
history_start: 2015-01-01
cache_dir: data/cache
report_dir: reports
primary_provider: yahoo
fallback_provider: stooq
provider_priority:
  - yahoo
  - stooq
timeout_seconds: 20
max_retries: 2
retry_backoff_seconds: 0.5
data_safe_threshold: 80
data_watch_threshold: 65
maximum_provider_difference: 0.02
nasdaq_23h_enabled: false
night_execution_enabled: false
default_execution_session: REGULAR
symbols:
  - AAPL
  - MSFT
  - NVDA
  - GOOGL
  - AMZN
  - VOO
  - QQQM
required_symbols:
  - SPY
  - QQQ
  - ^VIX
# Current real-account weights for analysis only. The application never submits broker orders.
holdings:
"""


def user_config_text(root: Path) -> str:
    """Create a first-run config whose writable paths live outside the release."""

    cache_dir = (root / "cache").resolve().as_posix()
    report_dir = (root / "reports").resolve().as_posix()
    return default_config_text().replace(
        "cache_dir: data/cache",
        f"cache_dir: {cache_dir}",
    ).replace(
        "report_dir: reports",
        f"report_dir: {report_dir}",
    )


def _scalar(value: str) -> str:
    return value.strip().strip("\"'")


def load_config(path: Path) -> TerminalConfig:
    """Read the documented restricted YAML subset without silent defaults."""

    if not path.exists():
        raise FileNotFoundError(f"Configuration file is missing: {path}")
    scalar_values: dict[str, str] = {}
    lists: dict[str, list[str]] = {}
    holdings: dict[str, float] = {}
    active_list: str | None = None
    in_holdings = False
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("-"):
            if active_list is None:
                raise ValueError(f"{path}:{number}: list item has no list key")
            lists.setdefault(active_list, []).append(_scalar(stripped[1:]))
            continue
        if raw.startswith((" ", "\t")):
            if not in_holdings or ":" not in stripped:
                raise ValueError(f"{path}:{number}: unsupported indented configuration")
            key, value = (part.strip() for part in stripped.split(":", 1))
            try:
                holdings[key.upper()] = float(_scalar(value))
            except ValueError as error:
                raise ValueError(f"{path}:{number}: holding weight must be numeric") from error
            continue
        if ":" not in stripped:
            raise ValueError(f"{path}:{number}: expected key: value")
        key, value = (part.strip() for part in stripped.split(":", 1))
        active_list = None
        in_holdings = key == "holdings"
        if not value:
            if key in {"symbols", "required_symbols", "provider_priority"}:
                active_list = key
            elif key != "holdings":
                raise ValueError(f"{path}:{number}: empty value is not supported")
            continue
        scalar_values[key] = _scalar(value)

    def as_int(key: str, default: int) -> int:
        try:
            return int(scalar_values.get(key, str(default)))
        except ValueError as error:
            raise ValueError(f"{path}: {key} must be an integer") from error

    def as_float(key: str, default: float) -> float:
        try:
            return float(scalar_values.get(key, str(default)))
        except ValueError as error:
            raise ValueError(f"{path}: {key} must be numeric") from error

    def as_bool(key: str, default: bool) -> bool:
        raw = scalar_values.get(key, str(default)).strip().lower()
        if raw in {"true", "1", "yes", "on"}:
            return True
        if raw in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"{path}: {key} must be true or false")

    def as_optional_date(key: str) -> date | None:
        raw = scalar_values.get(key, "").strip()
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError as error:
            raise ValueError(f"{path}: {key} must be YYYY-MM-DD") from error

    symbols = lists.get("symbols") or list(DEFAULT_SYMBOLS)
    required = lists.get("required_symbols") or list(DEFAULT_REQUIRED_SYMBOLS)
    priorities = lists.get("provider_priority") or [
        scalar_values.get("primary_provider", "yahoo"),
        scalar_values.get("fallback_provider", "stooq"),
    ]
    return TerminalConfig(
        market=scalar_values.get("market", "US").upper(),
        symbols=tuple(symbol.upper() for symbol in symbols),
        benchmark=scalar_values.get("benchmark", "SPY").upper(),
        nasdaq_benchmark=scalar_values.get("nasdaq_benchmark", "QQQ").upper(),
        vix_symbol=scalar_values.get("vix_symbol", "^VIX").upper(),
        history_start=scalar_values.get("history_start", "2015-01-01"),
        cache_dir=Path(scalar_values.get("cache_dir", "data/cache")),
        report_dir=Path(scalar_values.get("report_dir", "reports")),
        primary_provider=scalar_values.get("primary_provider", "yahoo").lower(),
        fallback_provider=scalar_values.get("fallback_provider", "stooq").lower(),
        provider_priority=tuple(dict.fromkeys(item.lower() for item in priorities)),
        timeout_seconds=as_int("timeout_seconds", 20),
        max_retries=as_int("max_retries", 2),
        retry_backoff_seconds=as_float("retry_backoff_seconds", 0.5),
        data_safe_threshold=as_float("data_safe_threshold", 80.0),
        data_watch_threshold=as_float("data_watch_threshold", 65.0),
        maximum_provider_difference=as_float("maximum_provider_difference", 0.02),
        nasdaq_23h_enabled=as_bool("nasdaq_23h_enabled", False),
        nasdaq_23h_effective_date=as_optional_date("nasdaq_23h_effective_date"),
        night_execution_enabled=as_bool("night_execution_enabled", False),
        default_execution_session=scalar_values.get(
            "default_execution_session", "REGULAR"
        ).upper(),
        portfolio_id=(as_int("portfolio_id", 0) if "portfolio_id" in scalar_values else None),
        required_symbols=tuple(symbol.upper() for symbol in required),
        holdings=holdings,
    )
