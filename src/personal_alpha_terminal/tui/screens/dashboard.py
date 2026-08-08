import logging

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Static

from personal_alpha_terminal.application.dashboard_service import DashboardView
from personal_alpha_terminal.tui.screens.base import BaseScreen
from personal_alpha_terminal.tui.widgets import StatusHeader

logger = logging.getLogger(__name__)


class DashboardScreen(BaseScreen):
    """Today-first dashboard; unavailable data never becomes an onboarding wall."""

    def compose_body(self) -> ComposeResult:
        yield Static("[b]今日量化研究驾驶舱[/b]", classes="panel-title")
        yield Static("正在读取系统状态…", id="system-summary", classes="panel")
        yield Static("正在读取今日任务…", id="tasks", classes="panel")
        with Horizontal(id="primary-row"):
            yield Static("市场状态\n等待模型", id="market-panel", classes="panel")
            yield Static(
                "执行边界\n仅研究、历史回测与人工决策复核\n禁止自动交易",
                id="execution-panel",
                classes="panel",
            )
        yield Static("[b]经验证的量化候选[/b]", classes="panel-title")
        yield DataTable(id="candidates")

    def on_mount(self) -> None:
        super().on_mount()
        table = self.query_one("#candidates", DataTable)
        table.add_columns("标的", "方向", "当前权重", "目标权重", "证据", "状态")
        self.load_dashboard()

    @work(thread=True, exclusive=True, group="dashboard")
    def load_dashboard(self) -> None:
        view = self.pat_app.service.get_daily_dashboard()
        if self.pat_app.auto_initialize and view.readiness.data.code == "EMPTY":
            try:
                self.pat_app.service.initialize_research_database()
                view = self.pat_app.service.get_daily_dashboard()
            except Exception:
                logger.exception("First-run minimum data initialization failed")
                view = self.pat_app.service.get_daily_dashboard()
        self.pat_app.call_from_thread(self._render_dashboard, view)

    def _render_dashboard(self, view: DashboardView) -> None:
        readiness = view.readiness
        self.query_one(StatusHeader).update_readiness(readiness, view.market_session)
        self.query_one("#system-summary", Static).update(
            f"[b]数据完整性[/b] {readiness.data.title_zh}  |  "
            f"[b]今日流水线[/b] {view.latest_pipeline_status}\n"
            f"{readiness.data.summary}\n修复动作：{readiness.data.repair_action}"
        )
        tasks = "\n".join(f"{index}. {task}" for index, task in enumerate(view.tasks, 1))
        self.query_one("#tasks", Static).update(
            "[b]今日任务[/b]\n" + (tasks or "没有待处理任务")
        )
        self.query_one("#market-panel", Static).update(
            f"[b]市场状态评分[/b]\n{view.regime_label}\n未校准时不显示为概率"
        )
        portfolio = (
            f"{view.portfolio_name}\n现金：{view.portfolio_cash}\n"
            f"持仓记录：{view.portfolio_position_count}"
            if view.portfolio_name is not None
            else "尚未创建真实组合\n使用 portfolio-init / portfolio-import 维护"
        )
        self.query_one("#execution-panel", Static).update(
            "[b]真实组合 / 人工执行[/b]\n"
            f"{portfolio}\n接受候选不会连接券商；成交必须人工记录"
        )
        table = self.query_one("#candidates", DataTable)
        table.clear()
        for item in view.candidates:
            table.add_row(
                item.ticker,
                item.action,
                f"{item.current_weight:.2%}",
                f"{item.target_weight:.2%}",
                item.evidence_grade,
                "人工复核" if item.executable else f"受阻：{item.blocked_reason}",
                key=item.recommendation_id,
            )
        if not view.candidates:
            table.add_row("—", "—", "—", "—", "证据不足", "No Decision Generated")
