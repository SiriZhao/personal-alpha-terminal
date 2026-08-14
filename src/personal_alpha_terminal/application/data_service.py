from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal import __build_version__
from personal_alpha_terminal.application.broad_universe_service import (
    BroadUSUniverseService,
)
from personal_alpha_terminal.application.data_certification import (
    DailyDataCertification,
    DailyDataCertifier,
)
from personal_alpha_terminal.application.data_lineage_certification import (
    BarCoverageEvidence,
    DataLineageCertifier,
    EvidenceStatus,
    LineageEvidenceBundle,
    write_evidence,
)
from personal_alpha_terminal.application.status import DataStatus, StatusDetail
from personal_alpha_terminal.application.universe import (
    MINIMUM_US_RESEARCH_UNIVERSE,
    ResearchAsset,
)
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.market_time import normalize_utc
from personal_alpha_terminal.core.runtime_bootstrap import application_data_dir
from personal_alpha_terminal.data.market_data.factory import build_market_data_engine
from personal_alpha_terminal.data.market_data.schemas import DailyUpdateReport
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment
from personal_alpha_terminal.data.us_market.pit_total_return import (
    PITCorporateAction,
    PITRawBar,
    PointInTimeTotalReturnBuilder,
)
from personal_alpha_terminal.data.us_market.repository import USPointInTimeRepository
from personal_alpha_terminal.models import (
    CorporateAction,
    DataSnapshotManifest,
    DelistingHistory,
    ExchangeSession,
    MarketDataQualityRun,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    ResearchDataCertification,
    Stock,
    TradingStatus,
)

LOGGER = logging.getLogger(__name__)


class SyncRunner(Protocol):
    def __call__(self, session: Session, start_date: date, end_date: date) -> DailyUpdateReport: ...


class LineageRunner(Protocol):
    def __call__(
        self,
        session: Session,
        settings: Settings,
        start_date: date,
        end_date: date,
        decision_time: datetime,
    ) -> LineageEvidenceBundle: ...


@dataclass(frozen=True, slots=True)
class InitializationProgress:
    step: int
    total_steps: int
    label: str
    detail: str


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    snapshot_id: str
    status: str
    successful: int
    failed: int
    accepted_rows: int
    manifest_path: Path
    failed_symbols: tuple[str, ...]


