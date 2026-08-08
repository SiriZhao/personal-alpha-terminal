from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Button, DataTable, Static

from personal_alpha_terminal.tui.screens.base import BaseScreen


class ActionCenterScreen(BaseScreen):
    def compose_body(self) -> ComposeResult:
        yield Static(
            "[b]行动中心[/b]  候选只来自确定性量化流水线",
            classes="panel-title",
        )
        yield Static(
            "AI 未配置不影响量化功能；AI 不能改变候选、权重或风险结论。",
            classes="panel",
        )
        yield DataTable(id="action-table")
        yield Button("接受选中项", id="accept", variant="success")
        yield Button("拒绝选中项", id="reject", variant="error")
        yield Button("观察选中项", id="watch")
        yield Static("", id="action-message", classes="panel")

    def on_mount(self) -> None:
        super().on_mount()
        table = self.query_one("#action-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "标的",
            "方向",
            "目标权重",
            "量化分",
            "置信等级",
            "数据版本",
            "状态",
        )
        self.refresh_actions()

    def refresh_actions(self) -> None:
        table = self.query_one("#action-table", DataTable)
        table.clear()
        for item in self.pat_app.service.get_action_candidates():
            table.add_row(
                item.ticker,
                item.action,
                f"{item.target_weight:.2%}",
                f"{item.quant_score:.1f}",
                item.evidence_grade,
                item.data_version,
                "可复核" if item.executable else f"受阻：{item.blocked_reason}",
                key=item.recommendation_id,
            )
        if table.row_count == 0:
            table.add_row(
                "--",
                "--",
                "--",
                "--",
                "证据不足",
                "--",
                "No Decision Generated",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id not in {"accept", "reject", "watch"}:
            return
        table = self.query_one("#action-table", DataTable)
        if table.cursor_row is None or not table.rows:
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        if row_key is None:
            return
        try:
            result = {
                "accept": self.pat_app.service.accept_candidate,
                "reject": self.pat_app.service.reject_candidate,
                "watch": self.pat_app.service.watch_candidate,
            }[event.button.id](str(row_key))
            if event.button.id == "accept":
                result += (
                    "\n已进入 Pending Manual Execution；请在 Charles Schwab "
                    "人工下单，系统不会连接券商。"
                )
        except Exception as error:
            result = f"操作未执行：{error}"
        self.query_one("#action-message", Static).update(result)
        self.refresh_actions()
