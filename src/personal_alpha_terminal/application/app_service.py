from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.application.backtest_service import BacktestService
from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator
from personal_alpha_terminal.application.daily_result import DailyQuantResult
from personal_alpha_terminal.application.data_service import (
    DataService,
    InitializationProgress,
    SyncOutcome,
    SyncRunner,
)
from personal_alpha_terminal.application.decision_service import CandidateView, DecisionService
from personal_alpha_terminal.application.diagnostic_service import DiagnosticService
from personal_alpha_terminal.application.intelligence_service import (
    IntelligenceApplicationService,
)
from personal_alpha_terminal.application.manual_execution_service import (
    ManualExecutionOrderService,
)
from personal_alpha_terminal.application.pipeline_service import PipelineService
from personal_alpha_terminal.application.quant_daily_service import (
    ProductionDailyWorkflow,
    TodayResult,
)
from personal_alpha_terminal.application.status import (
    ModelStatus,
    ProgramStatus,
    StatusDetail,
    SystemReadiness,
)
from personal_alpha_terminal.application.today_summary import DashboardView
from personal_alpha_terminal.automation.runner import PipelineExecution
from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.core.effective_config import (
    EffectiveRuntimeConfig,
    effective_config_from_settings,
)
from personal_alpha_terminal.decision_engine.repository import DecisionRepository
from personal_alpha_terminal.decision_engine.schemas import UserDecision
from personal_alpha_terminal.models import (
    DailyPipelineRun,
    Portfolio,
    PortfolioPosition,
    PortfolioTransaction,
    QuantDecisionRun,
    Stock,
)
from personal_alpha_terminal.portfolio.portfolio_validation import (
    ValidatedPosition,
    validate_cash,
    validate_ticker,
)
from personal_alpha_terminal.portfolio.position_import import (
    ParsedPositionFile,
    PositionImportResult,
    PositionImportRow,
    PositionImportService,
    parse_position_csv,
)
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar


