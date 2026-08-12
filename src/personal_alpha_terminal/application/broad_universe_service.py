"""Application service joining current listings to certified local PIT observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import median

from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.data.us_market.broad_universe import (
    BroadUniverseEligibility,
    CurrentDirectorySnapshot,
    CurrentSecurityMasterRecord,
    CurrentSecurityType,
    EligibilityRules,
    NasdaqTraderSymbolDirectoryAdapter,
    SecurityEligibilityObservation,
    current_snapshot_from_local_records,
    evaluate_broad_universe,
    read_directory_snapshot,
    write_directory_snapshot,
)
from personal_alpha_terminal.models import (
    ExchangeSession,
    PITTotalReturnVersion,
    Price,
    SecurityMaster,
)


@dataclass(frozen=True, slots=True)
class BroadUniverseSelection:
    directory: CurrentDirectorySnapshot
    eligibility: BroadUniverseEligibility
    alpha_securities: tuple[SecurityMaster, ...]
    reference_securities: tuple[SecurityMaster, ...]
    warnings: tuple[str, ...]

    def evidence(self) -> dict[str, object]:
        return {
            **self.eligibility.counts(),
            "universe_date": self.eligibility.universe_date.isoformat(),
            "directory_provider": self.directory.provider,
            "directory_version": self.directory.dataset_version,
            "directory_hash": self.directory.content_hash,
            "eligibility_hash": self.eligibility.snapshot_hash,
            "rules_fingerprint": self.eligibility.rules_fingerprint,
            "pit_status": self.eligibility.pit_status,
            "survivorship_status": self.eligibility.survivorship_status,
            "historical_use_allowed": self.directory.historical_use_allowed,
            "alpha_symbols": [item.symbol for item in self.alpha_securities],
            "reference_symbols": [item.symbol for item in self.reference_securities],
            "warnings": list(self.warnings),
        }


class BroadUSUniverseService:
    """Build a broad-current -> locally certifiable cross-sectional selection."""

    def __init__(
        self,
        session: Session,
        *,
        cache_root: Path,
        rules: EligibilityRules | None = None,
    ) -> None:
        self.session = session
        self.cache_root = cache_root
        self.rules = rules or EligibilityRules()

    def refresh_directory(
        self,
        *,
        retrieved_at: datetime | None = None,
        adapter: NasdaqTraderSymbolDirectoryAdapter | None = None,
    ) -> CurrentDirectorySnapshot:
        snapshot = (adapter or NasdaqTraderSymbolDirectoryAdapter()).fetch(
            retrieved_at=retrieved_at
        )
        write_directory_snapshot(snapshot, self.cache_root)
        return snapshot

    def select(
        self,
        *,
        universe_date: date,
        decision_time: datetime,
        reference_symbols: tuple[str, ...],
        require_pit_total_return: bool | None = None,
    ) -> BroadUniverseSelection:
        rules = self.rules
        if require_pit_total_return is not None:
            rules = EligibilityRules(
                **{
                    **asdict(self.rules),
                    "require_pit_total_return": require_pit_total_return,
                }
            )
        if decision_time.tzinfo is None:
            raise ValueError("broad universe decision_time must be timezone-aware")
        securities = tuple(
            self.session.scalars(
                select(SecurityMaster)
                .where(
                    SecurityMaster.market == "US",
                    SecurityMaster.available_time <= decision_time,
                )
                .order_by(SecurityMaster.canonical_code)
            )
        )
        directory, warnings = self._directory_or_fallback(securities, decision_time)
        stock_by_key = {
            (item.exchange, item.symbol): item for item in securities if item.asset_type == "stock"
        }
        directory_by_key = {(item.exchange, item.symbol): item for item in directory.records}
        observations: list[SecurityEligibilityObservation] = []
        for key, stock in stock_by_key.items():
            record = directory_by_key.get(key)
            if record is None:
                continue
            observation = self._observation(
                record,
                stock,
                universe_date=universe_date,
                decision_time=decision_time,
                rules=rules,
            )
            if observation is not None:
                observations.append(observation)
        quarantined_ids = frozenset(
            item.security_id
            for item in directory.records
            if item.symbol in self._load_quarantine()
        )
        eligibility = evaluate_broad_universe(
            directory,
            tuple(observations),
            universe_date=universe_date,
            decision_time=decision_time,
            rules=rules,
            quarantined=quarantined_ids,
        )
        eligible_keys = {(item.exchange, item.symbol) for item in eligibility.factor_eligible}
        alpha_securities = tuple(
            stock_by_key[key] for key in sorted(eligible_keys) if key in stock_by_key
        )
        requested_references = set(reference_symbols)
        references = tuple(
            item
            for item in securities
            if (
                item.asset_type == "etf"
                or (item.asset_type == "index" and item.symbol in requested_references)
            )
        )
        if not alpha_securities:
            warnings.append("FACTOR_ELIGIBLE_UNIVERSE_EMPTY")
        return BroadUniverseSelection(
            directory,
            eligibility,
            alpha_securities,
            references,
            tuple(dict.fromkeys(warnings)),
        )

    def _load_quarantine(self) -> dict[str, str]:
        """Read the batch-downloader quarantine store beside the broad cache."""
        path = self.cache_root.parent / "broad-universe" / "quarantine.json"
        if not path.exists():
            return {}
        try:
            payload = __import__("json").loads(path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError):
            return {}
        return {str(key): str(value) for key, value in payload.items()}

    def _directory_or_fallback(
        self,
        securities: tuple[SecurityMaster, ...],
        decision_time: datetime,
    ) -> tuple[CurrentDirectorySnapshot, list[str]]:
        latest = self.cache_root / "latest.json"
        if latest.exists():
            try:
                snapshot = read_directory_snapshot(latest)
                if snapshot.retrieved_at <= decision_time:
                    return snapshot, []
                warnings = ["CURRENT_DIRECTORY_NOT_YET_AVAILABLE_AT_DECISION_TIME"]
            except (KeyError, OSError, TypeError, ValueError):
                warnings = ["CURRENT_DIRECTORY_CACHE_INVALID"]
        else:
            warnings = ["CURRENT_DIRECTORY_METADATA_UNAVAILABLE"]
        local = tuple(
            self._local_record(item, decision_time)
            for item in securities
            if item.asset_type == "stock"
        )
        return current_snapshot_from_local_records(
            local,
            retrieved_at=decision_time,
        ), warnings + ["BROAD_UNIVERSE_DEGRADED_TO_LOCAL_CURRENT_MASTER"]

    def _observation(
        self,
        record: CurrentSecurityMasterRecord,
        stock: SecurityMaster,
        *,
        universe_date: date,
        decision_time: datetime,
        rules: EligibilityRules,
    ) -> SecurityEligibilityObservation | None:
        # Eligibility for the session uses data strictly before the universe date.
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
            return None
        unique_rows = {item.trade_date: item for item in rows}
        ordered = tuple(unique_rows[key] for key in sorted(unique_rows))
        expected_dates = tuple(
            self.session.scalars(
                select(distinct(ExchangeSession.session_date))
                .where(
                    ExchangeSession.session_date < universe_date,
                    ExchangeSession.is_open.is_(True),
                    ExchangeSession.available_time <= decision_time,
                )
                .order_by(ExchangeSession.session_date.desc())
                .limit(rules.minimum_trading_sessions)
            )
        )
        expected = len(expected_dates) or rules.minimum_trading_sessions
        expected_set = set(expected_dates)
        covered = (
            sum(item.trade_date in expected_set for item in ordered)
            if expected_set
            else len(ordered)
        )
        coverage = min(1.0, covered / expected)
        recent = ordered[-20:]
        dollar_volumes = tuple(
            float(item.close) * float(item.volume)
            for item in recent
            if item.volume is not None and float(item.volume) >= 0
        )
        version = self.session.scalar(
            select(PITTotalReturnVersion)
            .where(
                PITTotalReturnVersion.stock_id == stock.id,
                PITTotalReturnVersion.as_of_time <= decision_time,
                PITTotalReturnVersion.data_cutoff.is_not(None),
                PITTotalReturnVersion.data_cutoff <= decision_time,
                PITTotalReturnVersion.certification_status == "CERTIFIED",
            )
            .order_by(PITTotalReturnVersion.as_of_time.desc(), PITTotalReturnVersion.id.desc())
            .limit(1)
        )
        available_at = max(
            item.available_time for item in ordered if item.available_time is not None
        )
        if available_at.tzinfo is None:
            available_at = available_at.replace(tzinfo=UTC)
        return SecurityEligibilityObservation(
            security_id=record.security_id,
            symbol=record.symbol,
            as_of_date=ordered[-1].trade_date,
            available_at=available_at,
            latest_price=float(ordered[-1].close),
            observed_sessions=len(ordered),
            average_dollar_volume=(
                sum(dollar_volumes) / len(dollar_volumes) if dollar_volumes else None
            ),
            median_dollar_volume=(median(dollar_volumes) if dollar_volumes else None),
            valid_bar_coverage=coverage,
            missing_ratio=max(0.0, 1.0 - coverage),
            corporate_action_integrity=version is not None,
            feature_available=len(ordered) >= rules.minimum_trading_sessions,
        )

    @staticmethod
    def _local_record(
        stock: SecurityMaster,
        decision_time: datetime,
    ) -> CurrentSecurityMasterRecord:
        available = stock.available_time
        if available.tzinfo is None:
            available = available.replace(tzinfo=UTC)
        active_from = stock.list_date or available.date()
        return CurrentSecurityMasterRecord(
            security_id=stock.canonical_code,
            symbol=stock.symbol,
            company_name=stock.name,
            security_type=CurrentSecurityType.COMMON_STOCK,
            exchange=stock.exchange,
            currency=stock.currency,
            country="US",
            listing_date=stock.list_date,
            delisting_date=stock.delist_date,
            active_from=active_from,
            active_to=stock.delist_date,
            is_common_stock=True,
            is_etf=False,
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
            financial_status="UNKNOWN",
            source="LOCAL_CERTIFIED_DAILY_SNAPSHOT",
            effective_date=active_from,
            available_at=min(available, decision_time),
        )
