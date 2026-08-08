from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from time import perf_counter

import pandas as pd

from personal_alpha_terminal.terminal.cache import CacheLineage, DailyPriceCache
from personal_alpha_terminal.terminal.market_sessions import NEW_YORK, MarketSessionCalendar
from personal_alpha_terminal.terminal.providers import DataProvider, ProviderError, ProviderResult


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    provider: str
    status: str
    attempts: int
    successes: int
    failures: int
    latency_ms: float | None
    last_error: str | None
    rate_limited: bool = False

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0


@dataclass(slots=True)
class _ProviderCounter:
    attempts: int = 0
    successes: int = 0
    failures: int = 0
    latencies: list[float] | None = None
    last_error: str | None = None
    rate_limited: bool = False

    def __post_init__(self) -> None:
        if self.latencies is None:
            self.latencies = []


@dataclass(frozen=True, slots=True)
class MarketDataSyncResult:
    data: dict[str, tuple[pd.DataFrame, CacheLineage]]
    errors: dict[str, str]
    provider_health: tuple[ProviderHealth, ...]
    provider_disagreements: dict[str, float | None]
    used_cache: tuple[str, ...]
    degraded_symbols: tuple[str, ...]


class MarketDataService:
    """Multi-provider canonical market-data service for the daily terminal.

    Providers never reach the Quant Engine. A frame reaches callers only after
    provider-schema checks, canonical normalization and an atomic cache write.
    """

    def __init__(
        self,
        *,
        providers: tuple[DataProvider, ...],
        cache: DailyPriceCache,
        calendar: MarketSessionCalendar,
    ) -> None:
        if not providers:
            raise ValueError("MarketDataService requires at least one provider")
        self.providers = providers
        self.cache = cache
        self.calendar = calendar

    def sync(
        self,
        symbols: tuple[str, ...],
        *,
        start: date,
        end: date,
        refresh: bool,
    ) -> MarketDataSyncResult:
        data: dict[str, tuple[pd.DataFrame, CacheLineage]] = {}
        errors: dict[str, str] = {}
        disagreements: dict[str, float | None] = {}
        used_cache: list[str] = []
        degraded: list[str] = []
        counters: dict[str, _ProviderCounter] = {
            provider.name: _ProviderCounter() for provider in self.providers
        }

        for symbol in symbols:
            cached = self._load_cache(symbol, errors)
            selected: ProviderResult | None = None
            successful: list[ProviderResult] = []
            provider_errors: list[str] = []
            if refresh:
                incremental_start = (
                    self.cache.incremental_start(cached[0], start) if cached is not None else start
                )
                for provider in self.providers:
                    counter = counters[provider.name]
                    counter.attempts += 1
                    began = perf_counter()
                    try:
                        result = provider.fetch_daily(symbol, incremental_start, end)
                        self._validate_provider_frame(result)
                        successful.append(result)
                        counter.successes += 1
                        assert counter.latencies is not None
                        counter.latencies.append((perf_counter() - began) * 1000)
                        if selected is None:
                            selected = result
                    except (ProviderError, RuntimeError, ValueError) as error:
                        message = f"{provider.name}: {error}"
                        provider_errors.append(message)
                        counter.failures += 1
                        assert counter.latencies is not None
                        counter.latencies.append((perf_counter() - began) * 1000)
                        counter.last_error = str(error)
                        counter.rate_limited = (
                            "rate limit" in str(error).lower() or "429" in str(error)
                        )
                disagreements[symbol] = self._provider_disagreement(successful)
                if selected is not None:
                    canonical = self._canonicalize(selected)
                    canonical_result = ProviderResult(
                        symbol=selected.symbol,
                        frame=canonical,
                        provider=selected.provider,
                        endpoint=selected.endpoint,
                        requested_at=selected.requested_at,
                        completed_at=selected.completed_at,
                        adjustment_policy=selected.adjustment_policy,
                        content_hash=selected.content_hash,
                        exchange=selected.exchange,
                        asset_type=selected.asset_type,
                        verified_sources=tuple(item.provider for item in successful),
                        provider_disagreement=disagreements[symbol],
                    )
                    self.cache.merge_and_save(symbol, canonical_result)
                    cached = self._load_cache(symbol, errors)
                    if selected is not successful[0] or provider_errors:
                        degraded.append(symbol)
                elif cached is not None:
                    used_cache.append(symbol)
                    degraded.append(symbol)
                    errors[symbol] = (
                        "all live providers failed; using cached data subject to staleness checks: "
                        + "; ".join(provider_errors)
                    )
                else:
                    errors[symbol] = (
                        "all providers failed and no cache exists: "
                        + "; ".join(provider_errors)
                    )
            elif cached is not None:
                used_cache.append(symbol)

            if cached is not None:
                frame, lineage = cached
                canonical = self._canonicalize_cached(frame, lineage)
                data[symbol] = (canonical, lineage)
            elif symbol not in errors:
                errors[symbol] = "no canonical cache exists"

        health = tuple(
            self._health(name, values) for name, values in counters.items()
        )
        return MarketDataSyncResult(
            data,
            errors,
            health,
            disagreements,
            tuple(sorted(used_cache)),
            tuple(sorted(set(degraded))),
        )

    def _canonicalize(self, result: ProviderResult) -> pd.DataFrame:
        frame = result.frame.copy()
        dates = pd.to_datetime(frame["date"], errors="coerce")
        utc_values = [self.calendar.market_close_utc(item.date()) for item in dates]
        et_values = [item.astimezone(NEW_YORK) for item in utc_values]
        frame["symbol"] = result.symbol
        frame["exchange"] = result.exchange
        frame["asset_type"] = result.asset_type
        frame["timestamp_utc"] = pd.to_datetime(utc_values, utc=True)
        frame["timestamp_et"] = pd.to_datetime(et_values)
        frame["calendar_date"] = dates.dt.date
        frame["trade_date"] = dates.dt.date
        frame["session"] = "REGULAR"
        frame["market_structure_version"] = [
            self.calendar.structure_for_date(item.date()).value for item in dates
        ]
        if "adjusted_close" in frame and "adj_close" not in frame:
            frame["adj_close"] = frame["adjusted_close"]
        for column in ("bid", "ask", "mid", "spread"):
            if column not in frame:
                frame[column] = pd.NA
        frame["source"] = result.provider
        frame["retrieved_at"] = result.completed_at.astimezone(UTC)
        frame["data_age"] = [
            max(0.0, (result.completed_at - item).total_seconds())
            for item in utc_values
        ]
        frame["is_adjusted"] = False
        frame["quality_score"] = pd.NA
        return frame

    def _canonicalize_cached(
        self,
        frame: pd.DataFrame,
        lineage: CacheLineage,
    ) -> pd.DataFrame:
        canonical_required = {"timestamp_utc", "trade_date", "source"}
        if canonical_required.issubset(frame.columns) and not frame[
            list(canonical_required)
        ].isna().any().any():
            return frame
        synthetic_result = ProviderResult(
            symbol=lineage.symbol,
            frame=frame,
            provider=lineage.provider,
            endpoint=lineage.endpoint,
            requested_at=datetime.fromisoformat(lineage.requested_at),
            completed_at=datetime.fromisoformat(lineage.completed_at),
            adjustment_policy=lineage.adjustment_policy,
            content_hash=lineage.content_hash,
            verified_sources=lineage.verified_sources,
            provider_disagreement=lineage.provider_disagreement,
        )
        return self._canonicalize(synthetic_result)

    @staticmethod
    def _validate_provider_frame(result: ProviderResult) -> None:
        frame = result.frame
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(frame.columns)
        if missing or frame.empty:
            raise ProviderError(f"malformed provider result; missing={sorted(missing)}")
        if frame["date"].isna().any() or frame.duplicated("date").any():
            raise ProviderError("provider result has invalid or duplicate timestamps")
        prices = frame[["open", "high", "low", "close"]]
        if prices.isna().any().any() or (prices <= 0).any().any():
            raise ProviderError("provider result has null or non-positive OHLC")
        if (frame["high"] < prices[["open", "close", "low"]].max(axis=1)).any():
            raise ProviderError("provider result violates the OHLC high envelope")
        if (frame["low"] > prices[["open", "close", "high"]].min(axis=1)).any():
            raise ProviderError("provider result violates the OHLC low envelope")
        if frame["volume"].isna().any() or (frame["volume"] < 0).any():
            raise ProviderError("provider result has invalid volume")

    @staticmethod
    def _provider_disagreement(results: list[ProviderResult]) -> float | None:
        if len(results) < 2:
            return None
        left = results[0].frame.set_index("date")["close"].astype(float)
        differences: list[float] = []
        for result in results[1:]:
            right = result.frame.set_index("date")["close"].astype(float)
            aligned = pd.concat((left.rename("left"), right.rename("right")), axis=1).dropna()
            if aligned.empty:
                continue
            relative = ((aligned["left"] - aligned["right"]).abs() / aligned["left"]).tail(20)
            differences.append(float(relative.max()))
        return max(differences) if differences else None

    def _load_cache(
        self,
        symbol: str,
        errors: dict[str, str],
    ) -> tuple[pd.DataFrame, CacheLineage] | None:
        try:
            return self.cache.load(symbol)
        except RuntimeError as error:
            errors[symbol] = str(error)
            return None

    @staticmethod
    def _health(name: str, values: _ProviderCounter) -> ProviderHealth:
        attempts = values.attempts
        successes = values.successes
        failures = values.failures
        latencies = values.latencies or []
        if attempts == 0:
            status = "NOT_RUN"
        elif successes == attempts:
            status = "READY"
        elif successes:
            status = "DEGRADED"
        else:
            status = "UNAVAILABLE"
        return ProviderHealth(
            name,
            status,
            attempts,
            successes,
            failures,
            (sum(float(value) for value in latencies) / len(latencies) if latencies else None),
            values.last_error,
            values.rate_limited,
        )
