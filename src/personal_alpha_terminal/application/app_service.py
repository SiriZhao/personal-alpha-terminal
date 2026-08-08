from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.application.backtest_service import BacktestService
from personal_alpha_terminal.application.dashboard_service import DashboardView
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
from personal_alpha_terminal.application.pipeline_service import PipelineService
from personal_alpha_terminal.application.status import (
    ModelStatus,
    ProgramStatus,
    StatusDetail,
    SystemReadiness,
)
from personal_alpha_terminal.automation.runner import PipelineExecution
from personal_alpha_terminal.core.config import Settings, get_settings
from personal_alpha_terminal.decision_engine.repository import DecisionRepository
from personal_alpha_terminal.decision_engine.schemas import UserDecision
from personal_alpha_terminal.models import (
    DailyPipelineRun,
    Portfolio,
    PortfolioPosition,
    QuantDecisionRun,
)
from personal_alpha_terminal.portfolio.position_import import (
    PositionImportResult,
    PositionImportService,
    parse_position_csv,
)
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar


class ApplicationService:
    """Headless facade for research, backtests, diagnostics, and manual review.

    Paper trading was deliberately removed. Accepting a candidate records an
    immutable human decision; it never creates an order or changes a portfolio.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        settings: Settings | None = None,
        *,
        snapshot_root: Path | None = None,
        sync_runner: SyncRunner | None = None,
    ) -> None:
        self._factory = session_factory
        self._settings = settings or get_settings()
        self._snapshot_root = snapshot_root
        self._sync_runner = sync_runner

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
                    if data.code in {"PARTIAL", "STALE", "PROVIDER_ERROR"}
                    or model.code == "FAILED"
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
            nasdaq_23h_enabled=self._settings.nasdaq_23h_enabled,
            nasdaq_23h_effective_date=self._settings.nasdaq_23h_effective_date,
            night_execution_enabled=False,
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
    ) -> int:
        normalized = name.strip()
        if not normalized or cash_balance < 0:
            raise ValueError("portfolio name and non-negative cash are required")
        with self._factory.begin() as session:
            if session.scalar(select(Portfolio).where(Portfolio.name == normalized)) is not None:
                raise ValueError("portfolio name already exists")
            model = Portfolio(
                name=normalized,
                description="Manual Charles Schwab tracking; no broker connection",
                base_currency="USD",
                cash_balance=cash_balance,
            )
            session.add(model)
            session.flush()
            return model.id

    def import_portfolio_csv(
        self,
        *,
        portfolio_id: int,
        source: Path,
        as_of_date: date,
    ) -> PositionImportResult:
        parsed = parse_position_csv(source.read_bytes())
        with self._factory.begin() as session:
            return PositionImportService(session).import_snapshot(
                portfolio_id=portfolio_id,
                as_of_date=as_of_date,
                parsed=parsed,
            )

    def list_portfolios(self) -> tuple[dict[str, object], ...]:
        with self._factory() as session:
            portfolios = session.scalars(select(Portfolio).order_by(Portfolio.id))
            return tuple(
                {
                    "id": item.id,
                    "name": item.name,
                    "base_currency": item.base_currency,
                    "cash_balance": float(item.cash_balance),
                }
                for item in portfolios
            )

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
    ) -> str:
        with self._factory.begin() as session:
            return DecisionService(session).mark_executed(
                recommendation_id,
                actual_price=actual_price,
                quantity=quantity,
                fees=fees,
                executed_at=executed_at,
                notes=notes,
            )

    def run_backtest(self, **parameters: object) -> None:
        gate_approved = self.get_model_readiness().allow_candidates
        service = BacktestService()
        availability = service.availability(gate_approved=gate_approved)
        if not availability.available:
            raise RuntimeError(availability.reason)
        service.run_backtest(**parameters)

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
