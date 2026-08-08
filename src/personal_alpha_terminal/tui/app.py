from __future__ import annotations

from textual.app import App

from personal_alpha_terminal.application import ApplicationService
from personal_alpha_terminal.tui.screens import (
    ActionCenterScreen,
    BacktestScreen,
    DashboardScreen,
    DataCenterScreen,
    DiagnosticsScreen,
    SettingsScreen,
)
from personal_alpha_terminal.tui.theme import APP_CSS


class PersonalAlphaTerminalApp(App[None]):
    CSS = APP_CSS
    TITLE = "Personal Alpha Terminal"
    SUB_TITLE = "Quant Research Core"
    BINDINGS = [
        ("1", "screen_dashboard", "今日"),
        ("2", "screen_data", "数据"),
        ("3", "screen_actions", "决策复核"),
        ("5", "screen_backtest", "回测"),
        ("6", "screen_diagnostics", "诊断"),
        ("7", "screen_settings", "设置"),
        ("q", "quit", "退出"),
    ]
    SCREENS = {
        "dashboard": DashboardScreen,
        "data": DataCenterScreen,
        "actions": ActionCenterScreen,
        "backtest": BacktestScreen,
        "diagnostics": DiagnosticsScreen,
        "settings": SettingsScreen,
    }

    def __init__(self, service: ApplicationService, *, auto_initialize: bool = False) -> None:
        super().__init__()
        self.service = service
        self.auto_initialize = auto_initialize

    def on_mount(self) -> None:
        # Empty or unsafe data is represented inside Today. It must not create
        # an onboarding wall that prevents diagnostics and configuration.
        self.push_screen("dashboard")

    def action_screen_dashboard(self) -> None:
        self.switch_screen("dashboard")

    def action_screen_data(self) -> None:
        self.switch_screen("data")

    def action_screen_actions(self) -> None:
        self.switch_screen("actions")

    def action_screen_backtest(self) -> None:
        self.switch_screen("backtest")

    def action_screen_diagnostics(self) -> None:
        self.switch_screen("diagnostics")

    def action_screen_settings(self) -> None:
        self.switch_screen("settings")
