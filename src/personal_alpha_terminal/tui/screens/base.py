from __future__ import annotations

from typing import TYPE_CHECKING, cast

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static

from personal_alpha_terminal.tui.widgets import StatusHeader

if TYPE_CHECKING:
    from personal_alpha_terminal.tui.app import PersonalAlphaTerminalApp


class BaseScreen(Screen[None]):
    @property
    def pat_app(self) -> PersonalAlphaTerminalApp:
        return cast("PersonalAlphaTerminalApp", self.app)

    def compose(self) -> ComposeResult:
        yield StatusHeader(id="status-header", markup=True)
        with Horizontal(id="nav"):
            yield Button("1 今日", id="nav-dashboard")
            yield Button("2 数据", id="nav-data")
            yield Button("3 决策复核", id="nav-actions")
            yield Button("5 回测", id="nav-backtest")
            yield Button("6 诊断", id="nav-diagnostics")
            yield Button("7 设置", id="nav-settings")
        with VerticalScroll(id="body"):
            yield from self.compose_body()
        yield Footer()

    def compose_body(self) -> ComposeResult:
        yield Static("加载中…")

    def on_mount(self) -> None:
        self.refresh_header()

    def refresh_header(self) -> None:
        readiness = self.pat_app.service.get_system_health()
        self.query_one(StatusHeader).update_readiness(
            readiness, self.pat_app.service.get_market_session_status()
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        target = {
            "nav-dashboard": "dashboard",
            "nav-data": "data",
            "nav-actions": "actions",
            "nav-backtest": "backtest",
            "nav-diagnostics": "diagnostics",
            "nav-settings": "settings",
        }.get(event.button.id or "")
        if target:
            self.pat_app.switch_screen(target)
