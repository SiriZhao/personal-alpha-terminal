from textual.app import ComposeResult
from textual.widgets import Button, RichLog, Static

from personal_alpha_terminal.tui.screens.base import BaseScreen


class DiagnosticsScreen(BaseScreen):
    def compose_body(self) -> ComposeResult:
        yield Static("[b]系统诊断[/b]", classes="panel-title")
        yield Static("", id="diagnostic-summary", classes="panel")
        yield Button("导出脱敏诊断包", id="export-diagnostics", variant="primary")
        yield RichLog(id="error-log", markup=True, wrap=True)

    def on_mount(self) -> None:
        super().on_mount()
        summary = self.pat_app.service.get_diagnostic_summary()
        self.query_one("#diagnostic-summary", Static).update(
            "\n".join(f"{key}: {value}" for key, value in summary.items())
        )
        log = self.query_one("#error-log", RichLog)
        for error in self.pat_app.service.get_recent_errors():
            log.write(error)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        super().on_button_pressed(event)
        if event.button.id == "export-diagnostics":
            path = self.pat_app.service.export_diagnostic_bundle()
            self.query_one("#diagnostic-summary", Static).update(f"诊断包已导出：{path}")
