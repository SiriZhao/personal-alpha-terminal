from textual.app import ComposeResult
from textual.widgets import Static

from personal_alpha_terminal.tui.screens.base import BaseScreen


class SettingsScreen(BaseScreen):
    def compose_body(self) -> ComposeResult:
        yield Static("[b]设置[/b]", classes="panel-title")
        yield Static(
            "数据目录、Provider 优先级、研究成本/滑点假设、风险限制、AI 解释开关。\n\n"
            "AI API Key 使用 Windows Credential Manager 或环境变量；不会写入日志、诊断包或 EXE。\n"
            "AI 只能解释已生成的量化结果，不能改变排名、目标权重或风险结论。",
            classes="panel",
        )
