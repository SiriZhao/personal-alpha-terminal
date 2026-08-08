import asyncio
from pathlib import Path

from personal_alpha_terminal.application import ApplicationService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.tui import PersonalAlphaTerminalApp


def test_empty_database_opens_today_dashboard_without_onboarding(
    session_factory, tmp_path: Path
) -> None:
    service = ApplicationService(
        session_factory,
        Settings(database_url="sqlite://"),
        snapshot_root=tmp_path,
    )
    async def scenario() -> None:
        app = PersonalAlphaTerminalApp(service)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            assert app.screen is app.get_screen("dashboard")

    asyncio.run(scenario())


def test_tui_keyboard_navigation_works_without_ai_key(
    session_factory, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    service = ApplicationService(
        session_factory,
        Settings(database_url="sqlite://", llm_provider="disabled"),
        snapshot_root=tmp_path,
    )
    async def scenario() -> None:
        app = PersonalAlphaTerminalApp(service)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("6")
            await pilot.pause()
            assert app.screen is app.get_screen("diagnostics")
            await pilot.press("2")
            await pilot.pause()
            assert app.screen is app.get_screen("data")

    asyncio.run(scenario())
