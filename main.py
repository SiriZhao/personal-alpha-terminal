"""Windows-friendly terminal entry point; it never starts a browser or Streamlit."""

from __future__ import annotations

import sys


def _fast_startup_banner() -> None:
    """Print an immediate unbuffered first line before heavy CLI imports."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (OSError, ValueError, AttributeError):
        pass
    command = sys.argv[1] if len(sys.argv) > 1 else "daily"
    if command in {"daily", "refresh"}:
        print("PERSONAL ALPHA TERMINAL | starting...", flush=True)


def _run() -> int:
    _fast_startup_banner()
    from personal_alpha_terminal.terminal.cli import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_run())