class ApplicationService:
    """Headless facade for research, backtests, diagnostics, and manual review.

    There is no second trading domain. Accepting a candidate creates only a
    pending manual-execution record; it never contacts a broker or changes holdings.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings | None = None,
        *,
        snapshot_root: Path | None = None,
        sync_runner: SyncRunner | None = None,
        effective_config: EffectiveRuntimeConfig | None = None,
    ) -> None:
        self._factory = session_factory
        self._settings = settings or get_settings()
        self._snapshot_root = snapshot_root
        self._sync_runner = sync_runner
        self._effective_config = effective_config or effective_config_from_settings(self._settings)

    def get_system_health(self) -> SystemReadiness:
        try:
            with self._factory() as session:
                session.execute(text("SELECT 1"))
                database = StatusDetail.build(
                    ProgramStatus.READY,
                    "数据库正常",
                    "数据库连接可用。",
                    "SELECT 1 passed",
                    "无需操作",
                    allow_research=True,
                )
                data = self._data_service(session).get_data_readiness()
                model = self._model_status(session, data.allow_research)
                program_code = (
                    ProgramStatus.DEGRADED
                    if data.code in {"PARTIAL", "STALE", "PROVIDER_ERROR"} or model.code == "FAILED"
                    else ProgramStatus.READY
                )
                program = StatusDetail.build(
                    program_code,
                    "程序正常" if program_code is ProgramStatus.READY else "程序降级运行",
                    "研究终端与数据库可用；数据和模型状态独立显示。",
                    "headless application service available",
                    "按数据中心提示处理问题",
                    allow_research=data.allow_research,
                    allow_candidates=model.allow_candidates,
                )
                return SystemReadiness(program, database, data, model)
        except Exception as error:
            failure = StatusDetail.build(
                ProgramStatus.ERROR,
                "程序初始化异常",
                "已进入安全诊断模式。",
                f"{type(error).__name__}: {error}",
                "导出诊断包并查看日志",
            )
            return SystemReadiness(failure, failure, failure, failure)

    def get_data_readiness(self) -> StatusDetail:
        with self._factory() as session:
            return self._data_service(session).get_data_readiness()

    def get_model_readiness(self) -> StatusDetail:
        with self._factory() as session:
            data = self._data_service(session).get_data_readiness()
            return self._model_status(session, data.allow_research)

    def get_market_session_status(self) -> str:
        now = datetime.now(UTC)
        state = MarketSessionCalendar(
            nasdaq_23h_enabled=self._effective_config.nasdaq_23h_enabled,
            nasdaq_23h_effective_date=self._effective_config.nasdaq_23h_effective_date,
            night_execution_enabled=False,
            allow_deterministic_fallback=self._effective_config.allow_calendar_fallback,
        ).classify(now)
        return (
            f"ET {state.timestamp_et:%Y-%m-%d %H:%M %Z} | "
            f"Trade Date {state.trade_date} | {state.session.value}"
        )

    def initialize_research_database(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        progress: Callable[[InitializationProgress], None] | None = None,
    ) -> SyncOutcome:
        with self._factory.begin() as session:
            return self._data_service(session).initialize_research_database(
                start_date=start_date, end_date=end_date, progress=progress
            )

    def sync_market_data(self, *, start_date: date, end_date: date) -> SyncOutcome:
        with self._factory.begin() as session:
            return self._data_service(session).sync_market_data(
                start_date=start_date, end_date=end_date
            )

    def run_daily_pipeline(self, as_of_date: date | None = None) -> PipelineExecution:
        return PipelineService(self._settings).run_daily_pipeline(as_of_date)

    def run_quant_daily(
        self,
        *,
        portfolio_id: int | str,
        decision_time: datetime | None = None,
    ) -> TodayResult:
        """Run the gated DB -> alpha -> portfolio -> action production chain."""

        with self._factory.begin() as session:
            resolved_id = self._resolve_portfolio_id(session, portfolio_id)
            return ProductionDailyWorkflow(session, self._effective_config).run(
                portfolio_id=resolved_id,
                decision_time=decision_time or datetime.now(UTC),
            )

    def run_daily_quant_report(
        self,
        *,
        portfolio_id: int | str | None = None,
        decision_time: datetime | None = None,
        refresh: bool = True,
        progress: Callable[[str], None] | None = None,
    ) -> DailyQuantResult:
        """Run the only production daily orchestrator consumed by terminals."""

        resolved_id: int | None = None
        if portfolio_id is not None:
            with self._factory() as session:
                resolved_id = self._resolve_portfolio_id(session, portfolio_id)
        return DailyQuantOrchestrator(
            self._factory,
            self._effective_config,
            snapshot_root=(
                self._snapshot_root / "daily-runs" if self._snapshot_root is not None else None
            ),
            sync_runner=self._sync_runner,
        ).run(
            portfolio_id=resolved_id,
            decision_time=decision_time,
            refresh=refresh,
            progress=progress,
        )

    def get_daily_dashboard(self) -> DashboardView:
        readiness = self.get_system_health()
        with self._factory() as session:
            latest = session.scalar(
                select(DailyPipelineRun).order_by(DailyPipelineRun.start_time.desc()).limit(1)
            )
            candidates = DecisionService(session).get_action_candidates()
            portfolio = session.scalar(select(Portfolio).order_by(Portfolio.id).limit(1))
            position_count = (
                session.scalar(
                    select(func.count())
                    .select_from(PortfolioPosition)
                    .where(PortfolioPosition.portfolio_id == portfolio.id)
                )
                if portfolio is not None
                else 0
            ) or 0
        tasks: list[str] = []
        if readiness.data.code == "EMPTY":
            tasks.append("初始化最小美股研究数据")
        if readiness.data.code in {"STALE", "PROVIDER_ERROR"}:
            tasks.append("同步或修复行情数据")
        if readiness.model.code != "READY":
            tasks.append("数据门禁通过后运行量化流水线")
        if portfolio is None:
            tasks.append("创建真实组合或导入 Charles Schwab 持仓 CSV")
        elif position_count == 0:
            tasks.append("组合尚无持仓；可导入 Charles Schwab 持仓 CSV")
        return DashboardView(
            readiness=readiness,
            market_session=self.get_market_session_status(),
            latest_pipeline_date=latest.run_date if latest else None,
            latest_pipeline_status=latest.status if latest else "NOT_RUN",
            candidates=candidates,
            tasks=tuple(tasks),
            generated_at=datetime.now(UTC),
            portfolio_name=portfolio.name if portfolio is not None else None,
            portfolio_cash=portfolio.cash_balance if portfolio is not None else None,
            portfolio_position_count=position_count,
        )

    def create_portfolio(
        self,
        *,
        name: str,
        cash_balance: float = 0.0,
        currency: str = "USD",
    ) -> int:
        portfolio_id, _warnings = self.create_portfolio_with_positions(
            name=name,
            cash_balance=cash_balance,
            currency=currency,
            positions=(),
            source="cli-manual",
        )
        return portfolio_id

    def create_portfolio_with_positions(
        self,
        *,
        name: str,
        cash_balance: float | Decimal,
        currency: str = "USD",
        positions: tuple[ValidatedPosition, ...] = (),
        source: str = "cli-manual",
        as_of_date: date | None = None,
    ) -> tuple[int, tuple[str, ...]]:
        """Create the real manual ledger atomically with optional positions.

        The whole operation is one transaction: either the portfolio and every
        matched position are persisted, or nothing is.  Tickers that do not match
        the US security master are excluded with an explicit warning instead of
        being fabricated; cash is never assumed.
        """

        normalized = name.strip()
        if not normalized:
            raise ValueError("portfolio name must not be empty")
        normalized_currency = currency.strip().upper()
        if normalized_currency != "USD":
            raise ValueError("the production terminal supports USD portfolios only")
        cash = validate_cash(cash_balance)
        snapshot_date = as_of_date or datetime.now(UTC).date()
        with self._factory.begin() as session:
            if session.scalar(select(Portfolio).where(Portfolio.name == normalized)) is not None:
                raise ValueError("portfolio name already exists")
            model = Portfolio(
                name=normalized,
                description="Manual Charles Schwab tracking; no broker connection",
                base_currency=normalized_currency,
                cash_balance=cash,
                source=source,
            )
            session.add(model)
            session.flush()
            event_time = datetime.combine(snapshot_date, datetime.min.time(), tzinfo=UTC)
            if cash > 0:
                session.add(
                    PortfolioTransaction(
                        portfolio_id=model.id,
                        transaction_type="deposit",
                        trade_date=snapshot_date,
                        settlement_date=snapshot_date,
                        cash_amount=cash,
                        fee_amount=Decimal("0"),
                        currency=normalized_currency,
                        fx_rate_to_base=Decimal("1"),
                        source="portfolio_initialization",
                        external_id=f"initial-cash:{normalized}",
                        notes="Initial cash recorded by manual portfolio initialization",
                        event_time=event_time,
                        available_time=event_time,
                    )
                )
            warnings: list[str] = []
            seen: set[str] = set()
            for item in positions:
                ticker = validate_ticker(item.ticker)
                if ticker in seen:
                    raise ValueError(f"duplicate ticker: {ticker}")
                seen.add(ticker)
                stock = session.scalar(
                    select(Stock).where(
                        Stock.market == "US",
                        Stock.symbol == ticker,
                        Stock.is_active.is_(True),
                    )
                )
                if stock is None:
                    warnings.append(
                        f"ticker {ticker} is not in the US security master and was excluded"
                    )
                    continue
                session.add(
                    PortfolioPosition(
                        portfolio_id=model.id,
                        stock_id=stock.id,
                        as_of_date=snapshot_date,
                        quantity=item.shares,
                        average_cost=item.average_cost,
                    )
                )
            session.flush()
            return model.id, tuple(warnings)

    def import_portfolio_csv(
        self,
        *,
        portfolio_id: int | str,
        source: Path,
        as_of_date: date,
        cash_override: Decimal | None = None,
    ) -> PositionImportResult:
        if as_of_date > datetime.now(UTC).date():
            raise ValueError("portfolio as_of date cannot be in the future")
        parsed = parse_position_csv(source.read_bytes())
        if cash_override is not None:
            parsed = ParsedPositionFile(
                format_name=parsed.format_name,
                rows=parsed.rows,
                cash_balance=validate_cash(cash_override),
                warnings=parsed.warnings,
            )
        with self._factory.begin() as session:
            resolved_id = self._resolve_portfolio_id(session, portfolio_id)
            return PositionImportService(session).import_snapshot(
                portfolio_id=resolved_id,
                as_of_date=as_of_date,
                parsed=parsed,
            )

    def preview_portfolio_csv(self, *, source: Path) -> ParsedPositionFile:
        """Validate and preview a CSV without mutating the user's ledger or source file."""

        return parse_position_csv(source.read_bytes())

    def update_portfolio_snapshot(
        self,
        *,
        portfolio_id: int | str,
        as_of_date: date,
        positions: tuple[ValidatedPosition, ...],
        cash_balance: Decimal | None = None,
    ) -> PositionImportResult:
        """Atomically replace one dated manual snapshot; no broker action is implied."""

        if as_of_date > datetime.now(UTC).date():
            raise ValueError("portfolio as_of date cannot be in the future")
        parsed = ParsedPositionFile(
            format_name="manual_cli_snapshot",
            rows=tuple(
                PositionImportRow(item.ticker, item.shares, item.average_cost) for item in positions
            ),
            cash_balance=(validate_cash(cash_balance) if cash_balance is not None else None),
            warnings=(),
        )
        with self._factory.begin() as session:
            resolved_id = self._resolve_portfolio_id(session, portfolio_id)
            portfolio = session.get(Portfolio, resolved_id)
            assert portfolio is not None
            if parsed.cash_balance is not None and parsed.cash_balance != portfolio.cash_balance:
                delta = parsed.cash_balance - portfolio.cash_balance
                event_time = datetime.combine(as_of_date, datetime.min.time(), tzinfo=UTC)
                session.add(
                    PortfolioTransaction(
                        portfolio_id=resolved_id,
                        transaction_type="deposit" if delta > 0 else "withdrawal",
                        trade_date=as_of_date,
                        settlement_date=as_of_date,
                        cash_amount=abs(delta),
                        fee_amount=Decimal("0"),
                        currency=portfolio.base_currency,
                        fx_rate_to_base=Decimal("1"),
                        source="portfolio_manual_update",
                        external_id=(
                            f"cash-update:{portfolio.name}:{as_of_date}:"
                            f"{parsed.cash_balance.normalize()}"
                        ),
                        notes="Manual cash balance reconciliation",
                        event_time=event_time,
                        available_time=event_time,
                    )
                )
            return PositionImportService(session).import_snapshot(
                portfolio_id=resolved_id,
                as_of_date=as_of_date,
                parsed=parsed,
            )

    def list_portfolios(self) -> tuple[dict[str, object], ...]:
        with self._factory() as session:
            portfolios = session.scalars(select(Portfolio).order_by(Portfolio.id))
            return tuple(
                {
                    "id": item.id,
                    "portfolio_id": item.name,
                    "name": item.name,
                    "base_currency": item.base_currency,
                    "cash_balance": float(item.cash_balance),
                }
                for item in portfolios
            )

    def get_portfolio_status(self, portfolio_id: int | str) -> dict[str, object]:
        with self._factory() as session:
            resolved_id = self._resolve_portfolio_id(session, portfolio_id)
            portfolio = session.get(Portfolio, resolved_id)
            assert portfolio is not None
            latest_date = session.scalar(
                select(func.max(PortfolioPosition.as_of_date)).where(
                    PortfolioPosition.portfolio_id == resolved_id
                )
            )
            positions = (
                tuple(
                    session.scalars(
                        select(PortfolioPosition)
                        .where(
                            PortfolioPosition.portfolio_id == resolved_id,
                            PortfolioPosition.as_of_date == latest_date,
                        )
                        .order_by(PortfolioPosition.stock_id)
                    )
                )
                if latest_date is not None
                else ()
            )
            return {
                "id": portfolio.id,
                "portfolio_id": portfolio.name,
                "name": portfolio.name,
                "currency": portfolio.base_currency,
                "cash": float(portfolio.cash_balance),
                "nav": float(portfolio.cash_balance) if not positions else None,
                "invested": 0.0 if not positions else None,
                "cash_weight": 1.0 if not positions and portfolio.cash_balance > 0 else None,
                "as_of": latest_date,
                "positions": tuple(
                    {
                        "symbol": item.stock.symbol,
                        "shares": float(item.quantity),
                        "average_cost": (
                            float(item.average_cost) if item.average_cost is not None else None
                        ),
                    }
                    for item in positions
                ),
            }

    @staticmethod
    def _resolve_portfolio_id(session: Session, portfolio_id: int | str) -> int:
        portfolio = (
            session.get(Portfolio, portfolio_id)
            if isinstance(portfolio_id, int)
            else session.scalar(select(Portfolio).where(Portfolio.name == portfolio_id.strip()))
        )
        if portfolio is None:
            raise ValueError(f"portfolio does not exist: {portfolio_id}")
        return portfolio.id

    def get_action_candidates(self) -> tuple[CandidateView, ...]:
        with self._factory() as session:
            return DecisionService(session).get_action_candidates()

    def accept_candidate(self, recommendation_id: str, reason: str = "") -> str:
        return self._review(recommendation_id, UserDecision.ACCEPTED, reason)

    def reject_candidate(self, recommendation_id: str, reason: str = "") -> str:
        return self._review(recommendation_id, UserDecision.REJECTED, reason)

    def watch_candidate(self, recommendation_id: str, reason: str = "") -> str:
        return self._review(recommendation_id, UserDecision.WATCH, reason)

    def mark_candidate_executed(
        self,
        recommendation_id: str,
        *,
        actual_price: float,
        quantity: float,
        fees: float = 0.0,
        executed_at: datetime | None = None,
        notes: str = "",
        fill_id: str | None = None,
        external_reference: str | None = None,
        override_provenance: str | None = None,
    ) -> str:
        with self._factory.begin() as session:
            return DecisionService(session).mark_executed(
                recommendation_id,
                actual_price=actual_price,
                quantity=quantity,
                fees=fees,
                executed_at=executed_at,
                notes=notes,
                fill_id=fill_id,
                external_reference=external_reference,
                override_provenance=override_provenance,
            )

    def cancel_candidate_execution(self, recommendation_id: str, *, reason: str) -> str:
        with self._factory.begin() as session:
            metrics = ManualExecutionOrderService(session).cancel(
                recommendation_id,
                reason=reason,
            )
            return f"Manual execution {metrics.order_id}: {metrics.status.value}"

    def modify_candidate_execution(
        self,
        recommendation_id: str,
        *,
        approved_quantity: float,
        reason: str,
    ) -> str:
        with self._factory.begin() as session:
            metrics = ManualExecutionOrderService(session).modify_quantity(
                recommendation_id,
                approved_quantity=approved_quantity,
                reason=reason,
            )
            return (
                f"Manual execution {metrics.order_id}: {metrics.status.value}; "
                f"approved quantity={metrics.approved_quantity:g}"
            )

    def run_backtest(self, **parameters: object) -> object:
        with self._factory.begin() as session:
            return BacktestService(session).run_backtest(**parameters)  # type: ignore[arg-type]

    def get_pipeline_runs(self, limit: int = 20) -> tuple[dict[str, object], ...]:
        with self._factory() as session:
            runs = session.scalars(
                select(DailyPipelineRun).order_by(DailyPipelineRun.start_time.desc()).limit(limit)
            )
            return tuple(
                {"id": run.id, "date": run.run_date, "status": run.status, "summary": run.summary}
                for run in runs
            )

    def get_recent_errors(self) -> tuple[str, ...]:
        with self._factory() as session:
            return DiagnosticService(session, self._settings).recent_errors()

    def export_diagnostic_bundle(self, destination: Path | None = None) -> Path:
        with self._factory() as session:
            return DiagnosticService(session, self._settings).export_bundle(destination)

    def get_diagnostic_summary(self) -> dict[str, object]:
        with self._factory() as session:
            return DiagnosticService(session, self._settings).summary()

    def get_intelligence_status(self) -> dict[str, object]:
        with self._factory() as session:
            return IntelligenceApplicationService(session).status()

    def get_latest_opportunity_scan(self) -> dict[str, object]:
        with self._factory() as session:
            return IntelligenceApplicationService(session).latest_scan()

    def _review(self, recommendation_id: str, decision: UserDecision, reason: str) -> str:
        with self._factory.begin() as session:
            history = DecisionRepository(session).review(
                recommendation_id=recommendation_id,
                decision=decision,
                decided_at=datetime.now(UTC),
                reason=reason,
            )
            return history.decision

    def _data_service(self, session: Session) -> DataService:
        return DataService(
            session,
            self._settings,
            snapshot_root=self._snapshot_root,
            sync_runner=self._sync_runner,
        )

    @staticmethod
    def _model_status(session: Session, data_ready: bool) -> StatusDetail:
        latest = session.scalar(
            select(QuantDecisionRun).order_by(QuantDecisionRun.as_of_time.desc()).limit(1)
        )
        if not data_ready:
            return StatusDetail.build(
                ModelStatus.INSUFFICIENT_DATA,
                "模型等待数据",
                "没有生成候选；量化核心不会使用占位数据。",
                "research data unavailable",
                "先完成数据初始化和质量检查",
            )
        if latest is None:
            return StatusDetail.build(
                ModelStatus.NOT_RUN,
                "模型尚未运行",
                "研究数据可读，但尚无合格的每日决策结果。",
                "quant_decision_runs is empty",
                "运行每日流水线",
                allow_research=True,
            )
        if latest.status == "generated" and latest.gate_status == "APPROVED":
            return StatusDetail.build(
                ModelStatus.READY,
                "模型已就绪",
                "候选只来自 PRODUCTION_APPROVED Alpha。",
                f"run={latest.id}; model={latest.model_version}",
                "人工复核候选",
                allow_research=True,
                allow_candidates=True,
                updated_at=latest.as_of_time,
            )
        return StatusDetail.build(
            ModelStatus.INSUFFICIENT_DATA,
            "研究门禁未通过",
            "数据可用于受限研究，但不能生成目标组合候选。",
            "; ".join(latest.blockers) or latest.gate_status,
            "补齐 PIT 股票池、公司行动和总回报认证",
            allow_research=True,
        )
