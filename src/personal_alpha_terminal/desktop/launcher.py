import argparse
import os
import sys
import threading
import traceback
import webbrowser
from datetime import date
from pathlib import Path

from personal_alpha_terminal.desktop.recovery import (
    RecoveryStatus,
    build_recovery_server,
)
from personal_alpha_terminal.desktop.runtime import (
    DEFAULT_HOST,
    bootstrap_user_environment,
    bundled_dashboard_path,
    choose_dashboard_port,
    pid_file,
    process_matches_instance,
    read_instance,
    stage_update,
    stop_running_instance,
    write_instance,
)


def _message(title: str, body: str) -> None:
    if os.environ.get("PAT_SILENT", "").lower() in {"1", "true", "yes"}:
        return
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, body, title, 0x40)
    else:
        print(f"{title}: {body}")


def start() -> int:
    existing = read_instance()
    if existing is not None and process_matches_instance(existing):
        webbrowser.open(existing.url)
        return 0
    pid_file().unlink(missing_ok=True)

    try:
        bootstrap_user_environment()
    except Exception as error:
        return _run_recovery_dashboard(
            stage="environment-initialization",
            error=error,
            guidance="请在 System Status 中检查配置、数据库和日志目录。",
        )
    _launcher_trace("launcher:bootstrap-returned")
    dashboard = bundled_dashboard_path()
    if not dashboard.exists():
        return _run_recovery_dashboard(
            stage="dashboard-entrypoint",
            error=FileNotFoundError(str(dashboard)),
            guidance="应用文件不完整，请重新安装或完整解压 portable 目录。",
        )
    asset_error = _runtime_asset_error(dashboard)
    if asset_error is not None:
        return _run_recovery_dashboard(
            stage="runtime-assets",
            error=asset_error,
            guidance=(
                "检测到不完整的压缩包临时解压。请运行安装程序，或先完整解压 portable "
                "目录后再双击 PersonalAlphaTerminal.exe。"
            ),
        )
    port = choose_dashboard_port()
    dashboard_url = f"http://{DEFAULT_HOST}:{port}"
    instance = write_instance(dashboard_url)
    _launcher_trace(f"launcher:pid-written:{instance.pid}:{dashboard_url}")

    def open_browser() -> None:
        webbrowser.open(dashboard_url)

    if os.environ.get("PAT_NO_BROWSER", "").lower() not in {"1", "true", "yes"}:
        browser_timer = threading.Timer(1.5, open_browser)
        browser_timer.daemon = True
        browser_timer.start()
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    sys.argv = [
        "streamlit",
        "run",
        str(dashboard),
        f"--server.address={DEFAULT_HOST}",
        f"--server.port={port}",
        "--server.headless=true",
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
    ]
    try:
        _launcher_trace("launcher:streamlit-import")
        from streamlit.web.cli import main

        _launcher_trace("launcher:streamlit-main")
        main()
        _launcher_trace("launcher:streamlit-returned")
    except Exception:
        formatted = traceback.format_exc()
        _launcher_trace(f"launcher:error\n{formatted}")
        return 1
    finally:
        current = read_instance()
        if current is not None and current.pid == os.getpid():
            pid_file().unlink(missing_ok=True)
        _launcher_trace("launcher:pid-removed")
    return 0


def _runtime_asset_error(dashboard: Path) -> Exception | None:
    if not dashboard.is_file():
        return FileNotFoundError(str(dashboard))
    try:
        from streamlit import file_util

        static_directory = Path(file_util.get_static_dir())
    except Exception as error:
        return error
    index = static_directory / "index.html"
    if not index.is_file():
        return FileNotFoundError(f"Streamlit static entrypoint is missing: {index}")
    return None


def _run_recovery_dashboard(
    *,
    stage: str,
    error: Exception,
    guidance: str,
) -> int:
    formatted = "".join(traceback.format_exception(error))
    _launcher_trace(f"launcher:recovery:{stage}:{type(error).__name__}\n{formatted}")
    port = choose_dashboard_port()
    dashboard_url = f"http://{DEFAULT_HOST}:{port}"
    write_instance(dashboard_url)
    if os.environ.get("PAT_NO_BROWSER", "").lower() not in {"1", "true", "yes"}:
        browser_timer = threading.Timer(0.4, lambda: webbrowser.open(dashboard_url))
        browser_timer.daemon = True
        browser_timer.start()
    server = build_recovery_server(
        DEFAULT_HOST,
        port,
        RecoveryStatus(stage, type(error).__name__, guidance),
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        return 1
    finally:
        server.server_close()
        current = read_instance()
        if current is not None and current.pid == os.getpid():
            pid_file().unlink(missing_ok=True)
    return 1


def _launcher_trace(message: str) -> None:
    root = pid_file().parent
    try:
        with (root / "boot.log").open("a", encoding="utf-8") as stream:
            stream.write(f"{message}\n")
    except OSError:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--update", action="store_true")
    parser.add_argument("--daily-pipeline", action="store_true")
    parser.add_argument("--pipeline-as-of-date", type=date.fromisoformat, default=None)
    args, _ = parser.parse_known_args()
    if args.stop:
        stopped = stop_running_instance()
        _message(
            "Personal Alpha Terminal",
            "终端已关闭。" if stopped else "没有发现正在运行的终端。",
        )
        raise SystemExit(0)
    if args.update:
        success, message = stage_update()
        _message("Personal Alpha Terminal 更新", message)
        raise SystemExit(0 if success else 1)
    if args.daily_pipeline:
        try:
            settings = bootstrap_user_environment()
            from personal_alpha_terminal.automation.service import run_daily_pipeline

            result = run_daily_pipeline(
                settings=settings,
                as_of_date=args.pipeline_as_of_date,
                trigger="scheduler",
            )
        except Exception:
            _launcher_trace(f"daily-pipeline:error\n{traceback.format_exc()}")
            raise SystemExit(1) from None
        has_task_failure = any(
            status == "failed" for status in result.task_statuses.values()
        )
        raise SystemExit(2 if result.status == "failed" or has_task_failure else 0)
    raise SystemExit(start())


if __name__ == "__main__":
    main()
