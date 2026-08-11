from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from personal_alpha_terminal.application.universe import ResearchAsset
from personal_alpha_terminal.data.market_data.contracts import AssetPriceRequest
from personal_alpha_terminal.data.market_data.normalization import PriceNormalizer
from personal_alpha_terminal.data.market_data.providers.stooq import (
    StooqETFAdapter,
    StooqStockAdapter,
)


class ProviderFailureCategory(StrEnum):
    AUTH_NOT_CONFIGURED = "AUTH_NOT_CONFIGURED"
    AUTH_FAILED = "AUTH_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    API_INFORMATION = "API_INFORMATION"
    LATEST_SESSION_MISSING = "LATEST_SESSION_MISSING"


class IndependentProviderError(RuntimeError):
    def __init__(
        self,
        provider_id: str,
        category: ProviderFailureCategory,
        message: str,
        *,
        attempts: tuple[ProviderAttempt, ...] = (),
    ) -> None:
        self.provider_id = provider_id
        self.category = category
        self.attempts = attempts
        # Never include a request URL here: it contains the provider credential.
        super().__init__(f"{provider_id} {category.value}: {message}")


@dataclass(frozen=True, slots=True)
class ProviderAttempt:
    provider_id: str
    status: str
    failure_category: str | None
    reason: str
    configured: bool
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class IndependentFetchResult:
    provider_id: str
    prices: Mapping[date, float]
    retrieved_at: datetime
    latest_session: date
    content_hash: str
    cache_hit: bool
    attempts: tuple[ProviderAttempt, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider_id: str
    role: str
    asset_classes: tuple[str, ...]
    authentication_required: bool
    configured: bool
    reachable: str
    history_capability: str
    adjustment_convention: str
    timezone: str
    rate_limit_state: str
    last_success: str | None
    last_failure: str | None
    failure_category: str | None
    latest_session: str | None = None


HttpGetter = Callable[[str, int], tuple[int, Mapping[str, str], bytes]]


def _default_get(url: str, timeout: int) -> tuple[int, Mapping[str, str], bytes]:
    request = Request(url, headers={"User-Agent": "PersonalAlphaTerminal/1.1"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status), dict(response.headers.items()), response.read()
    except HTTPError as error:
        return int(error.code), dict(error.headers.items()), error.read()
    except TimeoutError as error:
        raise IndependentProviderError(
            "network", ProviderFailureCategory.TIMEOUT, "request timed out"
        ) from error
    except URLError as error:
        category = (
            ProviderFailureCategory.TIMEOUT
            if isinstance(error.reason, TimeoutError)
            else ProviderFailureCategory.PROVIDER_UNAVAILABLE
        )
        raise IndependentProviderError("network", category, "request failed") from error


class _JsonDailyProvider:
    provider_id = ""
    endpoint = ""
    environment_variable = ""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        timeout_seconds: int = 20,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        cache_dir: Path = Path("var/cache/providers/independent"),
        http_get: HttpGetter = _default_get,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else os.getenv(self.environment_variable, "")
        ).strip()
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.cache_dir = cache_dir / self.provider_id
        self.http_get = http_get

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def fetch(
        self,
        asset: ResearchAsset,
        start_date: date,
        end_date: date,
        *,
        expected_latest_session: date,
    ) -> IndependentFetchResult:
        if not self.configured:
            raise IndependentProviderError(
                self.provider_id,
                ProviderFailureCategory.AUTH_NOT_CONFIGURED,
                f"{self.environment_variable} is not configured",
            )
        cached = self._read_cache(asset.ticker, start_date, end_date, expected_latest_session)
        if cached is not None:
            return cached
        payload = self._request(asset.ticker, start_date, end_date)
        prices = self._parse(payload, asset.ticker, start_date, end_date)
        return self._finalize(asset.ticker, prices, expected_latest_session)

    def _request(self, symbol: str, start_date: date, end_date: date) -> Mapping[str, Any]:
        url = self._url(symbol, start_date, end_date)
        last: IndependentProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                status, _headers, body = self.http_get(url, self.timeout_seconds)
                if status in {401, 403}:
                    raise IndependentProviderError(
                        self.provider_id,
                        ProviderFailureCategory.AUTH_FAILED,
                        "authentication rejected",
                    )
                if status == 429:
                    raise IndependentProviderError(
                        self.provider_id, ProviderFailureCategory.RATE_LIMITED, "rate limit reached"
                    )
                if status >= 500:
                    raise IndependentProviderError(
                        self.provider_id,
                        ProviderFailureCategory.PROVIDER_UNAVAILABLE,
                        f"HTTP {status}",
                    )
                if status != 200:
                    raise IndependentProviderError(
                        self.provider_id,
                        ProviderFailureCategory.PROVIDER_UNAVAILABLE,
                        f"HTTP {status}",
                    )
                try:
                    decoded = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise IndependentProviderError(
                        self.provider_id,
                        ProviderFailureCategory.MALFORMED_RESPONSE,
                        "response is not valid JSON",
                    ) from error
                if not isinstance(decoded, dict):
                    raise IndependentProviderError(
                        self.provider_id,
                        ProviderFailureCategory.SCHEMA_MISMATCH,
                        "JSON root is not an object",
                    )
                return decoded
            except IndependentProviderError as error:
                if error.provider_id == "network":
                    error = IndependentProviderError(
                        self.provider_id, error.category, "request failed"
                    )
                last = error
                retryable = error.category in {
                    ProviderFailureCategory.TIMEOUT,
                    ProviderFailureCategory.PROVIDER_UNAVAILABLE,
                }
                if not retryable or attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_backoff_seconds * (2**attempt))
            except (TimeoutError, URLError) as error:
                last = IndependentProviderError(
                    self.provider_id,
                    ProviderFailureCategory.TIMEOUT,
                    "request timed out",
                )
                if attempt >= self.max_retries:
                    raise last from error
                time.sleep(self.retry_backoff_seconds * (2**attempt))
        assert last is not None
        raise last

    def _safe_message(self, value: object) -> str:
        message = str(value)[:160]
        return message.replace(self._api_key, "[REDACTED]") if self._api_key else message

    def _finalize(
        self, symbol: str, prices: Mapping[date, float], expected_latest_session: date
    ) -> IndependentFetchResult:
        if not prices:
            raise IndependentProviderError(
                self.provider_id, ProviderFailureCategory.EMPTY_RESPONSE, "no daily observations"
            )
        latest = max(prices)
        if latest != expected_latest_session:
            raise IndependentProviderError(
                self.provider_id,
                ProviderFailureCategory.LATEST_SESSION_MISSING,
                f"latest {latest.isoformat()} expected {expected_latest_session.isoformat()}",
            )
        retrieved_at = datetime.now(UTC)
        document = {
            "provider": self.provider_id,
            "symbol": symbol,
            "retrieved_at": retrieved_at.isoformat(),
            "as_of": expected_latest_session.isoformat(),
            "latest_session": latest.isoformat(),
            "row_count": len(prices),
            "prices": {key.isoformat(): prices[key] for key in sorted(prices)},
            "schema_version": "independent-daily-close-v1",
        }
        content_hash = _stable_hash(document)
        document["hash"] = content_hash
        self._write_cache(symbol, document)
        return IndependentFetchResult(
            self.provider_id, dict(prices), retrieved_at, latest, content_hash, False
        )

    def _read_cache(
        self, symbol: str, start_date: date, end_date: date, expected_latest_session: date
    ) -> IndependentFetchResult | None:
        path = self._cache_path(symbol)
        if not path.exists():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            expected_hash = document.pop("hash")
            if _stable_hash(document) != expected_hash:
                return None
            latest = date.fromisoformat(str(document["latest_session"]))
            if latest != expected_latest_session:
                return None
            prices = {
                date.fromisoformat(key): float(value)
                for key, value in dict(document["prices"]).items()
                if start_date <= date.fromisoformat(key) <= end_date
            }
            if latest not in prices:
                return None
            return IndependentFetchResult(
                self.provider_id,
                prices,
                datetime.fromisoformat(str(document["retrieved_at"])),
                latest,
                str(expected_hash),
                True,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _write_cache(self, symbol: str, document: Mapping[str, Any]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(symbol)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _cache_path(self, symbol: str) -> Path:
        safe = "".join(character if character.isalnum() else "_" for character in symbol)
        return self.cache_dir / f"{safe}.json"

    def _url(self, symbol: str, start_date: date, end_date: date) -> str:
        raise NotImplementedError

    def _parse(
        self, payload: Mapping[str, Any], symbol: str, start_date: date, end_date: date
    ) -> Mapping[date, float]:
        raise NotImplementedError


class TwelveDataProvider(_JsonDailyProvider):
    provider_id = "twelve_data"
    endpoint = "https://api.twelvedata.com/time_series"
    environment_variable = "TWELVE_DATA_API_KEY"

    def _url(self, symbol: str, start_date: date, end_date: date) -> str:
        query = urlencode(
            {
                "symbol": symbol,
                "interval": "1day",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "outputsize": 5000,
                "format": "JSON",
                "apikey": self._api_key,
            }
        )
        return f"{self.endpoint}?{query}"

    def _parse(
        self, payload: Mapping[str, Any], symbol: str, start_date: date, end_date: date
    ) -> Mapping[date, float]:
        if payload.get("status") == "error" or "code" in payload and "values" not in payload:
            code = int(payload.get("code", 0) or 0)
            message = str(payload.get("message", "provider error"))
            category = (
                ProviderFailureCategory.AUTH_FAILED
                if code in {401, 403}
                else ProviderFailureCategory.RATE_LIMITED
                if code == 429
                else ProviderFailureCategory.INVALID_SYMBOL
                if code in {400, 404}
                else ProviderFailureCategory.PROVIDER_UNAVAILABLE
            )
            raise IndependentProviderError(
                self.provider_id, category, self._safe_message(message)
            )
        values = payload.get("values")
        if not isinstance(values, list):
            raise IndependentProviderError(
                self.provider_id, ProviderFailureCategory.SCHEMA_MISMATCH, "values is missing"
            )
        meta = payload.get("meta")
        returned_symbol = meta.get("symbol") if isinstance(meta, dict) else None
        if returned_symbol is not None and str(returned_symbol).upper() != symbol.upper():
            raise IndependentProviderError(
                self.provider_id,
                ProviderFailureCategory.SCHEMA_MISMATCH,
                "response symbol does not match request",
            )
        return _parse_values(self.provider_id, values, start_date, end_date)


class AlphaVantageProvider(_JsonDailyProvider):
    provider_id = "alpha_vantage"
    endpoint = "https://www.alphavantage.co/query"
    environment_variable = "ALPHA_VANTAGE_API_KEY"

    def _url(self, symbol: str, start_date: date, end_date: date) -> str:
        del start_date, end_date
        query = urlencode(
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": self._api_key,
            }
        )
        return f"{self.endpoint}?{query}"

    def _parse(
        self, payload: Mapping[str, Any], symbol: str, start_date: date, end_date: date
    ) -> Mapping[date, float]:
        if "Note" in payload:
            raise IndependentProviderError(
                self.provider_id, ProviderFailureCategory.RATE_LIMITED, "API Note returned"
            )
        if "Information" in payload:
            raise IndependentProviderError(
                self.provider_id,
                ProviderFailureCategory.API_INFORMATION,
                "API Information returned",
            )
        if "Error Message" in payload:
            raise IndependentProviderError(
                self.provider_id, ProviderFailureCategory.INVALID_SYMBOL, "invalid symbol"
            )
        series = payload.get("Time Series (Daily)")
        if not isinstance(series, dict):
            raise IndependentProviderError(
                self.provider_id,
                ProviderFailureCategory.SCHEMA_MISMATCH,
                "daily time series is missing",
            )
        meta = payload.get("Meta Data")
        returned_symbol = meta.get("2. Symbol") if isinstance(meta, dict) else None
        if returned_symbol is not None and str(returned_symbol).upper() != symbol.upper():
            raise IndependentProviderError(
                self.provider_id,
                ProviderFailureCategory.SCHEMA_MISMATCH,
                "response symbol does not match request",
            )
        rows = [
            {
                "datetime": observed,
                "close": values.get("4. close") if isinstance(values, dict) else None,
            }
            for observed, values in series.items()
        ]
        return _parse_values(self.provider_id, rows, start_date, end_date)


class IndependentProviderRouter:
    """Per-symbol independent-provider fallback, separate from primary ingestion."""

    def __init__(
        self,
        *,
        twelve: TwelveDataProvider,
        alpha: AlphaVantageProvider,
        timeout_seconds: int = 20,
        priority: tuple[str, ...] = ("twelve_data", "alpha_vantage", "stooq"),
    ) -> None:
        self.twelve = twelve
        self.alpha = alpha
        self.timeout_seconds = timeout_seconds
        self.priority = priority
        self._stooq_failure: tuple[str, str] | None = None

    def fetch(
        self,
        asset: ResearchAsset,
        start_date: date,
        end_date: date,
        *,
        expected_latest_session: date,
    ) -> IndependentFetchResult:
        attempts: list[ProviderAttempt] = []
        providers = {"twelve_data": self.twelve, "alpha_vantage": self.alpha}
        for provider_name in self.priority:
            if provider_name == "stooq":
                break
            provider = providers.get(provider_name)
            if provider is None:
                continue
            try:
                result = provider.fetch(
                    asset,
                    start_date,
                    end_date,
                    expected_latest_session=expected_latest_session,
                )
                attempts.append(
                    ProviderAttempt(
                        provider.provider_id,
                        "PASS",
                        None,
                        "daily close returned",
                        True,
                        result.cache_hit,
                    )
                )
                return IndependentFetchResult(
                    result.provider_id,
                    result.prices,
                    result.retrieved_at,
                    result.latest_session,
                    result.content_hash,
                    result.cache_hit,
                    tuple(attempts),
                )
            except IndependentProviderError as error:
                attempts.append(
                    ProviderAttempt(
                        provider.provider_id,
                        "UNAVAILABLE",
                        error.category.value,
                        str(error),
                        provider.configured,
                    )
                )
        if "stooq" not in self.priority:
            reason = "; ".join(
                f"{item.provider_id}={item.failure_category}" for item in attempts
            )
            raise IndependentProviderError(
                "independent_router",
                ProviderFailureCategory.PROVIDER_UNAVAILABLE,
                f"no US equity independent provider available ({reason})",
                attempts=tuple(attempts),
            )
        try:
            if self._stooq_failure is not None:
                category, reason = self._stooq_failure
                attempts.append(
                    ProviderAttempt("stooq", "UNAVAILABLE", category, reason, True)
                )
                raise IndependentProviderError(
                    "stooq", ProviderFailureCategory.PROVIDER_UNAVAILABLE, reason
                )
            prices = self._stooq(asset, start_date, end_date)
            latest = max(prices)
            if latest != expected_latest_session:
                raise IndependentProviderError(
                    "stooq",
                    ProviderFailureCategory.LATEST_SESSION_MISSING,
                    f"latest {latest.isoformat()} expected {expected_latest_session.isoformat()}",
                )
            attempts.append(
                ProviderAttempt(
                    "stooq", "PASS", None, "best-effort daily close returned", True
                )
            )
            document = {key.isoformat(): prices[key] for key in sorted(prices)}
            return IndependentFetchResult(
                "stooq",
                prices,
                datetime.now(UTC),
                latest,
                _stable_hash(document),
                False,
                tuple(attempts),
            )
        except Exception as error:
            category = (
                error.category.value
                if isinstance(error, IndependentProviderError)
                else ProviderFailureCategory.PROVIDER_UNAVAILABLE.value
            )
            if not attempts or attempts[-1].provider_id != "stooq":
                attempts.append(
                    ProviderAttempt("stooq", "UNAVAILABLE", category, str(error), True)
                )
            self._stooq_failure = (category, str(error))
        reason = "; ".join(f"{item.provider_id}={item.failure_category}" for item in attempts)
        raise IndependentProviderError(
            "independent_router",
            ProviderFailureCategory.PROVIDER_UNAVAILABLE,
            f"no US equity independent provider available ({reason})",
            attempts=tuple(attempts),
        )

    def health(self) -> tuple[ProviderHealth, ...]:
        return (
            _health(self.twelve, "independent_validation", ("stock", "etf")),
            _health(self.alpha, "independent_validation_fallback", ("stock", "etf")),
            ProviderHealth(
                "stooq",
                "best_effort",
                ("stock", "etf"),
                False,
                True,
                "UNKNOWN",
                "daily_history_best_effort",
                "raw_close",
                "exchange_local_date",
                "UNKNOWN",
                None,
                None,
                None,
            ),
            ProviderHealth(
                "cboe_global_indices",
                "official_vix_validation",
                ("index",),
                False,
                True,
                "UNKNOWN",
                "VIX_daily_history",
                "official_close",
                "exchange_local_date",
                "NOT_APPLICABLE",
                None,
                None,
                None,
            ),
        )

    def _stooq(self, asset: ResearchAsset, start_date: date, end_date: date) -> dict[date, float]:
        adapter = (
            StooqStockAdapter(timeout_seconds=self.timeout_seconds)
            if asset.asset_type == "stock"
            else StooqETFAdapter(timeout_seconds=self.timeout_seconds)
        )
        batch = adapter.fetch_raw(
            AssetPriceRequest(
                symbol=asset.ticker,
                market="US",
                asset_type=asset.asset_type,  # type: ignore[arg-type]
                price_currency="USD",
                start_date=start_date,
                end_date=end_date,
            )
        )
        return {item.date: float(item.close) for item in PriceNormalizer().normalize(batch)}


def build_independent_provider_router(
    *,
    cache_dir: Path,
    timeout_seconds: int,
    max_retries: int,
    retry_backoff_seconds: float,
    twelve_api_key: str | None = None,
    alpha_api_key: str | None = None,
    priority: tuple[str, ...] = ("twelve_data", "alpha_vantage", "stooq"),
) -> IndependentProviderRouter:
    return IndependentProviderRouter(
        twelve=TwelveDataProvider(
            api_key=twelve_api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            cache_dir=cache_dir / "independent",
        ),
        alpha=AlphaVantageProvider(
            api_key=alpha_api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            cache_dir=cache_dir / "independent",
        ),
        timeout_seconds=timeout_seconds,
        priority=priority,
    )


def _parse_values(
    provider_id: str, values: Sequence[object], start_date: date, end_date: date
) -> Mapping[date, float]:
    result: dict[date, float] = {}
    for raw in values:
        if not isinstance(raw, dict):
            raise IndependentProviderError(
                provider_id, ProviderFailureCategory.SCHEMA_MISMATCH, "daily row is not an object"
            )
        try:
            observed = date.fromisoformat(str(raw["datetime"]))
            close = float(raw["close"])
        except (KeyError, TypeError, ValueError) as error:
            raise IndependentProviderError(
                provider_id, ProviderFailureCategory.SCHEMA_MISMATCH, "daily row is malformed"
            ) from error
        if not isfinite(close) or close <= 0:
            raise IndependentProviderError(
                provider_id, ProviderFailureCategory.SCHEMA_MISMATCH, "daily close is invalid"
            )
        if start_date <= observed <= end_date:
            result[observed] = close
    return result


def _health(
    provider: _JsonDailyProvider, role: str, asset_classes: tuple[str, ...]
) -> ProviderHealth:
    last_success, latest_session = _latest_cache_metadata(provider)
    return ProviderHealth(
        provider.provider_id,
        role,
        asset_classes,
        True,
        provider.configured,
        "UNKNOWN" if provider.configured else "NOT_CONFIGURED",
        "recent_daily_history",
        "raw_close",
        "exchange_local_date",
        "UNKNOWN",
        last_success,
        None,
        None,
        latest_session,
    )


def _latest_cache_metadata(
    provider: _JsonDailyProvider,
) -> tuple[str | None, str | None]:
    latest: tuple[str, str] | None = None
    try:
        paths = tuple(provider.cache_dir.glob("*.json"))
    except OSError:
        return None, None
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                continue
            expected_hash = document.pop("hash")
            if _stable_hash(document) != expected_hash:
                continue
            retrieved_at = str(document["retrieved_at"])
            latest_session = str(document["latest_session"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if latest is None or retrieved_at > latest[0]:
            latest = (retrieved_at, latest_session)
    return latest if latest is not None else (None, None)


def _stable_hash(document: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
