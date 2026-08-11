"""UI-independent application services for console and compatibility frontends."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from personal_alpha_terminal.application.app_service import ApplicationService
    from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator
    from personal_alpha_terminal.application.daily_result import DailyQuantResult

__all__ = ["ApplicationService", "DailyQuantOrchestrator", "DailyQuantResult"]


def __getattr__(name: str) -> object:
    """Keep public exports lazy so lower layers can use focused application services."""

    if name == "ApplicationService":
        from personal_alpha_terminal.application.app_service import ApplicationService

        return ApplicationService
    if name == "DailyQuantOrchestrator":
        from personal_alpha_terminal.application.daily_orchestrator import DailyQuantOrchestrator

        return DailyQuantOrchestrator
    if name == "DailyQuantResult":
        from personal_alpha_terminal.application.daily_result import DailyQuantResult

        return DailyQuantResult
    raise AttributeError(name)
