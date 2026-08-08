from datetime import date, timedelta

from textual import work
from textual.app import ComposeResult
from textual.widgets import Button, DataTable, Static

from personal_alpha_terminal.tui.screens.base import BaseScreen


class DataCenterScreen(BaseScreen):
    def compose_body(self) -> ComposeResult:
        yield Static("[b]数据中心[/b]  T 测试连接 / I 初始化 / S 增量同步", classes="panel-title")
        yield Static("读取数据状态…", id="data-summary", classes="panel")
        yield Button("初始化最小研究池", id="initialize-data", variant="primary")
        yield Button("增量同步（30天）", id="sync-data")
        yield DataTable(id="snapshot-table")
        yield Static("", id="data-message", classes="panel")

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#snapshot-table", DataTable).add_columns(
            "快照", "Provider", "范围", "接收", "拒绝", "认证"
        )
        self.refresh_data()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id == "initialize-data":
            self.initialize_data()
        elif event.button.id == "sync-data":
            self.sync_data()

    @work(thread=True, exclusive=True, group="data")
    def initialize_data(self) -> None:
        self.app.call_from_thread(self._show_message, "开始初始化，请勿关闭程序…")
        try:
            result = self.pat_app.service.initialize_research_database()
        except Exception as error:
            self.app.call_from_thread(self._show_message, f"初始化失败：{error}")
            return
        self.app.call_from_thread(
            self._show_message,
            f"完成：{result.status}，接收 {result.accepted_rows} 行；{result.manifest_path}",
        )
        self.app.call_from_thread(self.refresh_data)

    @work(thread=True, exclusive=True, group="data")
    def sync_data(self) -> None:
        end = date.today()
        try:
            result = self.pat_app.service.sync_market_data(
                start_date=end - timedelta(days=30), end_date=end
            )
        except Exception as error:
            self.app.call_from_thread(self._show_message, f"同步失败：{error}")
            return
        self.app.call_from_thread(self._show_message, f"同步完成：{result.status}")
        self.app.call_from_thread(self.refresh_data)

    def refresh_data(self) -> None:
        status = self.pat_app.service.get_data_readiness()
        self.query_one("#data-summary", Static).update(
            f"[b]{status.code} · {status.title_zh}[/b]\n{status.summary}\n"
            f"技术原因：{status.technical_reason}\n建议：{status.repair_action}"
        )

    def _show_message(self, message: str) -> None:
        self.query_one("#data-message", Static).update(message)
