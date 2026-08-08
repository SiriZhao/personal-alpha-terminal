"""Windows terminal product entry point; never opens a browser or submits orders."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from personal_alpha_terminal.application import ApplicationService
from personal_alpha_terminal.core.logging import configure_logging, log_application_start_once
from personal_alpha_terminal.core.retention import prune_generated_artifacts
from personal_alpha_terminal.data.database import get_session_factory
from personal_alpha_terminal.desktop.runtime import (
    application_data_dir,
    bootstrap_user_environment,
)
from personal_alpha_terminal.terminal.config import user_config_text
from personal_alpha_terminal.tui.app import PersonalAlphaTerminalApp
from personal_alpha_terminal.tui.instance import ConsoleInstanceLock

console = Console()
logger = logging.getLogger(__name__)


def _ensure_terminal_config(root: Path) -> Path:
    path = root / "config.yaml"
    (root / "cache").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    if not path.exists():
        temporary = path.with_suffix(".tmp")
        temporary.write_text(user_config_text(root), encoding="utf-8")
        temporary.replace(path)
    return path


async def _run_tui_smoke(app: PersonalAlphaTerminalApp) -> None:
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        if app.screen is not app.get_screen("dashboard"):
            raise RuntimeError("Today dashboard did not become the initial TUI screen")


def _dispatch_command(arguments: list[str], config_path: Path) -> int:
    from personal_alpha_terminal.terminal.cli import main as terminal_main

    return terminal_main(["--config", str(config_path), *arguments])


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        settings = bootstrap_user_environment()
        root = application_data_dir()
        config_path = _ensure_terminal_config(root)
        configure_logging(settings)
        log_application_start_once()
        try:
            removed = prune_generated_artifacts(root)
            if removed:
                logger.info("Pruned %d expired generated artifacts", len(removed))
        except OSError:
            logger.exception("Generated-artifact retention failed")
        if arguments:
            return _dispatch_command(arguments, config_path)
        service = ApplicationService(get_session_factory(), settings)
        smoke_test = os.environ.get("PAT_TUI_SMOKE_TEST") == "1"
        app = PersonalAlphaTerminalApp(service, auto_initialize=not smoke_test)
        if smoke_test:
            asyncio.run(_run_tui_smoke(app))
            console.print("TUI_SMOKE_OK")
            return 0
        with ConsoleInstanceLock():
            app.run()
        return 0
    except Exception as error:
        logger.exception("Terminal startup failed")
        console.print(
            Panel(
                "程序无法安全启动。运行 QuantTerminal.exe doctor 并查看用户日志目录。\n"
                f"诊断代码：{type(error).__name__}",
                title="Personal Alpha Terminal · STARTUP BLOCKED",
                border_style="red",
            )
        )
        if (
            getattr(sys, "frozen", False)
            and sys.stdin.isatty()
            and os.environ.get("PAT_NONINTERACTIVE") != "1"
        ):
            try:
                console.input("按 Enter 退出")
            except EOFError:
                pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
