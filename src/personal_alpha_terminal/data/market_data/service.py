import json
import logging
import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from functools import partial
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.data.market_data.circuit_breaker import (
    ProviderCircuitBreaker,
    ProviderCircuitState,
)
from personal_alpha_terminal.data.market_data.contracts import (
    AssetPriceRequest,
    AssetType,
    ProviderCapability,
    ProviderRawBatch,
)
from personal_alpha_terminal.data.market_data.error_classification import (
    classify_provider_error,
)
from personal_alpha_terminal.data.market_data.exceptions import (
    DataQualityError,
    MarketDataError,
    ProviderDependencyError,
    ProviderRequestError,
    UnsupportedMarketError,
)
from personal_alpha_terminal.data.market_data.normalization import PriceNormalizer
from personal_alpha_terminal.data.market_data.policies import policy_for_market
from personal_alpha_terminal.data.market_data.ports import MarketDataProvider
from personal_alpha_terminal.data.market_data.quality import DataQualityChecker
from personal_alpha_terminal.data.market_data.repository import PriceRepository
from personal_alpha_terminal.data.market_data.schemas import (
    DailyUpdateReport,
    DataQualityResult,
    InstrumentUpdateResult,
    Market,
    PriceBar,
)
from personal_alpha_terminal.models import Stock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ProviderQualityResult:
    provider: MarketDataProvider
    quality: DataQualityResult


# ROUND24 PHASE G: backfill state machine.  Symbols with structurally
# insufficient history (e.g. new listings) must not be re-requested every
# day.  State is persisted beside the provider cache and is deterministic.
BACKFILL_STATE_FILE = "backfill_state.json"
FULL_BACKFILL_REQUIRED = "FULL_BACKFILL_REQUIRED"
STRUCTURALLY_INSUFFICIENT_HISTORY = "STRUCTURALLY_INSUFFICIENT_HISTORY"
NEW_LISTING_WAITING_FOR_HISTORY = "NEW_LISTING_WAITING_FOR_HISTORY"
PERMANENT_PROVIDER_NO_HISTORY = "PERMANENT_PROVIDER_NO_HISTORY"
RETRY_AFTER = "RETRY_AFTER"
QUARANTINED = "QUARANTINED"
NEW_LISTING_CALENDAR_DAYS = 380
PERMANENT_NO_HISTORY_ATTEMPTS = 3
RETRY_AFTER_DAYS = 3


def _load_backfill_state(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def _save_backfill_state(path: Path, state: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, sort_keys=True, indent=2, default=str),
        encoding="utf-8",
    )


def classify_backfill_decision(
    symbol: str,
    *,
    earliest: date | None,
    latest: date | None,
    required_history_start: date,
    end_date: date,
    listing_date: date | None,
    state: dict[str, dict[str, object]],
) -> tuple[str, date | None]:
    """Classify one symbol's refresh need with the ROUND24 state machine."""

    entry = state.get(symbol, {})
    current_state = str(entry.get("state", ""))
    retry_after_raw = entry.get("retry_after")
    retry_after: date | None = None
    if isinstance(retry_after_raw, str):
        try:
            retry_after = date.fromisoformat(retry_after_raw[:10])
        except ValueError:
            retry_after = None
    eligible_after_raw = entry.get("history_eligible_after")
    eligible_after: date | None = None
    if isinstance(eligible_after_raw, str):
        try:
            eligible_after = date.fromisoformat(eligible_after_raw[:10])
        except ValueError:
            eligible_after = None
    if current_state == PERMANENT_PROVIDER_NO_HISTORY:
        return PERMANENT_PROVIDER_NO_HISTORY, None
    if current_state == RETRY_AFTER and retry_after is not None and end_date < retry_after:
        return RETRY_AFTER, retry_after
    if listing_date is not None:
        listing_eligible_after = listing_date + timedelta(days=NEW_LISTING_CALENDAR_DAYS)
        if end_date < listing_eligible_after and (
            earliest is None or earliest > required_history_start
        ):
            return NEW_LISTING_WAITING_FOR_HISTORY, listing_eligible_after
    if current_state in {
        STRUCTURALLY_INSUFFICIENT_HISTORY,
        NEW_LISTING_WAITING_FOR_HISTORY,
    }:
        if eligible_after is not None and end_date < eligible_after:
            return current_state, eligible_after
    if earliest is None or latest is None or earliest > required_history_start:
        return FULL_BACKFILL_REQUIRED, None
    if latest >= end_date:
        return "CACHED_UP_TO_DATE", None
    gap_days = (end_date - latest).days
    refresh_class = "INCREMENTAL_ONE_SESSION" if gap_days <= 5 else "INCREMENTAL_GAP"
    return refresh_class, None


