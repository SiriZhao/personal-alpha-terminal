from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_alpha_terminal import __build_version__
from personal_alpha_terminal.application.data_certification import (
    DailyDataCertification,
    DailyDataCertifier,
)
from personal_alpha_terminal.application.data_lineage_certification import (
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
from personal_alpha_terminal.core.runtime_bootstrap import application_data_dir
from personal_alpha_terminal.data.market_data.factory import build_market_data_engine
from personal_alpha_terminal.data.market_data.schemas import DailyUpdateReport
from personal_alpha_terminal.data.market_data_quality.schemas import MarketSegment
from personal_alpha_terminal.models import (
    DataSnapshotManifest,
    ExchangeSession,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    Stock,
)


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

    def sync_market_data(self, *, start_date: date, end_date: date) -> SyncOutcome:
        self._register_minimum_universe()
        self._create_universe_snapshot(end_date)
        requested_at = datetime.now(UTC)
        report = self._sync_runner(self._session, start_date, end_date)
        completed_at = datetime.now(UTC)
        return self._persist_manifest(report, requested_at, completed_at, start_date, end_date)

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
            markets={"US"}, start_date=start_date, end_date=end_date
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
            )
        )
        failures = {item.symbol for item in report.results if item.status == "failed"}
        required_failures = failures & required
        accepted = sum(item.valid_count for item in report.results)
        raw = sum(item.fetched_count for item in report.results)
        rejected = max(raw - accepted, 0)
        duplicate_count = sum(
            issue.code == "duplicate_bar"
            for item in report.results
            for issue in item.quality_issues
        )
        latest_dates: dict[str, date] = {}
        latest_rows = self._session.execute(
            select(Stock.symbol, func.max(Price.trade_date))
            .join(Price, Price.stock_id == Stock.id)
            .where(Stock.market == "US", Stock.symbol.in_(sorted(required)))
            .group_by(Stock.symbol)
        ).all()
        for symbol, latest_date in latest_rows:
            if latest_date is not None:
                latest_dates[symbol] = latest_date
        fresh_in_report = {
            item.symbol
            for item in report.results
            if (item.status == "success" and item.valid_count > 0)
            or item.status == "cached"
        }
        stale_required = {
            symbol
            for symbol in required
            if symbol not in fresh_in_report
            and (
                symbol not in latest_dates
                or (
                    end_date - latest_dates[symbol]
                ).days > self._settings.console_data_stale_days
            )
        }
        corporate_action_certified = lineage.corporate_actions.status in {
            EvidenceStatus.PASS,
            EvidenceStatus.PASS_WITH_WARNING,
        }
        provider_reconciled = lineage.reconciliation.status in {
            EvidenceStatus.PASS,
            EvidenceStatus.PASS_WITH_WARNING,
        }
        lineage_certified = corporate_action_certified and provider_reconciled
        if required_failures or stale_required:
            certification, quality = "BLOCKED", "blocked"
        elif failures or not lineage_certified:
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
            "provider_reconciled": provider_reconciled,
            "provider_reconciliation_status": lineage.reconciliation.status.value,
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
            "provider_reconciliation_symbol_results": [
                {
                    "symbol": item.symbol,
                    "status": item.status.value,
                    "secondary_provider": item.secondary_provider,
                    "primary_rows": item.primary_rows,
                    "secondary_rows": item.secondary_rows,
                    "matched_rows": item.matched_rows,
                    "coverage": item.coverage,
                    "warning_divergences": item.warning_divergences,
                    "blocking_divergences": item.blocking_divergences,
                    "reason": item.reason,
                }
                for item in lineage.reconciliation.symbol_results
            ],
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
                }
                for item in report.results
            },
            "stale_symbol_summary": sorted(stale_required),
            "failed_symbols": sorted(failures),
            "schema_version": "market-snapshot-v1",
            "application_version": __build_version__,
            "quality_status": quality,
            "certification_result": certification,
            "is_demo": False,
            "evidence": {
                "corporate_actions": "corporate_action_certificate.json",
                "provider_reconciliation": "provider_reconciliation_report.json",
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
                    }
                    for item in report.results
                },
                stale_symbol_summary=sorted(stale_required),
                failed_symbols=sorted(failures),
                schema_version="market-snapshot-v1",
                application_version=__build_version__,
                quality_status=quality,
                certification_result=certification,
                is_demo=False,
            )
        )
        self._session.flush()
        return SyncOutcome(
            snapshot_id=snapshot_id,
            status=certification,
            successful=report.success_count,
            failed=report.failure_count,
            accepted_rows=accepted,
            manifest_path=target,
            failed_symbols=tuple(sorted(failures)),
        )
