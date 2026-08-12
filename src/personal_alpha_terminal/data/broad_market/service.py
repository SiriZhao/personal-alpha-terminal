"""Broad-market data registration, backfill, incremental sync and funnel reporting.

This service is the operational bridge between the current Nasdaq Trader symbol
directory (thousands of listed common stocks) and the certified PIT price rows
that feed the cross-sectional factor universe.  It never fabricates membership:
historical membership continues to require the separate survivorship-safe
research-data contract (``SURVIVORSHIP_LIMITED``), and the current-directory rows
are only ever used for ``as_of`` current analysis.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.data.broad_market.batch_provider import (
    BatchDownloadReport,
    YahooBatchStockProvider,
)
from personal_alpha_terminal.data.market_data.schemas import PriceBar
from personal_alpha_terminal.data.us_market.broad_universe import (
    BroadUniverseEligibility,
    CurrentSecurityMasterRecord,
    EligibilityRules,
    read_directory_snapshot,
)
from personal_alpha_terminal.models import Price, SecurityMaster, Stock, TradingStatus


class QuarantineReason:
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    INVALID_BARS = "INVALID_BARS"
    NO_DATA = "NO_DATA"


@dataclass(frozen=True, slots=True)
class RegistrationReport:
    decision_time: datetime
    directory_provider: str
    directory_hash: str
    directory_securities: int
    registered: int
    already_registered: int
    skipped: int
    skip_reasons: dict[str, int]
    registered_symbols: tuple[str, ...]

    def document(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BroadUniverseSyncResult:
    decision_time: datetime
    start_date: date
    end_date: date
    report: BatchDownloadReport
    inserted_rows: int
    updated_rows: int
    quarantined: dict[str, str]
    retried_from_quarantine: tuple[str, ...]
    total_registered: int

    def document(self) -> dict[str, object]:
        return {
            "decision_time": self.decision_time.isoformat(),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "requested": len(self.report.requested_symbols),
            "received": len(self.report.received_symbols),
            "failed": list(self.report.failed_symbols),
            "coverage": round(self.report.coverage, 6),
            "inserted_rows": self.inserted_rows,
            "updated_rows": self.updated_rows,
            "quarantined": self.quarantined,
            "retried_from_quarantine": list(self.retried_from_quarantine),
            "total_registered": self.total_registered,
        }


@dataclass(frozen=True, slots=True)
class FunnelLayer:
    name: str
    count: int
    excluded: int
    breakdown: dict[str, int]

    def document(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BroadUniverseFunnelReport:
    universe_date: date
    decision_time: datetime
    rules_fingerprint: str
    layers: tuple[FunnelLayer, ...]
    eligible_symbols: tuple[str, ...]
    pit_status: str
    survivorship_status: str
    directory_provider: str
    directory_hash: str
    price_based_data_eligible: int
    price_based_liquidity_eligible: int
    price_based_factor_eligible: int
    price_based_symbols: tuple[str, ...]
    price_based_pit_status: str
    qualification: str = "HISTORICAL_RESEARCH_PIT"
    quarantine_count: int = 0

    def document(self) -> dict[str, object]:
        return {
            "universe_date": self.universe_date.isoformat(),
            "decision_time": self.decision_time.isoformat(),
            "rules_fingerprint": self.rules_fingerprint,
            "layers": [layer.document() for layer in self.layers],
            "eligible_symbols": list(self.eligible_symbols),
            "pit_status": self.pit_status,
            "survivorship_status": self.survivorship_status,
            "directory_provider": self.directory_provider,
            "directory_hash": self.directory_hash,
            "price_based_data_eligible": self.price_based_data_eligible,
            "price_based_liquidity_eligible": self.price_based_liquidity_eligible,
            "price_based_factor_eligible": self.price_based_factor_eligible,
            "price_based_symbols": list(self.price_based_symbols),
            "price_based_pit_status": self.price_based_pit_status,
            "qualification": self.qualification,
            "quarantine_count": self.quarantine_count,
        }


class BroadUniverseDataService:
    """Register and maintain price history for the broad current US universe."""

    SOURCE = "yahoo_finance"
    PROVIDER = "yahoo_finance.broad_universe_batch"
    SNAPSHOT_SOURCE = "broad_universe"

    def __init__(
        self,
        session: Session,
        *,
        cache_root: Path,
        directory_root: Path | None = None,
        provider: YahooBatchStockProvider | None = None,
        rules: EligibilityRules | None = None,
        history_start: date | None = None,
        require_pit_total_return: bool | None = None,
    ) -> None:
        self.session = session
        self.cache_root = cache_root
        self.directory_root = directory_root or (cache_root / "us-current-directory")
        self.provider = provider or YahooBatchStockProvider()
        self.rules = rules or EligibilityRules()
        if require_pit_total_return is not None:
            self.rules = EligibilityRules(
                **{
                    **asdict(self.rules),
                    "require_pit_total_return": require_pit_total_return,
                }
            )
        self.history_start = history_start

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_current_directory(self, *, decision_time: datetime) -> RegistrationReport:
        if decision_time.tzinfo is None:
            raise ValueError("registration decision_time must be timezone-aware")
        snapshot = read_directory_snapshot(self.directory_root / "latest.json")
        candidates = tuple(
            record
            for record in snapshot.records
            if record.available_at <= decision_time
            and record.effective_date <= decision_time.date()
            and self._security_type_allowed(record)
            and record.exchange in self.rules.allowed_exchanges
            and not record.test_issue
        )
        existing = {
            (item.exchange, item.symbol): item
            for item in self.session.scalars(
                select(SecurityMaster).where(SecurityMaster.market == "US")
            )
        }
        registered = 0
        already = 0
        skip_reasons: dict[str, int] = {}
        now = datetime.now(UTC)
        added: list[str] = []
        for record in candidates:
            key = (record.exchange, record.symbol)
            if key in existing:
                already += 1
                continue
            canonical = f"US:{record.exchange}:{record.symbol}"
            conflict = next(
                (item for item in existing.values() if item.canonical_code == canonical),
                None,
            )
            if conflict is not None:
                skip_reasons["canonical_code_conflict"] = (
                    skip_reasons.get("canonical_code_conflict", 0) + 1
                )
                continue
            active_from = record.listing_date or record.active_from or decision_time.date()
            security = Stock(
                canonical_code=canonical,
                symbol=record.symbol,
                name=(record.company_name or record.symbol)[:256],
                market="US",
                exchange=record.exchange,
                asset_type="stock",
                currency=record.currency or "USD",
                timezone="America/New_York",
                list_date=active_from,
                delist_date=None,
                is_active=True,
                source=record.source,
                provider=snapshot.provider,
                available_time=decision_time,
                ingested_time=now,
            )
            self.session.add(security)
            existing[key] = security
            registered += 1
            added.append(record.symbol)
        self.session.flush()
        return RegistrationReport(
            decision_time=decision_time,
            directory_provider=snapshot.provider,
            directory_hash=snapshot.content_hash,
            directory_securities=len(snapshot.records),
            registered=registered,
            already_registered=already,
            skipped=len(candidates) - registered - already,
            skip_reasons=skip_reasons,
            registered_symbols=tuple(sorted(added)),
        )

    def _security_type_allowed(self, record: CurrentSecurityMasterRecord) -> bool:
        if not record.is_common_stock:
            return False
        if record.is_adr and not self.rules.include_adr:
            return False
        if record.is_reit and not self.rules.include_reit:
            return False
        if record.financial_status not in {"", "N", "NORMAL", "UNKNOWN"}:
            return False
        return True

    # ------------------------------------------------------------------
    # Data sync (backfill + incremental)
    # ------------------------------------------------------------------

    def backfill(
        self,
        *,
        start_date: date,
        end_date: date,
        decision_time: datetime,
        max_symbols: int | None = None,
    ) -> BroadUniverseSyncResult:
        symbols = self._registered_stock_symbols(limit=max_symbols)
        return self._sync(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            decision_time=decision_time,
        )

    def incremental_sync(
        self,
        *,
        end_date: date,
        decision_time: datetime,
        sessions_back: int = 10,
        max_symbols: int | None = None,
    ) -> BroadUniverseSyncResult:
        symbols = self._registered_stock_symbols(limit=max_symbols)
        start_date = self._earliest_required_start(end_date, sessions_back=sessions_back)
        return self._sync(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            decision_time=decision_time,
        )

    def sync_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        decision_time: datetime,
    ) -> BroadUniverseSyncResult:
        return self._sync(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            decision_time=decision_time,
        )

    def _sync(
        self,
        *,
        symbols: tuple[str, ...],
        start_date: date,
        end_date: date,
        decision_time: datetime,
    ) -> BroadUniverseSyncResult:
        if decision_time.tzinfo is None:
            raise ValueError("sync decision_time must be timezone-aware")
        stocks = {
            item.symbol: item
            for item in self.session.scalars(
                select(SecurityMaster).where(
                    SecurityMaster.market == "US",
                    SecurityMaster.symbol.in_(symbols),
                )
            )
        }
        target = tuple(sorted(stocks))
        quarantine = self._load_quarantine()
        retried = tuple(symbol for symbol in target if quarantine.pop(symbol, None) is not None)
        chunk_size = getattr(self.provider, "chunk_size", 100)
        chunks = [
            target[index : index + chunk_size]
            for index in range(0, len(target), chunk_size)
        ]
        received: set[str] = set()
        failed: set[str] = set()
        bar_count = 0
        inserted = 0
        updated = 0
        failed_map: dict[str, str] = {}
        for chunk in chunks:
            report = self.provider.download(
                chunk,
                start_date=start_date,
                end_date=end_date,
            )
            received.update(report.received_symbols)
            failed.update(report.failed_symbols)
            bar_count += report.bar_count
            if report.received_symbols:
                inserted_delta, updated_delta = self._bulk_upsert_bars(
                    stocks,
                    report=report,
                )
                inserted += inserted_delta
                updated += updated_delta
            chunk_failed = {
                symbol: QuarantineReason.DOWNLOAD_FAILED for symbol in report.failed_symbols
            }
            if chunk_failed:
                quarantine.update(chunk_failed)
                failed_map.update(chunk_failed)
            self._save_quarantine(quarantine)
            self.session.commit()
        report = BatchDownloadReport(
            requested_symbols=target,
            received_symbols=tuple(sorted(received)),
            failed_symbols=tuple(sorted(failed)),
            quarantined_symbols=(),
            bar_count=bar_count,
            chunk_count=len(chunks),
        )
        return BroadUniverseSyncResult(
            decision_time=decision_time,
            start_date=start_date,
            end_date=end_date,
            report=report,
            inserted_rows=inserted,
            updated_rows=updated,
            quarantined=dict(failed_map),
            retried_from_quarantine=retried,
            total_registered=len(target),
        )

    def _registered_stock_symbols(self, *, limit: int | None) -> tuple[str, ...]:
        symbols = tuple(
            self.session.scalars(
                select(SecurityMaster.symbol)
                .where(
                    SecurityMaster.market == "US",
                    SecurityMaster.asset_type == "stock",
                    SecurityMaster.is_active.is_(True),
                )
                .order_by(SecurityMaster.symbol)
            )
        )
        if limit is not None and limit > 0:
            symbols = symbols[:limit]
        return symbols

    def _earliest_required_start(self, end_date: date, *, sessions_back: int) -> date:
        if sessions_back <= 0:
            raise ValueError("sessions_back must be positive")
        # Conservative calendar back-off; exchange-calendar exactness is handled
        # by the eligibility layer, which only uses bars available at decision time.
        return end_date - timedelta(days=sessions_back * 2)

    def _bulk_upsert_bars(
        self,
        stocks: dict[str, SecurityMaster],
        *,
        report: BatchDownloadReport,
    ) -> tuple[int, int]:
        """Persist downloaded bars with a single bulk-insert pass per chunk.

        Uses a compiled INSERT ... ON CONFLICT DO NOTHING style statement so a
        one-time multi-million-row backfill does not go through per-row ORM
        round-trips.  Idempotency is preserved by the (stock_id, trade_date,
        source) unique constraint.
        """

        bars_by_symbol: dict[str, list[PriceBar]] = {}
        for bar in report.bars:
            bars_by_symbol.setdefault(bar.symbol, []).append(bar)
        inserted = 0
        updated = 0
        for symbol in report.received_symbols:
            stock = stocks.get(symbol)
            bars = bars_by_symbol.get(symbol)
            if stock is None or not bars:
                continue
            count = self._bulk_upsert_stock(stock, bars)
            inserted += count
        return inserted, updated

    def _bulk_upsert_stock(
        self,
        stock: SecurityMaster,
        bars: list[PriceBar],
    ) -> int:
        """Bulk upsert one stock's bars using INSERT ... ON CONFLICT DO NOTHING.

        The (stock_id, trade_date, source) unique constraint makes the insert
        idempotent for incremental runs; a changed bar for an existing date is
        deliberately not silently overwritten during backfill (historical rows
        are immutable once certified).  Returns the number of new rows.
        """

        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        statement = (
            sqlite_insert(Price)
            .values(
                [
                    {
                        "stock_id": stock.id,
                        "trade_date": bar.date,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "adjusted_close": bar.adjusted_close,
                        "forward_adjusted_close": bar.forward_adjusted_close,
                        "backward_adjusted_close": bar.backward_adjusted_close,
                        "volume": bar.volume,
                        "asset_type": bar.asset_type,
                        "volume_unit": bar.volume_unit,
                        "price_currency": bar.price_currency,
                        "share_unit": bar.share_unit,
                        "price_type": bar.price_type,
                        "data_contract_version": bar.data_contract_version,
                        "source": self.SOURCE,
                        "provider": self.PROVIDER,
                        "adjustment_method": bar.adjustment_method,
                        "event_time": bar.event_time,
                        "available_time": bar.available_time,
                        "open_tradable": bar.open_tradable,
                        "ingested_at": bar.ingested_time,
                    }
                    for bar in bars
                ]
            )
            .on_conflict_do_nothing(index_elements=["stock_id", "trade_date", "source"])
        )
        result = self.session.execute(statement)
        self._ensure_tradable(stock)
        rowcount = getattr(result, "rowcount", None)
        return int(rowcount) if isinstance(rowcount, int) and rowcount >= 0 else 0

    def _ensure_tradable(self, stock: SecurityMaster) -> None:
        """Record TRADABLE status once current operational price evidence exists.

        Broad CURRENT_OPERATIONAL_PIT members are not part of the strict
        certified research snapshot, but they must still satisfy the same
        current tradability gate before portfolio construction.
        """
        self.session.flush()
        latest = self.session.scalar(
            select(TradingStatus)
            .where(TradingStatus.stock_id == stock.id)
            .order_by(TradingStatus.effective_time.desc(), TradingStatus.id.desc())
            .limit(1)
        )
        if latest is not None and latest.status == "TRADABLE":
            return
        now = datetime.now(UTC)
        self.session.add(
            TradingStatus(
                stock_id=stock.id,
                status="TRADABLE",
                effective_time=now,
                available_time=now,
                ingested_time=now,
                reason="current operational price evidence; no known delisting record",
                source="broad_universe_sync",
                provider="broad_market_sync",
            )
        )

    # ------------------------------------------------------------------
    # Quarantine
    # ------------------------------------------------------------------

    def _quarantine_path(self) -> Path:
        return self.cache_root / "broad-universe" / "quarantine.json"

    def _load_quarantine(self) -> dict[str, str]:
        path = self._quarantine_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def _save_quarantine(self, quarantine: dict[str, str]) -> None:
        path = self._quarantine_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(dict(sorted(quarantine.items())), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def quarantine_status(self) -> dict[str, str]:
        return self._load_quarantine()

    # ------------------------------------------------------------------
    # Funnel
    # ------------------------------------------------------------------

    def funnel(
        self,
        *,
        universe_date: date,
        decision_time: datetime,
    ) -> BroadUniverseFunnelReport:
        from personal_alpha_terminal.application.broad_universe_service import (
            BroadUSUniverseService,
        )

        service = BroadUSUniverseService(
            self.session,
            cache_root=self.directory_root,
            rules=self.rules,
        )
        selection = service.select(
            universe_date=universe_date,
            decision_time=decision_time,
            reference_symbols=("SPY", "QQQ"),
        )
        price_based_selection = service.select(
            universe_date=universe_date,
            decision_time=decision_time,
            reference_symbols=("SPY", "QQQ"),
            require_pit_total_return=False,
        )
        eligibility = selection.eligibility
        price_eligibility = price_based_selection.eligibility
        return self._funnel_from_eligibility(
            eligibility,
            price_eligibility=price_eligibility,
            quarantine_count=len(service._load_quarantine()),
        )

    def _funnel_from_eligibility(
        self,
        eligibility: BroadUniverseEligibility,
        *,
        price_eligibility: BroadUniverseEligibility | None = None,
        quarantine_count: int = 0,
    ) -> BroadUniverseFunnelReport:
        layers: list[FunnelLayer] = []
        current = eligibility.raw_listed_securities
        layers.append(
            FunnelLayer(
                "listed_securities",
                current,
                eligibility.raw_listed_securities - current,
                {},
            )
        )
        equities = eligibility.raw_listed_equities
        layers.append(
            FunnelLayer(
                "listed_equities",
                equities,
                current - equities,
                {"non_equity": current - equities},
            )
        )
        current = len(eligibility.security_type_eligible)
        layers.append(
            FunnelLayer(
                "security_type_eligible",
                current,
                equities - current,
                self._breakdown(eligibility, equities - current, layer="security"),
            )
        )
        current = len(eligibility.data_eligible)
        data_excluded = len(eligibility.security_type_eligible) - current
        layers.append(
            FunnelLayer(
                "data_eligible",
                current,
                data_excluded,
                self._breakdown(eligibility, data_excluded, layer="data"),
            )
        )
        current = len(eligibility.liquidity_eligible)
        liquidity_excluded = len(eligibility.data_eligible) - current
        layers.append(
            FunnelLayer(
                "liquidity_eligible",
                current,
                liquidity_excluded,
                self._breakdown(
                    eligibility,
                    liquidity_excluded,
                    layer="liquidity",
                ),
            )
        )
        current = len(eligibility.factor_eligible)
        factor_excluded = len(eligibility.liquidity_eligible) - current
        layers.append(
            FunnelLayer(
                "factor_eligible",
                current,
                factor_excluded,
                self._breakdown(eligibility, factor_excluded, layer="factor"),
            )
        )
        layers.append(
            FunnelLayer(
                "signal_eligible",
                current,
                0,
                {},
            )
        )
        return BroadUniverseFunnelReport(
            universe_date=eligibility.universe_date,
            decision_time=eligibility.decision_time,
            rules_fingerprint=eligibility.rules_fingerprint,
            layers=tuple(layers),
            eligible_symbols=tuple(sorted(item.symbol for item in eligibility.factor_eligible)),
            pit_status=eligibility.pit_status,
            survivorship_status=eligibility.survivorship_status.value,
            directory_provider="current_directory",
            directory_hash=eligibility.snapshot_hash,
            price_based_data_eligible=(
                len(price_eligibility.data_eligible)
                if price_eligibility is not None
                else 0
            ),
            price_based_liquidity_eligible=(
                len(price_eligibility.liquidity_eligible)
                if price_eligibility is not None
                else 0
            ),
            price_based_factor_eligible=(
                len(price_eligibility.factor_eligible)
                if price_eligibility is not None
                else 0
            ),
            price_based_symbols=(
                tuple(sorted(item.symbol for item in price_eligibility.factor_eligible))
                if price_eligibility is not None
                else ()
            ),
            price_based_pit_status=(
                price_eligibility.pit_status if price_eligibility is not None else "UNAVAILABLE"
            ),
            qualification=eligibility.qualification.value,
            quarantine_count=quarantine_count,
        )

    @staticmethod
    def _breakdown(
        eligibility: BroadUniverseEligibility,
        total: int,
        *,
        layer: str,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        for reasons in eligibility.exclusions.values():
            for reason in reasons:
                counts[reason] = counts.get(reason, 0) + 1
        if layer == "security":
            security_reasons = {
                key: value
                for key, value in counts.items()
                if key.startswith(("TEST_", "UNSUPPORTED", "SECURITY_TYPE", "FINANCIAL"))
            }
            return security_reasons
        if layer == "data":
            return {
                key: value
                for key, value in counts.items()
                if key.startswith(
                    (
                        "PIT_",
                        "FUTURE",
                        "PRICE",
                        "INSUFFICIENT",
                        "VALID_",
                        "MISSING",
                        "CORPORATE",
                        "FEATURES",
                    )
                )
            }
        if layer == "liquidity":
            return {
                key: value for key, value in counts.items() if key.startswith(("ADV", "MEDIAN"))
            }
        return {}

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    def coverage(self) -> dict[str, object]:
        rows = self.session.execute(
            select(
                Price.stock_id,
                func.min(Price.trade_date),
                func.max(Price.trade_date),
                func.count(Price.id),
            )
            .where(Price.source == self.SOURCE)
            .group_by(Price.stock_id)
        )
        by_stock = {
            stock_id: (min_date, max_date, count) for stock_id, min_date, max_date, count in rows
        }
        stocks = {
            item.id: item
            for item in self.session.scalars(
                select(SecurityMaster).where(
                    SecurityMaster.market == "US",
                    SecurityMaster.asset_type == "stock",
                )
            )
        }
        symbol_rows = {
            stocks[stock_id].symbol: (min_date.isoformat(), max_date.isoformat(), count)
            for stock_id, (min_date, max_date, count) in by_stock.items()
            if stock_id in stocks
        }
        latest = max((item[1] for item in by_stock.values()), default=None)
        return {
            "registered_stocks": len(stocks),
            "stocks_with_prices": len(symbol_rows),
            "price_rows": sum(item[2] for item in by_stock.values()),
            "latest_price_date": latest.isoformat() if latest else None,
            "symbols": symbol_rows,
        }