class MarketDataEngine:
    """Provider-independent interface for retrieval and incremental persistence."""

    def __init__(
        self,
        *,
        providers: Iterable[MarketDataProvider],
        repository: PriceRepository,
        settings: Settings,
        quality_checker: DataQualityChecker | None = None,
        normalizer: PriceNormalizer | None = None,
        sleep: Callable[[float], None] = time.sleep,
        circuit_breaker: ProviderCircuitBreaker | None = None,
        batch_provider: Any | None = None,
        batch_threshold: int = 200,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._quality_checker = quality_checker or DataQualityChecker()
        self._normalizer = normalizer or PriceNormalizer()
        self._sleep = sleep
        self._circuit = circuit_breaker or ProviderCircuitBreaker(
            settings.market_data_provider_cache_dir / "circuit-breaker"
        )
        self._provider_outcomes: dict[str, list[dict[str, object]]] = {}
        self._latencies: dict[str, list[float]] = {}
        self._batch_provider = batch_provider
        self._batch_threshold = max(1, batch_threshold)
        self._providers: dict[tuple[Market, AssetType], list[MarketDataProvider]] = {}

        for provider in providers:
            for capability in provider.capabilities:
                key = (capability.market, capability.asset_type)
                self._providers.setdefault(key, []).append(provider)

    def get_stock_price(
        self,
        symbol: str,
        market: Market,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        fetched = self._fetch_validated(
            symbol=symbol,
            market=market,
            asset_type="stock",
            price_currency=self._default_currency(market),
            start_date=start_date,
            end_date=end_date,
        )
        self._log_quality_issues(symbol, market, fetched.quality)
        return list(fetched.quality.bars)

    def get_market_index(
        self,
        symbol: str,
        market: Market,
        start_date: date,
        end_date: date,
    ) -> list[PriceBar]:
        fetched = self._fetch_validated(
            symbol=symbol,
            market=market,
            asset_type="index",
            price_currency=self._default_currency(market),
            start_date=start_date,
            end_date=end_date,
        )
        self._log_quality_issues(symbol, market, fetched.quality)
        return list(fetched.quality.bars)

    def update_daily_data(
        self,
        *,
        markets: set[Market] | None = None,
        symbols: set[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> DailyUpdateReport:
        if symbols and (not markets or len(markets) != 1):
            raise ValueError("A symbol filter requires exactly one market.")

        effective_end = end_date or date.today()
        if start_date is not None and start_date > effective_end:
            raise ValueError("start_date cannot be later than end_date.")
        stocks = self._repository.list_active_stocks(markets=markets, symbols=symbols)
        results: list[InstrumentUpdateResult] = []

        if (
            not symbols
            and sum(
                stock.market == "US" and stock.asset_type == "stock"
                for stock in stocks
            )
            > self._batch_threshold
            and self._batch_provider is not None
            and self._circuit.state(self._batch_provider.source)
            is not ProviderCircuitState.OPEN_CIRCUIT
        ):
            batch_stocks = [
                stock
                for stock in stocks
                if stock.market == "US" and stock.asset_type == "stock"
            ]
            remaining = [stock for stock in stocks if stock not in batch_stocks]
            batch_report = self._run_batch_refresh(
                batch_stocks,
                effective_end,
                forced_start_date=start_date,
                progress=progress,
            )
            remaining_results = tuple(
                self._update_stock(
                    stock,
                    effective_end,
                    forced_start_date=start_date,
                )
                for stock in remaining
            )
            return DailyUpdateReport(
                started_on=batch_report.started_on,
                results=(*batch_report.results, *remaining_results),
                batch_timings=batch_report.batch_timings,
            )

        if symbols:
            found = {stock.symbol for stock in stocks}
            market = next(iter(markets or set()))
            provider = self._provider_for(market, "stock")
            for missing in sorted(symbols - found):
                results.append(
                    InstrumentUpdateResult(
                        symbol=missing,
                        market=market,
                        source=provider.source,
                        status="failed",
                        start_date=(start_date or self._settings.market_data_default_start),
                        end_date=effective_end,
                        provider=provider.provider_id,
                        error="Instrument is not registered in the stocks table.",
                    )
                )

        for stock in stocks:
            results.append(
                self._update_stock(
                    stock,
                    effective_end,
                    forced_start_date=start_date,
                )
            )

        return DailyUpdateReport(
            started_on=date.today(),
            results=tuple(results),
        )

    def _run_batch_refresh(
        self,
        stocks: list[Any],
        end_date: date,
        *,
        forced_start_date: date | None,
        progress: Callable[[str], None] | None = None,
    ) -> DailyUpdateReport:
        """Batch-first incremental refresh for large universes.

        Each symbol is classified from real DB bounds: fully current caches are
        reused, symbols with historical depth but a missing recent session are
        refreshed only for the missing window, and only symbols without usable
        history enter a full backfill. Provider work is grouped by the same
        missing window so one batch serves many symbols.
        """
        from personal_alpha_terminal.data.market_data.schemas import InstrumentUpdateResult

        batch_provider = self._batch_provider
        assert batch_provider is not None
        chunk_size = int(getattr(batch_provider, "chunk_size", 100))
        requested = [item for item in stocks if item.symbol]
        planning_started = perf_counter()
        target = sorted(item.symbol for item in requested)
        stock_by_symbol = {item.symbol: item for item in requested}
        required_history_start = end_date - timedelta(
            days=self._settings.console_initial_history_days
        )
        backfill_state_path = (
            self._settings.market_data_provider_cache_dir.parent
            / "broad-universe"
            / BACKFILL_STATE_FILE
        )
        backfill_state = _load_backfill_state(backfill_state_path)
        state_changed = False
        decisions: dict[str, tuple[str, date, date]] = {}
        deferred_until: dict[str, tuple[str, date | None]] = {}
        # ROUND25 PHASE 13: one GROUP BY query instead of one
        # price_date_bounds roundtrip per symbol (N+1 elimination).
        bounds_by_id = self._repository.price_date_bounds_batch(
            (stock.id for stock in requested),
            batch_provider.source,
        )
        for symbol in target:
            stock = stock_by_symbol.get(symbol)
            if stock is None:
                continue
            earliest, latest = bounds_by_id.get(stock.id, (None, None))
            listing_date = getattr(stock, "list_date", None)
            refresh_class, eligible_after = classify_backfill_decision(
                symbol,
                earliest=earliest,
                latest=latest,
                required_history_start=required_history_start,
                end_date=end_date,
                listing_date=listing_date,
                state=backfill_state,
            )
            if refresh_class in {
                STRUCTURALLY_INSUFFICIENT_HISTORY,
                NEW_LISTING_WAITING_FOR_HISTORY,
                PERMANENT_PROVIDER_NO_HISTORY,
                RETRY_AFTER,
            }:
                deferred_until[symbol] = (refresh_class, eligible_after)
                decisions[symbol] = (refresh_class, required_history_start, end_date)
                entry = backfill_state.get(symbol, {})
                if eligible_after is not None:
                    new_entry = {
                        **entry,
                        "state": refresh_class,
                        "history_eligible_after": eligible_after.isoformat(),
                    }
                    if new_entry != entry:
                        backfill_state[symbol] = new_entry
                        state_changed = True
                continue
            if refresh_class == "CACHED_UP_TO_DATE":
                decisions[symbol] = ("CACHED_UP_TO_DATE", required_history_start, end_date)
            else:
                decisions[symbol] = (
                    refresh_class,
                    (latest + timedelta(days=1)) if latest is not None else required_history_start,
                    end_date,
                )
                if refresh_class == FULL_BACKFILL_REQUIRED:
                    backfill_state.pop(symbol, None)
                    state_changed = True

        results: list[InstrumentUpdateResult] = []
        for symbol, (refresh_class, _eligible_after) in sorted(
            deferred_until.items()
        ):
            results.append(
                InstrumentUpdateResult(
                    symbol=symbol,
                    market="US",
                    source=batch_provider.source,
                    provider=batch_provider.provider_id,
                    status="deferred",
                    start_date=required_history_start,
                    end_date=end_date,
                    error=refresh_class,
                    refresh_class=refresh_class,
                )
            )
        for symbol in sorted(target):
            refresh_class, request_start, request_end = decisions[symbol]
            if refresh_class == "CACHED_UP_TO_DATE":
                results.append(
                    InstrumentUpdateResult(
                        symbol=symbol,
                        market="US",
                        source=batch_provider.source,
                        provider=batch_provider.provider_id,
                        status="cached",
                        start_date=request_start,
                        end_date=request_end,
                        error="HISTORICAL_CACHE_REUSED_UP_TO_DATE",
                        refresh_class=refresh_class,
                    )
                )
        pending_by_window: dict[tuple[date, date], list[str]] = {}
        for symbol in sorted(target):
            refresh_class, request_start, request_end = decisions[symbol]
            if refresh_class not in {
                "CACHED_UP_TO_DATE",
                STRUCTURALLY_INSUFFICIENT_HISTORY,
                NEW_LISTING_WAITING_FOR_HISTORY,
                PERMANENT_PROVIDER_NO_HISTORY,
                RETRY_AFTER,
            }:
                pending_by_window.setdefault((request_start, request_end), []).append(symbol)
        planning_seconds = perf_counter() - planning_started
        if progress is not None:
            cached_count = sum(
                1
                for refresh_class, _, _ in decisions.values()
                if refresh_class == "CACHED_UP_TO_DATE"
            )
            progress(
                f"[\u5e02\u573a\u6570\u636e] \u68c0\u67e5\u7f13\u5b58 "
                f"{cached_count} / {len(target)}"
            )
        batch_timings: list[dict[str, object]] = [
            {
                "phase": "cache_status_planning",
                "symbol_count": len(target),
                "duration_seconds": round(planning_seconds, 4),
            }
        ]
        for (request_start, request_end), symbols in sorted(pending_by_window.items()):
            chunks = [
                symbols[index : index + chunk_size]
                for index in range(0, len(symbols), chunk_size)
            ]
            for chunk_index, chunk in enumerate(chunks, start=1):
                started = perf_counter()
                if progress is not None:
                    progress(
                        f"[Provider] \u6279\u6b21 {chunk_index} / {len(chunks)} "
                        f"{request_start} -> {request_end}"
                    )
                try:
                    report = batch_provider.download(
                        tuple(chunk),
                        start_date=request_start,
                        end_date=request_end,
                    )
                except Exception as exc:  # noqa: BLE001 - isolation boundary
                    structured = classify_provider_error(
                        batch_provider.source,
                        exc,
                        symbol=", ".join(chunk[:3]),
                        attempt=1,
                    )
                    self._record_outcome(
                        batch_provider.source,
                        structured.classification.value,
                        structured.sanitized_reason,
                    )
                    self._circuit.record_failure(
                        batch_provider.source,
                        structured.classification,
                        symbol=chunk[0] if chunk else "BATCH",
                    )
                    for symbol in chunk:
                        entry = backfill_state.get(symbol, {})
                        if decisions[symbol][0] in {FULL_BACKFILL_REQUIRED, "FULL_BACKFILL"}:
                            classification = structured.classification.value
                            if "RATE" in classification or "THROTTLE" in classification:
                                backfill_state[symbol] = {
                                    **entry,
                                    "state": RETRY_AFTER,
                                    "retry_after": (
                                        end_date + timedelta(days=RETRY_AFTER_DAYS)
                                    ).isoformat(),
                                }
                                state_changed = True
                        results.append(
                            InstrumentUpdateResult(
                                symbol=symbol,
                                market="US",
                                source=batch_provider.source,
                                provider=batch_provider.provider_id,
                                status="failed",
                                start_date=request_start,
                                end_date=request_end,
                                error=structured.classification.value,
                                refresh_class=decisions[symbol][0],
                            )
                        )
                    batch_timings.append(
                        {
                            "batch": chunk_index,
                            "symbol_count": len(chunk),
                            "start_date": request_start.isoformat(),
                            "end_date": request_end.isoformat(),
                            "duration_seconds": round(perf_counter() - started, 4),
                            "success": 0,
                            "failure": len(chunk),
                        }
                    )
                    continue
                self._circuit.record_success(batch_provider.source)
                self._record_outcome(batch_provider.source, "SUCCESS", None)
                received = set(report.received_symbols)
                failed = set(report.failed_symbols)
                success_in_batch = 0
                failure_in_batch = 0
                for symbol in chunk:
                    refresh_class = decisions[symbol][0]
                    stock = stock_by_symbol.get(symbol)
                    if stock is None or symbol not in received:
                        failure_in_batch += 1
                        entry = backfill_state.get(symbol, {})
                        attempts = int(str(entry.get("attempts", 0) or 0)) + 1
                        if attempts >= PERMANENT_NO_HISTORY_ATTEMPTS:
                            backfill_state[symbol] = {
                                **entry,
                                "state": PERMANENT_PROVIDER_NO_HISTORY,
                                "attempts": attempts,
                            }
                        else:
                            backfill_state[symbol] = {**entry, "attempts": attempts}
                        state_changed = True
                        results.append(
                            InstrumentUpdateResult(
                                symbol=symbol,
                                market="US",
                                source=batch_provider.source,
                                provider=batch_provider.provider_id,
                                status="no_data" if symbol not in failed else "failed",
                                start_date=request_start,
                                end_date=request_end,
                                error=(
                                    "SYMBOL_NOT_RECEIVED"
                                    if symbol not in failed
                                    else "NO_PRICE_HISTORY"
                                ),
                                refresh_class=refresh_class,
                            )
                        )
                        continue
                    batch_bars = [
                        bar for bar in report.bars if getattr(bar, "symbol", None) == symbol
                    ]
                    if not batch_bars:
                        failure_in_batch += 1
                        entry = backfill_state.get(symbol, {})
                        attempts = int(str(entry.get("attempts", 0) or 0)) + 1
                        if attempts >= PERMANENT_NO_HISTORY_ATTEMPTS:
                            backfill_state[symbol] = {
                                **entry,
                                "state": PERMANENT_PROVIDER_NO_HISTORY,
                                "attempts": attempts,
                            }
                        else:
                            backfill_state[symbol] = {**entry, "attempts": attempts}
                        state_changed = True
                        results.append(
                            InstrumentUpdateResult(
                                symbol=symbol,
                                market="US",
                                source=batch_provider.source,
                                provider=batch_provider.provider_id,
                                status="no_data",
                                start_date=request_start,
                                end_date=request_end,
                                error="NO_PRICE_HISTORY",
                                refresh_class=refresh_class,
                            )
                        )
                        continue
                    with self._repository.savepoint():
                        upsert = self._repository.upsert_bars(
                            stock=stock,
                            source=batch_provider.source,
                            provider=batch_provider.provider_id,
                            bars=batch_bars,
                        )
                    success_in_batch += 1
                    if symbol in backfill_state:
                        del backfill_state[symbol]
                        state_changed = True
                    results.append(
                        InstrumentUpdateResult(
                            symbol=symbol,
                            market="US",
                            source=batch_provider.source,
                            provider=batch_provider.provider_id,
                            status="success",
                            start_date=request_start,
                            end_date=request_end,
                            fetched_count=len(batch_bars),
                            inserted_count=upsert.inserted_count,
                            updated_count=upsert.updated_count,
                            error=refresh_class,
                            refresh_class=refresh_class,
                        )
                    )
                batch_timings.append(
                    {
                        "batch": chunk_index,
                        "symbol_count": len(chunk),
                        "start_date": request_start.isoformat(),
                        "end_date": request_end.isoformat(),
                        "duration_seconds": round(perf_counter() - started, 4),
                        "success": success_in_batch,
                        "failure": failure_in_batch,
                    }
                )
        if state_changed:
            _save_backfill_state(backfill_state_path, backfill_state)
        return DailyUpdateReport(
            started_on=date.today(),
            results=tuple(results),
            batch_timings=tuple(batch_timings),
        )

    def _update_stock(
        self,
        stock: Stock,
        end_date: date,
        *,
        forced_start_date: date | None,
    ) -> InstrumentUpdateResult:
        market = self._market_value(stock.market)
        asset_type = self._asset_type_value(stock.asset_type)
        providers = self._providers_for(market, asset_type)
        provider = providers[0]
        metadata_error = self._instrument_metadata_error(stock, market)
        if metadata_error is None and not any(
            self._provider_capability(item, market, asset_type).supported
            for item in providers
        ):
            metadata_error = (
                "Configured provider capabilities are not certified for "
                f"{market}/{asset_type}."
            )
        if metadata_error is not None:
            return InstrumentUpdateResult(
                symbol=stock.symbol,
                market=market,
                source=provider.source,
                provider=provider.provider_id,
                status="failed",
                start_date=(forced_start_date or self._settings.market_data_default_start),
                end_date=end_date,
                error=metadata_error,
            )
        latest_by_provider = {
            item.source: self._repository.latest_price_date(stock.id, item.source)
            for item in providers
        }
        latest_values = [item for item in latest_by_provider.values() if item is not None]
        latest = max(latest_values) if latest_values else None
        start_date = forced_start_date or self._incremental_start(latest)

        if start_date > end_date:
            return InstrumentUpdateResult(
                symbol=stock.symbol,
                market=market,
                source=provider.source,
                provider=provider.provider_id,
                status="no_data",
                start_date=start_date,
                end_date=end_date,
            )

        try:
            fetched = self._fetch_validated(
                symbol=stock.symbol,
                market=market,
                asset_type=asset_type,
                price_currency=stock.currency.strip().upper(),
                start_date=start_date,
                end_date=end_date,
            )
            selected_provider = fetched.provider
            quality_result = fetched.quality
            if not quality_result.bars:
                return InstrumentUpdateResult(
                    symbol=stock.symbol,
                    market=market,
                    source=selected_provider.source,
                    provider=selected_provider.provider_id,
                    status="no_data",
                    start_date=start_date,
                    end_date=end_date,
                    quality_issues=quality_result.issues,
                )

            with self._repository.savepoint():
                upsert = self._repository.upsert_bars(
                    stock=stock,
                    source=selected_provider.source,
                    provider=selected_provider.provider_id,
                    bars=quality_result.bars,
                )
            return InstrumentUpdateResult(
                symbol=stock.symbol,
                market=market,
                source=selected_provider.source,
                provider=selected_provider.provider_id,
                status="success",
                start_date=start_date,
                end_date=end_date,
                fetched_count=quality_result.input_count,
                valid_count=len(quality_result.bars),
                inserted_count=upsert.inserted_count,
                updated_count=upsert.updated_count,
                quality_issues=quality_result.issues,
            )
        except (MarketDataError, SQLAlchemyError, RuntimeError, ValueError) as exc:
            logger.error(
                "Daily update failed: market=%s symbol=%s error=%s",
                market,
                stock.symbol,
                exc,
            )
            cached_is_fresh = (
                latest is not None
                and (end_date - latest).days <= self._settings.console_data_stale_days
            )
            return InstrumentUpdateResult(
                symbol=stock.symbol,
                market=market,
                source=provider.source,
                provider=provider.provider_id,
                status="cached" if cached_is_fresh else "failed",
                start_date=start_date,
                end_date=end_date,
                error=(
                    f"live providers failed; retained cache through {latest}: {exc}"
                    if cached_is_fresh
                    else str(exc)
                ),
            )

    def _fetch_validated(
        self,
        *,
        symbol: str,
        market: Market,
        asset_type: AssetType,
        price_currency: str,
        start_date: date,
        end_date: date,
    ) -> _ProviderQualityResult:
        if start_date > end_date:
            raise ValueError("start_date cannot be later than end_date.")
        failures: list[str] = []
        for provider in self._providers_for(market, asset_type):
            capability = self._provider_capability(provider, market, asset_type)
            if not capability.supported:
                failures.append(f"{provider.source}: capability not certified")
                continue
            request = AssetPriceRequest(
                symbol=symbol,
                market=market,
                asset_type=asset_type,
                price_currency=price_currency,
                start_date=start_date,
                end_date=end_date,
            )
            try:
                raw_batch = self._request_with_retry(
                    partial(provider.fetch_raw, request),
                    provider=provider,
                    symbol=symbol,
                )
                bars = self._normalizer.normalize(raw_batch)
                result = self._quality_checker.validate(
                    bars,
                    expected_symbol=symbol,
                    expected_market=market,
                    expected_asset_type=asset_type,
                    expected_price_currency=price_currency,
                    expected_volume_unit=capability.volume_unit,
                    start_date=start_date,
                    end_date=end_date,
                    require_volume=capability.volume_unit != "none",
                )
                if result.has_errors:
                    raise DataQualityError(
                        f"{market}:{symbol} failed closed because {provider.source} "
                        "contains data-quality errors."
                    )
                if not result.bars:
                    raise ProviderRequestError(
                        f"{provider.source} returned no rows for {market}:{symbol}"
                    )
                return _ProviderQualityResult(provider, result)
            except (MarketDataError, RuntimeError, ValueError) as exc:
                failures.append(f"{provider.source}: {exc}")
                logger.warning(
                    "Provider fallback: market=%s asset=%s symbol=%s provider=%s error=%s",
                    market,
                    asset_type,
                    symbol,
                    provider.source,
                    exc,
                )
        raise ProviderRequestError(
            f"All providers failed for {market}/{asset_type}/{symbol}: "
            + "; ".join(failures)
        )

    def _request_with_retry(
        self,
        operation: Callable[[], ProviderRawBatch],
        *,
        provider: MarketDataProvider,
        symbol: str,
    ) -> ProviderRawBatch:
        attempts = self._settings.market_data_max_retries + 1
        for attempt in range(1, attempts + 1):
            started = time.perf_counter()
            try:
                result = operation()
                self._circuit.record_success(provider.source)
                self._latencies.setdefault(provider.source, []).append(
                    (time.perf_counter() - started) * 1000.0
                )
                self._record_outcome(provider.source, "SUCCESS", None)
                return result
            except ProviderDependencyError:
                raise
            except (MarketDataError, RuntimeError, ValueError) as exc:
                structured = classify_provider_error(
                    provider.source,
                    exc,
                    symbol=symbol,
                    attempt=attempt,
                )
                self._record_outcome(
                    provider.source, structured.classification.value, structured.sanitized_reason
                )
                self._circuit.record_failure(
                    provider.source,
                    structured.classification,
                    symbol=symbol,
                )
                logger.warning(
                    "Provider request failed: provider=%s symbol=%s attempt=%s/%s "
                    "classification=%s reason=%s",
                    provider.source,
                    symbol,
                    attempt,
                    attempts,
                    structured.classification.value,
                    structured.sanitized_reason,
                )
                if not structured.retryable:
                    raise ProviderRequestError(
                        f"{provider.source} failed for {symbol}: "
                        f"{structured.classification.value}"
                    ) from exc
                if attempt == attempts:
                    raise
                base_delay = self._settings.market_data_retry_backoff_seconds * (
                    2 ** (attempt - 1)
                )
                delay = base_delay + random.uniform(0.0, min(0.25, base_delay))
                self._sleep(delay)
        raise RuntimeError("Retry loop exited unexpectedly.")

    def _record_outcome(
        self, provider: str, classification: str, reason: str | None
    ) -> None:
        self._provider_outcomes.setdefault(provider, []).append(
            {
                "provider": provider,
                "classification": classification,
                "sanitized_reason": reason,
            }
        )

    def provider_health(self) -> dict[str, list[dict[str, object]]]:
        return {
            provider: list(outcomes)
            for provider, outcomes in sorted(self._provider_outcomes.items())
        }

    def circuit_state(self, provider: str) -> str:
        return self._circuit.state(provider).value

    def _incremental_start(self, latest: date | None) -> date:
        if latest is None:
            return self._settings.market_data_default_start
        overlap = self._settings.market_data_overlap_days
        candidate = latest + timedelta(days=1 - overlap)
        return max(candidate, self._settings.market_data_default_start)

    def _provider_for(self, market: Market, asset_type: AssetType) -> MarketDataProvider:
        return self._providers_for(market, asset_type)[0]

    def _providers_for(self, market: Market, asset_type: AssetType) -> list[MarketDataProvider]:
        available: list[MarketDataProvider] = []
        for provider in self._providers.get((market, asset_type), []):
            if self._circuit.state(provider.source) is ProviderCircuitState.OPEN_CIRCUIT:
                self._record_outcome(
                    provider.source,
                    "SKIPPED",
                    "provider circuit is OPEN_CIRCUIT; request suppressed",
                )
                continue
            available.append(provider)
        return available

    @staticmethod
    def _provider_capability(
        provider: MarketDataProvider,
        market: Market,
        asset_type: AssetType,
    ) -> ProviderCapability:
        return next(
            item
            for item in provider.capabilities
            if item.market == market and item.asset_type == asset_type
        )

    @staticmethod
    def _market_value(value: str) -> Market:
        if value == "A":
            return "A"
        if value == "HK":
            return "HK"
        if value == "US":
            return "US"
        raise UnsupportedMarketError(f"Unsupported stock market value: {value}.")

    @staticmethod
    def _asset_type_value(value: str) -> AssetType:
        if value in {"stock", "etf", "index", "bond"}:
            return value  # type: ignore[return-value]
        raise UnsupportedMarketError(
            f"Asset type {value!r} has no market-price schema or adapter."
        )

    @staticmethod
    def _default_currency(market: Market) -> str:
        return {"A": "CNY", "HK": "HKD", "US": "USD"}[market]

    @staticmethod
    def _instrument_metadata_error(stock: Stock, market: Market) -> str | None:
        policy = policy_for_market(market)
        if stock.asset_type not in {"stock", "etf", "index", "bond"}:
            return (
                f"Asset type {stock.asset_type!r} has no certified daily-price adapter; "
                "refusing to route it through a stock endpoint."
            )
        currency = stock.currency.strip().upper()
        if currency not in policy.allowed_currencies:
            allowed = ", ".join(sorted(policy.allowed_currencies))
            return (
                f"Instrument currency {currency!r} is incompatible with market {market}; "
                f"allowed currencies: {allowed}."
            )
        if stock.timezone != policy.timezone:
            return (
                f"Instrument timezone {stock.timezone!r} is incompatible with market {market}; "
                f"expected {policy.timezone!r}."
            )
        return None

    @staticmethod
    def _log_quality_issues(
        symbol: str,
        market: Market,
        result: DataQualityResult,
    ) -> None:
        for issue in result.issues:
            logger.warning(
                "Market-data quality issue: market=%s symbol=%s date=%s code=%s message=%s",
                market,
                symbol,
                issue.date,
                issue.code,
                issue.message,
            )
