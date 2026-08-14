"""ROUND24 ETF sleeve application service (C2, C8, K).

Joins the deterministic ETF catalog + symbol directory with PIT-visible
price observations, computes ETF sleeve factors, builds core/tactical
targets and composes the multi-sleeve risk view.  The equity path stays
untouched: this service never modifies Classical Champion outputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import median

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.us_market.broad_universe import (
    CurrentDirectorySnapshot,
    CurrentSecurityMasterRecord,
    SecurityEligibilityObservation,
    current_snapshot_from_local_records,
    latest_directory_snapshot_at,
    read_directory_snapshot,
)
from personal_alpha_terminal.data.us_market.etf_universe import (
    EtfEligibilityRules,
    EtfUniverseEligibility,
    evaluate_etf_universe,
)
from personal_alpha_terminal.instruments.catalog import default_catalog
from personal_alpha_terminal.models import Price, SecurityMaster
from personal_alpha_terminal.quant_engine.factors.etf_factors import (
    EtfFactorSnapshot,
    compute_etf_factors,
)
from personal_alpha_terminal.quant_engine.portfolio.etf_sleeves import (
    EtfSleeveConfig,
    build_etf_targets,
    compose_multi_sleeve,
)


@dataclass(frozen=True, slots=True)
class EtfSleeveOutcome:
    eligibility: EtfUniverseEligibility | None
    factors: tuple[dict[str, object], ...]
    core_targets: tuple[dict[str, object], ...]
    tactical_targets: tuple[dict[str, object], ...]
    composition: dict[str, object] | None
    warnings: tuple[str, ...] = ()

    def evidence(self) -> dict[str, object]:
        return {
            "counts": self.eligibility.counts() if self.eligibility else {},
            "symbols_by_sleeve": (
                self.eligibility.symbols_by_sleeve() if self.eligibility else {}
            ),
            "factors": list(self.factors),
            "core_targets": list(self.core_targets),
            "tactical_targets": list(self.tactical_targets),
            "composition": self.composition or {},
            "warnings": list(self.warnings),
        }


class EtfSleeveApplicationService:
    """Application boundary for the ETF sleeves inside the daily chain."""

    def __init__(
        self,
        session: Session,
        config: EffectiveRuntimeConfig,
        *,
        rules: EtfEligibilityRules | None = None,
        sleeve_config: EtfSleeveConfig | None = None,
    ) -> None:
        self.session = session
        self.config = config
        self.rules = rules or EtfEligibilityRules()
        self.sleeve_config = sleeve_config or EtfSleeveConfig()
        self.catalog = default_catalog()

    @property
    def directory_cache_root(self) -> Path:
        return self.config.cache_dir / "us-current-directory"

    def _directory(self, decision_time: datetime) -> CurrentDirectorySnapshot | None:
        root = self.directory_cache_root
        selected = latest_directory_snapshot_at(root, decision_time)
        if selected is not None:
            return selected
        latest = root / "latest.json"
        if latest.exists():
            try:
                return read_directory_snapshot(latest)
            except (KeyError, OSError, TypeError, ValueError):
                return None
        securities = tuple(
            self.session.scalars(
                select(SecurityMaster).where(
                    SecurityMaster.market == "US",
                    SecurityMaster.available_time <= decision_time,
                )
            )
        )
        local = tuple(
            self._local_record(item, decision_time)
            for item in securities
            if item.asset_type == "etf"
        )
        if not local:
            return None
        return current_snapshot_from_local_records(local, retrieved_at=decision_time)

    @staticmethod
    def _local_record(
        stock: SecurityMaster, decision_time: datetime
    ) -> CurrentSecurityMasterRecord:
        from personal_alpha_terminal.data.us_market.broad_universe import (
            CurrentSecurityType,
        )

        available = stock.available_time
        if available.tzinfo is None:
            available = available.replace(tzinfo=UTC)
        active_from = stock.list_date or available.date()
        return CurrentSecurityMasterRecord(
            security_id=stock.canonical_code,
            symbol=stock.symbol,
            company_name=stock.name,
            security_type=CurrentSecurityType.ETF,
            exchange=stock.exchange or "XNAS",
            currency="USD",
            country="US",
            listing_date=stock.list_date,
            delisting_date=stock.delist_date,
            active_from=active_from,
            active_to=None,
            is_common_stock=False,
            is_etf=True,
            is_adr=False,
            is_reit=False,
            is_preferred=False,
            is_warrant=False,
            is_unit=False,
            is_right=False,
            is_otc=False,
            sector=None,
            industry=None,
            test_issue=False,
            financial_status="N",
            source="LOCAL_ETF_MASTER",
            effective_date=active_from,
            available_at=available,
        )

    def _observations(
        self,
        securities: tuple[SecurityMaster, ...],
        directory: CurrentDirectorySnapshot,
        *,
        universe_date: date,
        decision_time: datetime,
    ) -> tuple[SecurityEligibilityObservation, ...]:
        observations: list[SecurityEligibilityObservation] = []
        rules = self.rules
        directory_by_symbol = {item.symbol: item for item in directory.records}
        for stock in securities:
            directory_record = directory_by_symbol.get(stock.symbol)
            observation_id = (
                directory_record.security_id
                if directory_record is not None
                else f"CATALOG:{stock.symbol}"
            )
            rows = tuple(
                self.session.scalars(
                    select(Price)
                    .where(
                        Price.stock_id == stock.id,
                        Price.price_type == "unadjusted_ohlcv",
                        Price.trade_date < universe_date,
                        Price.available_time.is_not(None),
                        Price.available_time <= decision_time,
                    )
                    .order_by(Price.trade_date.desc(), Price.id.desc())
                    .limit(max(300, rules.minimum_trading_sessions + 20))
                )
            )
            if not rows:
                continue
            unique_rows = {item.trade_date: item for item in rows}
            ordered = tuple(unique_rows[key] for key in sorted(unique_rows))
            recent = ordered[-20:]
            dollar_volumes = tuple(
                float(item.close) * float(item.volume)
                for item in recent
                if item.volume is not None and float(item.volume) >= 0
            )
            available_at = max(
                item.available_time for item in ordered if item.available_time is not None
            )
            if available_at is None:
                continue
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=UTC)
            observations.append(
                SecurityEligibilityObservation(
                    security_id=observation_id,
                    symbol=stock.symbol,
                    as_of_date=ordered[-1].trade_date,
                    available_at=available_at,
                    latest_price=float(ordered[-1].close),
                    observed_sessions=len(ordered),
                    average_dollar_volume=(
                        sum(dollar_volumes) / len(dollar_volumes)
                        if dollar_volumes
                        else None
                    ),
                    median_dollar_volume=median(dollar_volumes) if dollar_volumes else None,
                    valid_bar_coverage=1.0,
                    missing_ratio=0.0,
                    corporate_action_integrity=False,
                    feature_available=len(ordered) >= rules.minimum_trading_sessions,
                )
            )
        return tuple(observations)

    @staticmethod
    def _supplementary_catalog_records(
        catalog_symbols: tuple[str, ...],
        directory: CurrentDirectorySnapshot,
        *, 
        decision_time: datetime,
    ) -> tuple[CurrentSecurityMasterRecord, ...]:
        """Deterministic catalog rows for ETFs absent from the Nasdaq directory
        parse (e.g. NYSE Arca funds).  Classification stays catalog-driven."""

        from personal_alpha_terminal.data.us_market.broad_universe import (
            CurrentSecurityMasterRecord,
            CurrentSecurityType,
        )

        directory_symbols = {item.symbol for item in directory.records}
        effective_date = max(
            (item.effective_date for item in directory.records),
            default=decision_time.date(),
        )
        records: list[CurrentSecurityMasterRecord] = []
        for symbol in catalog_symbols:
            if symbol in directory_symbols:
                continue
            records.append(
                CurrentSecurityMasterRecord(
                    security_id=f"CATALOG:{symbol}",
                    symbol=symbol,
                    company_name=str(symbol),
                    security_type=CurrentSecurityType.ETF,
                    exchange="XNAS",
                    currency="USD",
                    country="US",
                    listing_date=None,
                    delisting_date=None,
                    active_from=effective_date,
                    active_to=None,
                    is_common_stock=False,
                    is_etf=True,
                    is_adr=False,
                    is_reit=False,
                    is_preferred=False,
                    is_warrant=False,
                    is_unit=False,
                    is_right=False,
                    is_otc=False,
                    sector=None,
                    industry=None,
                    test_issue=False,
                    financial_status="N",
                    source="ROUND24_ETF_CATALOG",
                    effective_date=effective_date,
                    available_at=decision_time,
                )
            )
        return tuple(records)

    def select(
        self,
        *,
        universe_date: date,
        decision_time: datetime,
    ) -> tuple[EtfUniverseEligibility | None, tuple[str, ...]]:
        warnings: list[str] = []
        snapshot = self._directory(decision_time)
        if snapshot is None:
            warnings.append("ETF_DIRECTORY_UNAVAILABLE")
            return None, tuple(warnings)
        catalog_symbols = self.catalog.symbols()
        securities = tuple(
            self.session.scalars(
                select(SecurityMaster)
                .where(
                    SecurityMaster.market == "US",
                    SecurityMaster.asset_type == "etf",
                    SecurityMaster.symbol.in_(catalog_symbols),
                    SecurityMaster.available_time <= decision_time,
                )
            )
        )
        observations = self._observations(
            securities,
            snapshot,
            universe_date=universe_date,
            decision_time=decision_time,
        )
        supplementary = self._supplementary_catalog_records(
            catalog_symbols,
            snapshot,
            decision_time=decision_time,
        )
        eligibility = evaluate_etf_universe(
            snapshot,
            observations,
            self.catalog,
            supplementary_records=supplementary,
            universe_date=universe_date,
            decision_time=decision_time,
            rules=self.rules,
        )
        return eligibility, tuple(warnings)

    def run(
        self,
        *,
        universe_date: date,
        decision_time: datetime,
        equity_weights: dict[str, float],
        current_weights: dict[str, float],
        portfolio_value: float,
    ) -> EtfSleeveOutcome:
        warnings: list[str] = []
        eligibility, directory_warnings = self.select(
            universe_date=universe_date,
            decision_time=decision_time,
        )
        warnings.extend(directory_warnings)
        if eligibility is None:
            return EtfSleeveOutcome(
                eligibility=None,
                factors=(),
                core_targets=(),
                tactical_targets=(),
                composition=None,
                warnings=tuple(warnings),
            )
        tradable_symbols = tuple(
            item.symbol for item in eligibility.tradable_eligible
        )
        if not tradable_symbols:
            return EtfSleeveOutcome(
                eligibility=eligibility,
                factors=(),
                core_targets=(),
                tactical_targets=(),
                composition=None,
                warnings=tuple([*warnings, "NO_TRADABLE_ETFS"]),
            )
        benchmark_policy = {
            item.symbol: item.benchmark_policy
            for item in eligibility.tradable_eligible
        }
        rows = self.session.execute(
            select(
                SecurityMaster.symbol,
                Price.trade_date,
                Price.close,
                Price.volume,
            )
            .join(Price, Price.stock_id == SecurityMaster.id)
            .where(
                SecurityMaster.symbol.in_(tradable_symbols),
                Price.price_type == "unadjusted_ohlcv",
                Price.trade_date <= universe_date,
                Price.available_time <= decision_time,
            )
            .order_by(SecurityMaster.symbol, Price.trade_date)
        ).all()
        frame = pd.DataFrame(
            rows, columns=["symbol", "trade_date", "close", "volume"]
        )
        factors: tuple[EtfFactorSnapshot, ...] = ()
        if not frame.empty:
            factors = compute_etf_factors(
                frame,
                information_cutoff=decision_time,
                benchmark_symbol="SPY",
                benchmark_policy=benchmark_policy,
            )
        factor_docs = tuple(item.document() for item in factors)
        core_symbols = frozenset(item.symbol for item in eligibility.core_eligible)
        tactical_symbols = frozenset(
            item.symbol for item in eligibility.tactical_eligible
        )
        core_factors = tuple(
            item for item in factors if item.symbol in core_symbols
        )
        tactical_factors = tuple(
            item for item in factors if item.symbol in tactical_symbols
        )
        core_targets = build_etf_targets(
            core_factors,
            sleeve="ETF_CORE",
            current_weights=current_weights,
            portfolio_value=portfolio_value,
            decision_time=decision_time,
            config=self.sleeve_config,
            benchmark_policy=benchmark_policy,
        )
        tactical_targets = build_etf_targets(
            tactical_factors,
            sleeve="ETF_TACTICAL",
            current_weights=current_weights,
            portfolio_value=portfolio_value,
            decision_time=decision_time,
            config=self.sleeve_config,
            benchmark_policy=benchmark_policy,
        )
        etf_weights = {
            item.symbol: item.target_weight
            for item in (*core_targets, *tactical_targets)
            if item.target_weight > 0
        }
        composition = None
        if etf_weights:
            returns_map: dict[str, pd.Series] = {}
            all_symbols = sorted(set(equity_weights) | set(etf_weights))
            all_rows = self.session.execute(
                select(
                    SecurityMaster.symbol,
                    Price.trade_date,
                    Price.close,
                )
                .join(Price, Price.stock_id == SecurityMaster.id)
                .where(
                    SecurityMaster.symbol.in_(all_symbols),
                    Price.price_type == "unadjusted_ohlcv",
                    Price.trade_date <= universe_date,
                    Price.available_time <= decision_time,
                )
                .order_by(SecurityMaster.symbol, Price.trade_date)
            ).all()
            if all_rows:
                all_frame = pd.DataFrame(
                    all_rows, columns=["symbol", "trade_date", "close"]
                )
                all_frame["close"] = pd.to_numeric(
                    all_frame["close"], errors="coerce"
                )
                for symbol in all_symbols:
                    series = (
                        all_frame[all_frame["symbol"] == symbol]
                        .set_index("trade_date")["close"]
                        .pct_change()
                        .tail(252)
                    )
                    if len(series) > 60:
                        returns_map[symbol] = series
            sector_proxy = {
                item.symbol: item.etf_category or "UNCLASSIFIED"
                for item in eligibility.tradable_eligible
            }
            composition = compose_multi_sleeve(
                equity_weights=equity_weights,
                etf_weights=etf_weights,
                returns=returns_map,
                portfolio_value=portfolio_value,
                config=self.sleeve_config,
                sector_proxy=sector_proxy,
            ).document()
        return EtfSleeveOutcome(
            eligibility=eligibility,
            factors=factor_docs,
            core_targets=tuple(item.document() for item in core_targets),
            tactical_targets=tuple(item.document() for item in tactical_targets),
            composition=composition,
            warnings=tuple(warnings),
        )
