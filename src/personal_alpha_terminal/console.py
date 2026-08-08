"""Windows terminal product entry point; never opens a browser or submits orders."""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from personal_alpha_terminal.core.logging import configure_logging, log_application_start_once
from personal_alpha_terminal.core.retention import prune_generated_artifacts
from personal_alpha_terminal.core.runtime_bootstrap import (
    application_data_dir,
    bootstrap_user_environment,
)
from personal_alpha_terminal.terminal.config import user_config_text
from personal_alpha_terminal.terminal.instance import ConsoleInstanceLock

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


def _dispatch_command(arguments: list[str], config_path: Path) -> int:
    from personal_alpha_terminal.terminal.cli import main as terminal_main

    return terminal_main(["--config", str(config_path), *arguments])


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments == ["version"] or any(item in {"-h", "--help"} for item in arguments):
        return _dispatch_command(arguments, Path("config.yaml"))
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
        with ConsoleInstanceLock():
            return _dispatch_command(arguments or ["daily"], config_path)
    except Exception as error:
        try:
            root = application_data_dir()
            root.mkdir(parents=True, exist_ok=True)
            with (root / "boot.log").open("a", encoding="utf-8") as stream:
                stream.write("bootstrap:fatal\n")
                stream.write(traceback.format_exc())
                stream.write("\n")
        except OSError:
            pass
        logger.exception("Terminal startup failed")
        console.print(
            Panel(
                "程序无法安全启动。请运行 PersonalAlphaTerminal.exe doctor，"
                "并查看用户日志目录。\n"
                f"诊断代码：{type(error).__name__}",
                title="Personal Alpha Terminal - STARTUP BLOCKED",
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
