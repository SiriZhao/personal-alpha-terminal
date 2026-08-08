from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.backtest.schemas import BacktestBar, UniversePoint
from personal_alpha_terminal.models import (
    CorporateAction as CorporateActionRecord,
)
from personal_alpha_terminal.models import (
    ExchangeSession,
    MarketUniverseMember,
    MarketUniverseSnapshot,
    Price,
    SecurityMaster,
)
from personal_alpha_terminal.quant_engine.backtest import (
    BacktestTarget,
    CorporateAction,
    CorporateActionType,
    ProductionBacktestConfig,
    ProductionBacktestDataset,
    ProductionBacktestEngine,
    ProductionBacktestResult,
)
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchPurpose,
)


@dataclass(frozen=True, slots=True)
class BacktestAvailability:
    available: bool
    status: str
    reason: str


class ProductionBacktestDatasetRepository:
    """Build the official raw-price backtest dataset from certified persisted evidence."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def load(
        self,
        *,
        authorization: ResearchDataAuthorization,
        start_date: date,
        end_date: date,
    ) -> tuple[ProductionBacktestDataset, dict[int, str]]:
        if not authorization.permits(ResearchPurpose.BACKTEST):
            raise ValueError("BacktestDataGate is not approved")
        evidence = authorization.evidence
        if evidence.market != "US" or evidence.adjustment_mode != "point_in_time_total_return":
            raise ValueError("official backtest requires US point-in-time total-return evidence")
        cutoff = datetime.combine(end_date, time.max, tzinfo=UTC)
        snapshots = tuple(
            self.session.scalars(
                select(MarketUniverseSnapshot)
                .where(
                    MarketUniverseSnapshot.market == "US",
                    MarketUniverseSnapshot.as_of_date <= end_date,
                    MarketUniverseSnapshot.available_time <= cutoff,
                    MarketUniverseSnapshot.certification_status == "CERTIFIED",
                    MarketUniverseSnapshot.data_version == evidence.data_version,
                )
                .order_by(MarketUniverseSnapshot.as_of_date, MarketUniverseSnapshot.id)
            )
        )
        if not snapshots:
            raise ValueError("certified historical US universe timeline is unavailable")
        timeline: list[UniversePoint] = []
        all_assets: set[int] = set()
        for snapshot in snapshots:
            members = frozenset(
                self.session.scalars(
                    select(MarketUniverseMember.stock_id).where(
                        MarketUniverseMember.snapshot_id == snapshot.id,
                    )
                )
            )
            if not members:
                raise ValueError(f"certified universe snapshot {snapshot.id} has no members")
            all_assets.update(members)
            timeline.append(
                UniversePoint(
                    snapshot_id=snapshot.id,
                    as_of_date=snapshot.as_of_date,
                    available_at=snapshot.available_time,
                    asset_ids=members,
                    source=f"{snapshot.source}:{snapshot.provider}",
                )
            )
        securities = {
            item.id: item
            for item in self.session.scalars(
                select(SecurityMaster).where(SecurityMaster.id.in_(all_assets))
            )
        }
        if set(securities) != all_assets:
            raise ValueError("universe timeline contains unknown securities")
        prices = tuple(
            self.session.scalars(
                select(Price)
                .where(
                    Price.stock_id.in_(all_assets),
                    Price.trade_date >= start_date,
                    Price.trade_date <= end_date,
                    Price.price_type == "unadjusted_ohlcv",
                    Price.available_time.is_not(None),
                    Price.available_time <= cutoff,
                )
                .order_by(Price.trade_date, Price.stock_id, Price.id)
            )
        )
        bars = tuple(
            BacktestBar(
                asset_id=item.stock_id,
                symbol=securities[item.stock_id].symbol,
                market="US",
                trade_date=item.trade_date,
                open=float(item.open),
                high=float(item.high),
                low=float(item.low),
                close=float(item.close),
                adjusted_close=None,
                volume=int(item.volume) if item.volume is not None else None,
                source=item.source,
                adjustment_method="RAW_OHLCV",
                provider=item.provider,
                event_time=item.event_time,
                available_time=item.available_time,
                ingested_time=item.ingested_at,
                open_tradable=item.open_tradable,
            )
            for item in prices
        )
        sessions = tuple(
            self.session.scalars(
                select(ExchangeSession)
                .where(
                    ExchangeSession.exchange.in_(("XNYS", "XNAS")),
                    ExchangeSession.session_date >= start_date,
                    ExchangeSession.session_date <= end_date,
                    ExchangeSession.is_open.is_(True),
                    ExchangeSession.available_time <= cutoff,
                    ExchangeSession.source != "legacy_unknown",
                )
                .order_by(ExchangeSession.session_date, ExchangeSession.id)
            )
        )
        calendar = tuple(sorted({item.session_date for item in sessions}))
        if not calendar:
            raise ValueError("verified US trading calendar is unavailable")
        actions = tuple(
            self._action(item)
            for item in self.session.scalars(
                select(CorporateActionRecord)
                .where(
                    CorporateActionRecord.stock_id.in_(all_assets),
                    CorporateActionRecord.effective_date >= start_date,
                    CorporateActionRecord.effective_date <= end_date,
                    CorporateActionRecord.available_time <= cutoff,
                )
                .order_by(CorporateActionRecord.effective_date, CorporateActionRecord.id)
            )
        )
        sectors = {
            item.id: item.industry.name if item.industry is not None else "UNCLASSIFIED"
            for item in securities.values()
        }
        return (
            ProductionBacktestDataset(
                bars=bars,
                calendar=calendar,
                calendar_source="persisted_verified_us_exchange_sessions",
                universe_timeline=tuple(timeline),
                corporate_actions=actions,
                corporate_action_ledger_certified=evidence.corporate_actions_complete,
                universe_certified=True,
                data_version=evidence.data_version,
            ),
            sectors,
        )

    @staticmethod
    def _action(item: CorporateActionRecord) -> CorporateAction:
        mapping = {
            "split": CorporateActionType.SPLIT,
            "reverse_split": CorporateActionType.SPLIT,
            "cash_dividend": CorporateActionType.CASH_DIVIDEND,
            "merger_cash": CorporateActionType.MERGER_CASH,
            "delisting": CorporateActionType.DELISTING,
            "symbol_change": CorporateActionType.SYMBOL_CHANGE,
        }
        kind = mapping.get(item.action_type)
        if kind is None:
            raise ValueError(
                f"corporate action requires unsupported explicit valuation: {item.action_type}"
            )
        return CorporateAction(
            asset_id=item.stock_id,
            action_type=kind,
            effective_date=item.effective_date,
            announcement_date=item.announcement_date,
            available_at=item.available_time,
            ratio=float(item.split_ratio) if item.split_ratio is not None else None,
            cash_amount=float(item.cash_amount) if item.cash_amount is not None else None,
            new_symbol=str(item.details.get("new_symbol", "")) or None,
            source=f"{item.source}:{item.provider}:{item.action_id}:{item.revision_id}",
        )


class BacktestService:
    """Single official service around ProductionBacktestEngine."""

    def __init__(self, session: Session | None = None) -> None:
        self.session = session

    def availability(self, *, gate_approved: bool) -> BacktestAvailability:
        if not gate_approved:
            return BacktestAvailability(
                False,
                "BLOCKED",
                "PIT universe, corporate actions, total return, and model gates are not approved.",
            )
        return BacktestAvailability(True, "READY", "Certified production backtest is available.")

    def run_backtest(
        self,
        *,
        authorization: ResearchDataAuthorization,
        start_date: date,
        end_date: date,
        targets: tuple[BacktestTarget, ...],
        config: ProductionBacktestConfig,
    ) -> ProductionBacktestResult:
        if self.session is None:
            raise RuntimeError("BacktestService requires the bound runtime database session")
        dataset, sectors = ProductionBacktestDatasetRepository(self.session).load(
            authorization=authorization,
            start_date=start_date,
            end_date=end_date,
        )
        return ProductionBacktestEngine().run(dataset, targets, config, sectors=sectors)
