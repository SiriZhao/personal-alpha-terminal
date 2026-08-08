from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from personal_alpha_terminal.quant_engine.data.fundamental_data import FundamentalObservation
from personal_alpha_terminal.quant_engine.data.market_data import (
    MacroObservation,
    MarketBar,
    MarketDataQuery,
    QuantMarketDataset,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)


class DataProvider(Protocol):
    """Provider-neutral port. Implementations may call APIs; strategies may not."""

    provider_id: str

    def get_market_data(self, query: MarketDataQuery) -> tuple[MarketBar, ...]: ...

    def get_fundamentals(
        self,
        permanent_security_id: str,
        start_date: date,
        end_date: date,
    ) -> tuple[FundamentalObservation, ...]: ...

    def get_macro_data(
        self,
        series: tuple[str, ...],
        start_date: date,
        end_date: date,
    ) -> tuple[MacroObservation, ...]: ...


class LocalResearchCache:
    """Small local SQLite cache for normalized, already-gated research payloads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quant_cache (
                    cache_key TEXT PRIMARY KEY,
                    data_version TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def get_market_bars(self, cache_key: str, data_version: str) -> tuple[MarketBar, ...] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM quant_cache WHERE cache_key=? AND data_version=?",
                (cache_key, data_version),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row[0]))
        if not isinstance(payload, list):
            raise ValueError("cached market payload is not a list")
        return tuple(_bar_from_json(item) for item in payload)

    def put_market_bars(
        self,
        cache_key: str,
        data_version: str,
        bars: tuple[MarketBar, ...],
        created_at: datetime,
    ) -> None:
        payload = json.dumps(
            [_bar_to_json(bar) for bar in bars],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO quant_cache(cache_key, data_version, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    data_version=excluded.data_version,
                    payload=excluded.payload,
                    created_at=excluded.created_at
                """,
                (cache_key, data_version, payload, created_at.isoformat()),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection


class DataPipeline:
    def __init__(
        self,
        provider: DataProvider,
        cache: LocalResearchCache,
        gate: ResearchDataGate | None = None,
    ) -> None:
        self.provider = provider
        self.cache = cache
        self.gate = gate or ResearchDataGate()

    def load_market_data(
        self,
        *,
        query: MarketDataQuery,
        request: ResearchDataRequest,
        evidence: ResearchDataEvidence,
    ) -> QuantMarketDataset:
        if (query.market, query.asset_type) != (request.market, request.asset_type):
            raise ValueError("query and ResearchDataRequest market/asset_type must match")
        if query.start_date != request.start_date or query.end_date != request.end_date:
            raise ValueError("query and ResearchDataRequest date ranges must match")
        if query.adjustment_mode != request.adjustment_mode:
            raise ValueError("query and ResearchDataRequest adjustment modes must match")
        authorization = self.gate.authorize(request, evidence)
        cache_key = _cache_key(query, self.provider.provider_id)
        cached = self.cache.get_market_bars(cache_key, evidence.data_version)
        if cached is not None:
            self._validate_market_bars(
                cached,
                query,
                request,
                evidence=evidence,
                provider_id=self.provider.provider_id,
            )
            return QuantMarketDataset(query, authorization, cached, evidence.data_version, True)

        bars = self.provider.get_market_data(query)
        self._validate_market_bars(
            bars,
            query,
            request,
            evidence=evidence,
            provider_id=self.provider.provider_id,
        )
        self.cache.put_market_bars(
            cache_key,
            evidence.data_version,
            bars,
            request.decision_time,
        )
        return QuantMarketDataset(query, authorization, bars, evidence.data_version, False)

    @staticmethod
    def _validate_market_bars(
        bars: tuple[MarketBar, ...],
        query: MarketDataQuery,
        request: ResearchDataRequest,
        *,
        evidence: ResearchDataEvidence,
        provider_id: str,
    ) -> None:
        if not bars:
            raise ValueError("provider returned no market bars")
        dates: set[date] = set()
        previous: date | None = None
        for bar in bars:
            if bar.permanent_security_id != query.permanent_security_id:
                raise ValueError("provider returned the wrong permanent security")
            if bar.ticker != query.ticker:
                raise ValueError("provider returned the wrong ticker mapping")
            if bar.currency != query.currency or bar.adjustment_mode != query.adjustment_mode:
                raise ValueError("provider returned a currency/adjustment contract mismatch")
            if bar.provider != provider_id or bar.provider != evidence.provider:
                raise ValueError("provider lineage does not match certified evidence")
            if bar.source != evidence.source:
                raise ValueError("source lineage does not match certified evidence")
            if not query.start_date <= bar.trade_date <= query.end_date:
                raise ValueError("provider returned a bar outside the requested date range")
            if bar.available_time > request.decision_time:
                raise ValueError("provider returned future-available market data")
            if (
                request.purpose is ResearchPurpose.BACKTEST
                and query.adjustment_mode == "point_in_time_total_return"
                and bar.adjusted_close is None
            ):
                raise ValueError("PIT total-return backtests require adjusted_close")
            if bar.trade_date in dates or (previous is not None and bar.trade_date < previous):
                raise ValueError("provider returned duplicate or unsorted market bars")
            dates.add(bar.trade_date)
            previous = bar.trade_date


def _cache_key(query: MarketDataQuery, provider_id: str) -> str:
    payload = json.dumps(asdict(query), default=str, sort_keys=True, separators=(",", ":"))
    return sha256(f"{provider_id}|{payload}".encode()).hexdigest()


def _bar_to_json(bar: MarketBar) -> dict[str, object]:
    return {
        "permanent_security_id": bar.permanent_security_id,
        "ticker": bar.ticker,
        "trade_date": bar.trade_date.isoformat(),
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "adjusted_close": str(bar.adjusted_close) if bar.adjusted_close is not None else None,
        "volume": str(bar.volume) if bar.volume is not None else None,
        "currency": bar.currency,
        "event_time": bar.event_time.isoformat(),
        "available_time": bar.available_time.isoformat(),
        "ingested_time": bar.ingested_time.isoformat(),
        "source": bar.source,
        "provider": bar.provider,
        "adjustment_mode": bar.adjustment_mode,
        "open_tradable": bar.open_tradable,
    }


def _bar_from_json(value: object) -> MarketBar:
    if not isinstance(value, dict):
        raise ValueError("cached market bar is not an object")
    return MarketBar(
        permanent_security_id=str(value["permanent_security_id"]),
        ticker=str(value["ticker"]),
        trade_date=date.fromisoformat(str(value["trade_date"])),
        open=Decimal(str(value["open"])),
        high=Decimal(str(value["high"])),
        low=Decimal(str(value["low"])),
        close=Decimal(str(value["close"])),
        adjusted_close=(
            Decimal(str(value["adjusted_close"]))
            if value.get("adjusted_close") is not None
            else None
        ),
        volume=Decimal(str(value["volume"])) if value.get("volume") is not None else None,
        currency=str(value["currency"]),
        event_time=datetime.fromisoformat(str(value["event_time"])),
        available_time=datetime.fromisoformat(str(value["available_time"])),
        ingested_time=datetime.fromisoformat(str(value["ingested_time"])),
        source=str(value["source"]),
        provider=str(value["provider"]),
        adjustment_mode=str(value["adjustment_mode"]),
        open_tradable=bool(value["open_tradable"]),
    )