class DataService:
    """Research-data orchestration without presentation-layer dependencies."""

    def __init__(
        self,
        session: Session,
        settings: Settings,
        *,
        snapshot_root: Path | None = None,
        sync_runner: SyncRunner | None = None,
        lineage_runner: LineageRunner | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._snapshot_root = snapshot_root or application_data_dir() / "data" / "snapshots"
        self._uses_default_sync_runner = sync_runner is None
        self._sync_runner = sync_runner or self._run_market_engine
        self._lineage_runner = lineage_runner

    def get_data_readiness(self, *, as_of: datetime | None = None) -> StatusDetail:
        now = as_of or datetime.now(UTC)
        count = self._session.scalar(select(func.count()).select_from(Price)) or 0
        latest = self._session.scalar(select(func.max(Price.trade_date)))
        manifest = self._session.scalar(
            select(DataSnapshotManifest).order_by(DataSnapshotManifest.completed_at.desc()).limit(1)
        )
        if count == 0:
            return StatusDetail.build(
                DataStatus.EMPTY,
                "行情未初始化",
                "数据库可用，但尚未导入可追溯行情。",
                "prices 表为空",
                "运行数据初始化",
            )
        if manifest is None:
            return StatusDetail.build(
                DataStatus.PARTIAL,
                "行情缺少快照",
                "已有价格记录，但缺少不可变来源清单。",
                "data_snapshot_manifests 为空",
                "重新同步并生成快照",
                allow_research=False,
            )
        age = (now.date() - latest).days if latest else 10_000
        if manifest.certification_result == "BLOCKED":
            return StatusDetail.build(
                DataStatus.PROVIDER_ERROR,
                "核心数据同步失败",
                "必需资产未通过质量检查；旧缓存只可查看。",
                ", ".join(manifest.failed_symbols) or "required asset failure",
                "重试失败资产或检查网络和 Provider",
            )
        if age > self._settings.console_data_stale_days:
            return StatusDetail.build(
                DataStatus.STALE,
                "行情已过期",
                f"最近行情日期为 {latest}，禁止生成新候选。",
                f"latest_price_age_days={age}",
                "运行增量同步",
                allow_research=True,
            )
        status = (
            DataStatus.CERTIFIED
            if manifest.certification_result == "CERTIFIED"
            else DataStatus.PARTIAL
        )
        return StatusDetail.build(
            status,
            "研究数据已认证" if status is DataStatus.CERTIFIED else "研究数据部分可用",
            "免费源数据已通过本地价格合同；组合决策仍受 PIT 门禁约束。",
            f"snapshot={manifest.snapshot_id}; quality={manifest.quality_status}",
            "查看数据快照和严格研究门禁详情",
            allow_research=True,
            allow_candidates=False,
            updated_at=manifest.completed_at,
        )

    def initialize_research_database(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        progress: Callable[[InitializationProgress], None] | None = None,
    ) -> SyncOutcome:
        effective_end = end_date or date.today()
        effective_start = start_date or effective_end - timedelta(
            days=self._settings.console_initial_history_days
        )
        notify = progress or (lambda _item: None)
        notify(InitializationProgress(1, 6, "环境", "数据库事务与目录已准备"))
        self._register_minimum_universe()
        notify(InitializationProgress(2, 6, "证券主数据", "最小美股研究池已登记"))
        self._create_universe_snapshot(effective_end)
        notify(InitializationProgress(3, 6, "历史股票池", "当前时点快照已创建"))
        self._initialize_exchange_calendar(effective_start, effective_end)
        notify(InitializationProgress(4, 6, "交易日历", "美国交易日历已写入"))
        outcome = self.sync_market_data(start_date=effective_start, end_date=effective_end)
        notify(InitializationProgress(5, 6, "行情与质量", outcome.status))
        notify(InitializationProgress(6, 6, "完成", f"快照 {outcome.snapshot_id}"))
        return outcome

    def sync_market_data(
        self,
        *,
        start_date: date,
        end_date: date,
        progress: Callable[[str], None] | None = None,
    ) -> SyncOutcome:
        if self._uses_default_sync_runner:
            self._refresh_broad_current_directory()
        self._register_minimum_universe()
        self._create_universe_snapshot(end_date)
        calendar_start = min(
            start_date - timedelta(days=5),
            end_date - timedelta(days=self._settings.console_initial_history_days),
        )
        self._initialize_exchange_calendar(
            calendar_start,
            end_date + timedelta(days=5),
        )
        requested_at = datetime.now(UTC)
        self._active_progress = progress
        report = self._sync_runner(self._session, start_date, end_date)
        completed_at = datetime.now(UTC)
        return self._persist_manifest(report, requested_at, completed_at, start_date, end_date)

    def _refresh_broad_current_directory(self) -> None:
        """Refresh current listings once per UTC day without blocking price sync."""

        cache_root = self._settings.market_data_provider_cache_dir / "us-current-directory"
        latest = cache_root / "latest.json"
        if latest.exists():
            modified = datetime.fromtimestamp(latest.stat().st_mtime, tz=UTC)
            if modified.date() == datetime.now(UTC).date():
                return
        try:
            BroadUSUniverseService(
                self._session,
                cache_root=cache_root,
            ).refresh_directory()
        except TimeoutError:
            LOGGER.warning("broad-universe metadata provider temporarily unavailable: timeout")
        except OSError as exc:
            LOGGER.warning("broad-universe metadata provider unavailable: %s", exc)
        except ValueError as exc:
            LOGGER.warning("broad-universe metadata response rejected: %s", exc)

    def latest_manifest(self) -> DataSnapshotManifest | None:
        return self._session.scalar(
            select(DataSnapshotManifest).order_by(DataSnapshotManifest.completed_at.desc()).limit(1)
        )

    def daily_certification(
        self, *, analysis_date: date, decision_time: datetime
    ) -> DailyDataCertification:
        return DailyDataCertifier(self._session, self._settings).certify(
            analysis_date=analysis_date,
            decision_time=decision_time,
            manifest=self.latest_manifest(),
        )

    def refresh_start_date(self, *, analysis_date: date) -> date:
        """Use a full bootstrap window until every required asset has model history."""

        required = {
            item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if item.required
        }
        counts: dict[str, int] = {
            symbol: int(count)
            for symbol, count in self._session.execute(
                select(Stock.symbol, func.count(Price.id))
                .join(Price, Price.stock_id == Stock.id)
                .where(
                    Stock.market == "US",
                    Stock.symbol.in_(sorted(required)),
                    Price.trade_date <= analysis_date,
                    Price.price_type.in_(("unadjusted_ohlcv", "index_level_ohlcv")),
                )
                .group_by(Stock.symbol)
            ).all()
        }
        minimum_bars = max(
            126,
            min(504, int(self._settings.console_initial_history_days * 0.68)),
        )
        if any(int(counts.get(symbol, 0)) < minimum_bars for symbol in required):
            return analysis_date - timedelta(days=self._settings.console_initial_history_days)
        return analysis_date - timedelta(
            days=max(7, self._settings.market_data_overlap_days)
        )

    def _run_market_engine(
        self, session: Session, start_date: date, end_date: date
    ) -> DailyUpdateReport:
        return build_market_data_engine(session, self._settings).update_daily_data(
            markets={"US"},
            start_date=start_date,
            end_date=end_date,
            progress=getattr(self, "_active_progress", None),
        )

    def _register_minimum_universe(self) -> None:
        now = datetime.now(UTC)
        existing = {
            item.canonical_code: item
            for item in self._session.scalars(select(Stock).where(Stock.market == "US"))
        }
        for asset in MINIMUM_US_RESEARCH_UNIVERSE:
            if asset.canonical_code in existing:
                continue
            self._session.add(
                Stock(
                    canonical_code=asset.canonical_code,
                    symbol=asset.ticker,
                    name=asset.name,
                    market="US",
                    exchange=asset.exchange,
                    asset_type=asset.asset_type,
                    currency="USD",
                    timezone="America/New_York",
                    source="console_minimum_universe",
                    provider="application_config",
                    available_time=now,
                    ingested_time=now,
                )
            )
        self._session.flush()

    def _create_universe_snapshot(self, as_of_date: date) -> None:
        existing = self._session.scalar(
            select(MarketUniverseSnapshot).where(
                MarketUniverseSnapshot.market == "US",
                MarketUniverseSnapshot.as_of_date == as_of_date,
                MarketUniverseSnapshot.source == "console_minimum_universe",
            )
        )
        now = datetime.now(UTC)
        if existing is None:
            snapshot = MarketUniverseSnapshot(
                market="US",
                as_of_date=as_of_date,
                source="console_minimum_universe",
                provider="application_config",
                available_time=now,
                ingested_time=now,
            )
            self._session.add(snapshot)
            self._session.flush()
        else:
            snapshot = existing
        stocks = {
            item.symbol: item
            for item in self._session.scalars(select(Stock).where(Stock.market == "US"))
        }
        existing_stock_ids = set(
            self._session.scalars(
                select(MarketUniverseMember.stock_id).where(
                    MarketUniverseMember.snapshot_id == snapshot.id
                )
            )
        )
        for asset in MINIMUM_US_RESEARCH_UNIVERSE:
            stock = stocks[asset.ticker]
            if stock.id in existing_stock_ids:
                continue
            self._session.add(
                MarketUniverseMember(
                    snapshot_id=snapshot.id,
                    stock_id=stock.id,
                    segment=self._market_segment(asset),
                    size_bucket="unknown",
                    listing_age_bucket="unknown",
                    reason=f"minimum liquid research universe: {asset.role}",
                )
            )
        self._session.flush()

    @staticmethod
    def _market_segment(asset: ResearchAsset) -> str:
        if asset.asset_type == "etf":
            return MarketSegment.US_ETF.value
        if asset.asset_type == "index":
            return MarketSegment.US_INDEX.value
        if asset.exchange == "XNAS":
            return MarketSegment.NASDAQ.value
        if asset.exchange == "XNYS":
            return MarketSegment.NYSE.value
        raise ValueError(
            f"unsupported US market segment: {asset.ticker}/{asset.asset_type}/{asset.exchange}"
        )

    def _initialize_exchange_calendar(self, start_date: date, end_date: date) -> None:
        try:
            import exchange_calendars as xcals  # type: ignore[import-untyped]
        except ImportError:
            return
        now = datetime.now(UTC)
        for exchange, calendar_name in (("XNYS", "XNYS"), ("XNAS", "XNYS")):
            calendar = xcals.get_calendar(calendar_name)
            sessions = calendar.sessions_in_range(start_date.isoformat(), end_date.isoformat())
            existing = set(
                self._session.scalars(
                    select(ExchangeSession.session_date).where(
                        ExchangeSession.exchange == exchange,
                        ExchangeSession.session_date.between(start_date, end_date),
                        ExchangeSession.source == "exchange_calendars",
                    )
                )
            )
            for session_label in sessions:
                session_date = session_label.date()
                if session_date in existing:
                    continue
                self._session.add(
                    ExchangeSession(
                        exchange=exchange,
                        session_date=session_date,
                        is_open=True,
                        open_time=calendar.session_open(session_label).to_pydatetime(),
                        close_time=calendar.session_close(session_label).to_pydatetime(),
                        timezone="America/New_York",
                        source="exchange_calendars",
                        provider=f"exchange_calendars:{calendar_name}",
                        available_time=now,
                        ingested_time=now,
                    )
                )
        self._session.flush()

    def _persist_manifest(
        self,
        report: DailyUpdateReport,
        requested_at: datetime,
        completed_at: datetime,
        start_date: date,
        end_date: date,
    ) -> SyncOutcome:
        required = {item.ticker for item in MINIMUM_US_RESEARCH_UNIVERSE if item.required}
        lineage = (
            self._lineage_runner(
                self._session,
                self._settings,
                start_date,
                end_date,
                completed_at,
            )
            if self._lineage_runner is not None
            else DataLineageCertifier(self._session, self._settings).certify(
                assets=MINIMUM_US_RESEARCH_UNIVERSE,
                start_date=start_date,
                analysis_date=end_date,
                decision_time=completed_at,
                source_by_symbol={
                    item.symbol: item.source
                    for item in report.results
                    if item.source and item.status in {"success", "cached"}
                },
                include_optional_reconciliation=False,
            )
        )
        failures = {item.symbol for item in report.results if item.status == "failed"}
        selected_sources = {
            item.symbol: item.source
            for item in report.results
            if item.source and item.status in {"success", "cached"}
        }
        required_failures = failures & required
        accepted = sum(item.valid_count for item in report.results)
        raw = sum(item.fetched_count for item in report.results)
        rejected = max(raw - accepted, 0)
        duplicate_count = sum(
            issue.code == "duplicate_bar"
            for item in report.results
            for issue in item.quality_issues
        )
        coverage_latest = {item.symbol: item.latest for item in lineage.coverage}
        stale_required = {
            symbol for symbol in required if coverage_latest.get(symbol) != end_date
        }
        corporate_action_certified = lineage.corporate_actions.status in {
            EvidenceStatus.PASS,
            EvidenceStatus.PASS_WITH_WARNING,
        }
        provider_reconciled = lineage.reconciliation.status in {
            EvidenceStatus.PASS,
            EvidenceStatus.PASS_WITH_WARNING,
        }
        required_coverage_failures = {
            item.symbol
            for item in lineage.coverage
            if item.required
            and (
                item.missing > 0
                or item.duplicate > 0
                or item.unexpected != item.rejected
                or item.latest != end_date
            )
        }
        lineage_certified = corporate_action_certified
        if (
            required_failures
            or stale_required
            or required_coverage_failures
            or not lineage_certified
        ):
            certification, quality = "BLOCKED", "blocked"
        elif failures:
            certification, quality = "PARTIAL", "partial"
        else:
            certification, quality = "CERTIFIED", "passed"
        sources = sorted({item.source for item in report.results if item.source})
        adapters = sorted({item.provider for item in report.results if item.provider})
        payload = {
            "provider_name": ",".join(sources) or "unavailable",
            "provider_adapter": ",".join(adapters) or "unavailable",
            "requested_at": requested_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "market": "US",
            "asset_type": "mixed",
            "symbols": [item.symbol for item in report.results],
            "required_symbols": sorted(required),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "observed_at": completed_at.isoformat(),
            "timezone": "America/New_York",
            "currency": "USD",
            "price_adjustment_policy": "raw_ohlcv; adjusted_close_research_only",
            "corporate_action_policy": (
                "certified_pit_ledger"
                if corporate_action_certified
                else "not_certified_for_pit_portfolio_decisions"
            ),
            "corporate_action_status": lineage.corporate_actions.status.value,
            "single_source_certification": True,
            "provider_reconciliation_required": False,
            "provider_reconciled": provider_reconciled,
            "provider_reconciliation_status": lineage.reconciliation.status.value,
            "provider_reconciliation_secondary_providers": list(
                lineage.reconciliation.secondary_providers
            ),
            "provider_preflight": lineage.document()["reconciliation"].get(
                "provider_preflight", []
            ),
            "corporate_action_certificate_hash": lineage.corporate_actions.content_hash,
            "provider_reconciliation_hash": lineage.reconciliation.content_hash,
            "corporate_action_symbol_results": [
                {
                    "symbol": item.symbol,
                    "status": item.status.value,
                    "events_found": item.events_found,
                    "errors": list(item.errors),
                }
                for item in lineage.corporate_actions.symbol_results
            ],
            "provider_reconciliation_symbol_results": lineage.document()["reconciliation"][
                "symbol_results"
            ],
            "provider_reconciliation_window": {
                "start": (
                    lineage.reconciliation.reconciliation_window_start.isoformat()
                    if lineage.reconciliation.reconciliation_window_start
                    else None
                ),
                "end": (
                    lineage.reconciliation.reconciliation_window_end.isoformat()
                    if lineage.reconciliation.reconciliation_window_end
                    else None
                ),
                "minimum_overlap_sessions": (
                    lineage.reconciliation.minimum_overlap_sessions
                ),
                "preferred_overlap_sessions": (
                    lineage.reconciliation.preferred_overlap_sessions
                ),
                "latest_session_required": lineage.reconciliation.latest_session_required,
            },
            "required_certified": sum(
                item.required
                and item.symbol not in required_coverage_failures
                and item.symbol not in required_failures
                and item.symbol not in stale_required
                for item in lineage.coverage
            ),
            "required_total": sum(item.required for item in lineage.coverage),
            "optional_certified": sum(
                not item.required
                and item.missing == 0
                and item.duplicate == 0
                and item.unexpected == item.rejected
                and item.latest == end_date
                for item in lineage.coverage
            ),
            "optional_total": sum(not item.required for item in lineage.coverage),
            "pit_data_cutoff": (
                lineage.data_cutoff.isoformat() if lineage.data_cutoff is not None else None
            ),
            "latest_completed_session": lineage.latest_completed_session.isoformat(),
            "decision_timestamp_convention": lineage.decision_timestamp_convention,
            "bar_coverage": [
                {
                    "symbol": item.symbol,
                    "required": item.required,
                    "expected": item.expected,
                    "matched": item.matched,
                    "missing": item.missing,
                    "unexpected": item.unexpected,
                    "duplicate": item.duplicate,
                    "rejected": item.rejected,
                    "valid": item.valid,
                    "latest": item.latest.isoformat() if item.latest else None,
                    "missing_dates": [value.isoformat() for value in item.missing_dates],
                    "unexpected_dates": [
                        value.isoformat() for value in item.unexpected_dates
                    ],
                }
                for item in lineage.coverage
            ],
            "raw_row_count": raw,
            "accepted_row_count": accepted,
            "rejected_row_count": rejected,
            "duplicate_count": duplicate_count,
            "missingness_summary": {
                item.symbol: {
                    "status": item.status,
                    "rows": item.valid_count,
                    "source": item.source,
                    "provider": item.provider,
                    "error": item.error,
                    "refresh_class": item.refresh_class,
                }
                for item in report.results
            },
            "stale_symbol_summary": sorted(stale_required),
            "failed_symbols": sorted(failures | required_coverage_failures),
            "batch_timings": [dict(item) for item in report.batch_timings],
            "fallback_usage": [
                {
                    "symbol": item.symbol,
                    "provider": item.source,
                    "reason": "primary request failed; fallback passed identical quality checks",
                }
                for item in report.results
                if item.status in {"success", "cached"}
                and item.source
                and item.source != "yahoo_finance"
            ],
            "schema_version": "market-snapshot-v2",
            "application_version": __build_version__,
            "quality_status": quality,
            "certification_result": certification,
            "is_demo": False,
            "evidence": {
                "corporate_actions": "corporate_action_certificate.json",
                "provider_reconciliation_optional": "provider_reconciliation_report.json",
                "certification_matrix": "data_certification_matrix.json",
            },
        }
        content_hash = sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        snapshot_id = f"US-{completed_at:%Y%m%dT%H%M%SZ}-{content_hash[:12]}"
        target_dir = self._snapshot_root / snapshot_id
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / "manifest.json"
        corporate_action_path = target_dir / "corporate_action_certificate.json"
        reconciliation_path = target_dir / "provider_reconciliation_report.json"
        coverage_path = target_dir / "data_certification_matrix.json"
        write_evidence(
            corporate_action_path,
            {
                "snapshot_id": snapshot_id,
                **lineage.document()["corporate_actions"],
            },
        )
        write_evidence(
            reconciliation_path,
            {
                "snapshot_id": snapshot_id,
                **lineage.document()["reconciliation"],
            },
        )
        write_evidence(
            coverage_path,
            {
                "snapshot_id": snapshot_id,
                "coverage": lineage.document()["coverage"],
            },
        )
        document = {"snapshot_id": snapshot_id, "content_hash": content_hash, **payload}
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(target)
        self._session.add(
            DataSnapshotManifest(
                snapshot_id=snapshot_id,
                content_hash=content_hash,
                immutable_reference=str(target.resolve()),
                provider_name=str(payload["provider_name"]),
                provider_adapter=str(payload["provider_adapter"]),
                requested_at=requested_at,
                completed_at=completed_at,
                market="US",
                asset_type="mixed",
                symbols=[item.symbol for item in report.results],
                required_symbols=sorted(required),
                start_date=start_date,
                end_date=end_date,
                observed_at=completed_at,
                timezone="America/New_York",
                currency="USD",
                price_adjustment_policy=str(payload["price_adjustment_policy"]),
                corporate_action_policy=str(payload["corporate_action_policy"]),
                raw_row_count=raw,
                accepted_row_count=accepted,
                rejected_row_count=rejected,
                duplicate_count=duplicate_count,
                missingness_summary={
                    item.symbol: {
                        "status": item.status,
                        "rows": item.valid_count,
                        "source": item.source,
                        "provider": item.provider,
                        "error": item.error,
                        "refresh_class": item.refresh_class,
                    }
                    for item in report.results
                },
                stale_symbol_summary=sorted(stale_required),
                failed_symbols=sorted(failures | required_coverage_failures),
                schema_version="market-snapshot-v2",
                application_version=__build_version__,
                quality_status=quality,
                certification_result=certification,
                is_demo=False,
            )
        )
        self._session.flush()
        if certification == "CERTIFIED":
            self._materialize_live_research_evidence(
                analysis_date=end_date,
                decision_time=completed_at,
                manifest_hash=content_hash,
                corporate_action_hash=lineage.corporate_actions.content_hash,
                selected_sources=selected_sources,
                coverage=lineage.coverage,
            )
        return SyncOutcome(
            snapshot_id=snapshot_id,
            status=certification,
            successful=report.success_count,
            failed=report.failure_count,
            accepted_rows=accepted,
            manifest_path=target,
            failed_symbols=tuple(sorted(failures)),
        )

    def _materialize_live_research_evidence(
        self,
        *,
        analysis_date: date,
        decision_time: datetime,
        manifest_hash: str,
        corporate_action_hash: str,
        selected_sources: dict[str, str],
        coverage: tuple[BarCoverageEvidence, ...],
    ) -> None:
        """Persist the current daily PIT inputs without certifying historical membership.

        The configured universe is observable at ``decision_time`` and is therefore
        valid for today's diagnostic cross-section.  Its research certification
        explicitly disallows backtests and portfolio decisions; historical universe
        membership remains a separate, fail-closed capability.
        """

        snapshot = self._session.scalar(
            select(MarketUniverseSnapshot).where(
                MarketUniverseSnapshot.market == "US",
                MarketUniverseSnapshot.as_of_date == analysis_date,
                MarketUniverseSnapshot.source == "console_minimum_universe",
            )
        )
        if snapshot is None:
            raise ValueError("current live universe snapshot was not persisted")
        members = tuple(
            self._session.scalars(
                select(Stock)
                .join(MarketUniverseMember, MarketUniverseMember.stock_id == Stock.id)
                .where(MarketUniverseMember.snapshot_id == snapshot.id)
                .order_by(Stock.canonical_code)
            )
        )
        if not members:
            raise ValueError("current live universe snapshot has no members")
        history_counts = {
            security.symbol: int(
                self._session.scalar(
                    select(func.count())
                    .select_from(Price)
                    .where(
                        Price.stock_id == security.id,
                        Price.source == selected_sources.get(security.symbol, ""),
                        Price.trade_date <= analysis_date,
                        Price.available_time.is_not(None),
                        Price.available_time <= decision_time,
                    )
                )
                or 0
            )
            for security in members
        }
        # A refresh may be driven by a manifest-only test/diagnostic adapter.  DATA
        # evidence remains valid for its own scope, but PIT is intentionally not
        # materialized until every selected source has real history.
        if any(count < 2 for count in history_counts.values()):
            return

        repository = USPointInTimeRepository(self._session)
        builder = PointInTimeTotalReturnBuilder()
        version_ids: list[str] = []
        history_starts: list[date] = []
        for security in members:
            selected_source = selected_sources.get(security.symbol)
            if not selected_source:
                raise ValueError(f"selected source is missing: {security.symbol}")
            prices = tuple(
                self._session.scalars(
                    select(Price)
                    .where(
                        Price.stock_id == security.id,
                        Price.source == selected_source,
                        Price.trade_date <= analysis_date,
                        Price.available_time.is_not(None),
                        Price.available_time <= decision_time,
                        Price.price_type.in_(("unadjusted_ohlcv", "index_level_ohlcv")),
                    )
                    .order_by(Price.trade_date, Price.id)
                )
            )
            if len(prices) < 2:
                raise ValueError(
                    f"insufficient selected-source PIT history: {security.symbol}"
                )
            history_starts.append(prices[0].trade_date)
            bars = tuple(
                PITRawBar(
                    permanent_security_id=security.canonical_code,
                    trade_date=item.trade_date,
                    close=float(item.close),
                    source_id=(
                        f"price:{item.source}:{item.provider}:{security.canonical_code}:"
                        f"{item.trade_date.isoformat()}"
                    ),
                    available_at=normalize_utc(item.available_time),
                )
                for item in prices
                if item.available_time is not None
            )
            actions = tuple(
                self._pit_action(item, security.canonical_code)
                for item in self._session.scalars(
                    select(CorporateAction)
                    .where(
                        CorporateAction.stock_id == security.id,
                        CorporateAction.effective_date <= analysis_date,
                        CorporateAction.available_time <= decision_time,
                    )
                    .order_by(CorporateAction.effective_date, CorporateAction.id)
                )
            )
            series = builder.build(
                bars=bars,
                actions=actions,
                as_of_time=decision_time,
            )
            repository.persist_total_return_series(
                series,
                stock_id=security.id,
                corporate_action_ledger_hash=corporate_action_hash,
                certification_status="CERTIFIED",
            )
            version_ids.append(series.version_id)

        universe_payload = {
            "scope": "CURRENT_LIVE_ANALYSIS_ONLY",
            "analysis_date": analysis_date.isoformat(),
            "available_time": normalize_utc(snapshot.available_time).isoformat(),
            "members": [item.canonical_code for item in members],
            "manifest_hash": manifest_hash,
            "corporate_action_hash": corporate_action_hash,
            "pit_total_return_versions": sorted(version_ids),
        }
        data_version = sha256(
            json.dumps(universe_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        snapshot.version_id = data_version
        snapshot.data_version = data_version
        snapshot.content_hash = data_version
        snapshot.certification_status = "CERTIFIED"

        expected = sum(item.expected for item in coverage)
        missing = sum(item.missing for item in coverage)
        anomalies = sum(
            item.duplicate + item.rejected
            for item in coverage
        )
        quality = MarketDataQualityRun(
            history_start=min(history_starts),
            history_end=analysis_date,
            random_seed=0,
            minimum_sample_size=len(members),
            sample_count=len(members),
            status="passed",
            source_snapshot_ids=[snapshot.id],
            aggregate_metrics={
                "source": "strict_selected_source_daily_certification",
                "provider": ",".join(sorted(set(selected_sources.values()))),
                "latest_available_time": decision_time.isoformat(),
                "missing_rate": (missing / expected if expected else 0.0),
                "anomaly_rate": (anomalies / expected if expected else 0.0),
                "maximum_missing_rate": 0.0,
                "maximum_anomaly_rate": 0.0,
                "us_point_in_time_status": "certified",
                "us_adjustment_mode": "point_in_time_total_return",
                "us_corporate_actions_certified": True,
                "us_trading_calendar_certified": True,
                "us_dual_source_verified": False,
                "source_conflict": False,
                "data_version": data_version,
                "allow_display": True,
                "allow_backtest": False,
                "allow_portfolio_decision": True,
                "universe_scope": "CURRENT_LIVE_ANALYSIS_ONLY",
                "survivorship_safe_for_history": False,
            },
            blockers=[],
        )
        self._session.add(quality)
        self._session.flush()
        evidence_fingerprint = sha256(
            json.dumps(
                {
                    "quality_run_id": quality.id,
                    "universe_snapshot_id": snapshot.id,
                    "data_version": data_version,
                    "scope": "CURRENT_LIVE_ANALYSIS_ONLY",
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        existing = self._session.scalar(
            select(ResearchDataCertification).where(
                ResearchDataCertification.market == "US",
                ResearchDataCertification.asset_type == "mixed",
                ResearchDataCertification.data_version == data_version,
            )
        )
        if existing is None:
            self._session.add(
                ResearchDataCertification(
                    market="US",
                    asset_type="mixed",
                    data_version=data_version,
                    status="APPROVED",
                    evidence_fingerprint=evidence_fingerprint,
                    quality_run_id=quality.id,
                    universe_snapshot_id=snapshot.id,
                    allow_display=True,
                    allow_backtest=False,
                    allow_portfolio_decision=True,
                    valid_from=decision_time,
                    valid_until=None,
                    blockers=[],
                    warnings=[
                        "current configured universe is not historical survivorship-safe",
                        "portfolio decisions require separate model/data approval",
                    ],
                )
            )
        self._session.flush()
        self._materialize_tradability_evidence(
            members=members,
            decision_time=decision_time,
        )

    def _materialize_tradability_evidence(
        self,
        *,
        members: tuple[Stock, ...],
        decision_time: datetime,
    ) -> None:
        """Persist point-in-time tradability evidence for the certified universe.

        A security is recorded as TRADABLE only when certified bar evidence was
        actually available at ``decision_time`` and no delisting record is known.
        ``available_time``/``effective_time`` are the real ingestion moment and are
        never backdated; securities without bar evidence receive no row and remain
        UNKNOWN, which keeps portfolio construction fail-closed.
        """

        ingested = normalize_utc(decision_time)
        for security in members:
            if security.asset_type not in {"stock", "etf"}:
                continue
            delisted = self._session.scalar(
                select(DelistingHistory)
                .where(
                    DelistingHistory.stock_id == security.id,
                    DelistingHistory.available_time <= ingested,
                )
                .limit(1)
            )
            if delisted is not None:
                continue
            bar_count = (
                self._session.scalar(
                    select(func.count())
                    .select_from(Price)
                    .where(
                        Price.stock_id == security.id,
                        Price.available_time.is_not(None),
                        Price.available_time <= ingested,
                    )
                )
                or 0
            )
            if bar_count == 0:
                continue
            latest = self._session.scalar(
                select(TradingStatus)
                .where(
                    TradingStatus.stock_id == security.id,
                    TradingStatus.available_time <= ingested,
                )
                .order_by(
                    TradingStatus.effective_time.desc(), TradingStatus.id.desc()
                )
                .limit(1)
            )
            if latest is not None and latest.status == "TRADABLE":
                continue
            self._session.add(
                TradingStatus(
                    stock_id=security.id,
                    status="TRADABLE",
                    effective_time=ingested,
                    available_time=ingested,
                    ingested_time=ingested,
                    reason="certified PIT bar evidence; no known delisting record",
                    source="certified_live_universe",
                    provider="data_lineage_certification",
                )
            )
        self._session.flush()

    @staticmethod
    def _pit_action(item: CorporateAction, permanent_security_id: str) -> PITCorporateAction:
        mapped_type = {
            "merger_cash": "merger_consideration",
            "merger_stock": "merger_consideration",
            "delisting": "delisting_payment",
        }.get(item.action_type, item.action_type)
        announcement_at = None
        if item.announcement_date is not None:
            announcement_at = datetime.combine(
                item.announcement_date,
                datetime.min.time(),
                tzinfo=UTC,
            )
        return PITCorporateAction(
            action_id=item.action_id,
            revision_id=item.revision_id,
            permanent_security_id=permanent_security_id,
            action_type=mapped_type,
            effective_date=item.effective_date,
            announcement_at=announcement_at,
            available_at=normalize_utc(item.available_time),
            source_id=f"corporate-action:{item.source}:{item.provider}:{item.action_id}",
            split_ratio=(float(item.split_ratio) if item.split_ratio is not None else None),
            cash_amount=(float(item.cash_amount) if item.cash_amount is not None else None),
            currency=item.currency,
        )
