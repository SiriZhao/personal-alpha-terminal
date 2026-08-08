from textual.app import ComposeResult
from textual.widgets import Static

from personal_alpha_terminal.tui.screens.base import BaseScreen


class BacktestScreen(BaseScreen):
    def compose_body(self) -> ComposeResult:
        yield Static("[b]回测中心[/b]", classes="panel-title")
        yield Static(
            "严格 PIT 授权未通过时，本页保持 BLOCKED。\n"
            "不会使用当前成分股、未来复权或 T 日收盘成交来伪造专业结果。",
            classes="panel",
        )
