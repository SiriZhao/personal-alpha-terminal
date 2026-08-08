from textual.widgets import Static

from personal_alpha_terminal.application.status import SystemReadiness


class StatusHeader(Static):
    def update_readiness(self, readiness: SystemReadiness, market_time: str) -> None:
        text = (
            "[b]Personal Alpha Terminal[/b]  "
            f"{market_time}\n"
            f"程序 [{_style(readiness.program.code)}]{readiness.program.code}[/]  "
            f"数据 [{_style(readiness.data.code)}]{readiness.data.code}[/]  "
            f"模型 [{_style(readiness.model.code)}]{readiness.model.code}[/]  "
            f"更新 {readiness.data.updated_at:%Y-%m-%d %H:%M UTC}"
        )
        self.update(text)


def _style(code: str) -> str:
    if code in {"READY", "CERTIFIED"}:
        return "green"
    if code in {"ERROR", "PROVIDER_ERROR", "FAILED"}:
        return "red"
    return "yellow"
