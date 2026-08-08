from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from personal_alpha_terminal import __build_version__

PRODUCT_NAME = "Personal Alpha Terminal"
PRODUCT_CHANNEL = "Personal Quant Investment OS"
PRODUCT_DISPLAY_NAME = f"{PRODUCT_NAME} v{__build_version__} {PRODUCT_CHANNEL}"
FIRST_RUN_NOTICE = (
    "本系统用于个人量化投资研究与人工决策复核。分析依赖数据质量和模型假设，"
    "不构成投资建议；未通过数据门禁的信息不会生成组合行动建议。"
)


class RunMode(StrEnum):
    RESEARCH_PREVIEW = "research_preview"
    MOCK_DEMO = "mock_demo"
    OFFLINE = "offline"
    DATA_VALIDATION = "data_validation"


class ThemeMode(StrEnum):
    SYSTEM = "system"
    DARK = "dark"
    LIGHT = "light"


class MarketColorConvention(StrEnum):
    CHINA = "china"
    INTERNATIONAL = "international"


@dataclass(frozen=True, slots=True)
class UserPreferences:
    schema_version: int = 2
    # Kept for backward-compatible loading of 0.9.0 preference files. These
    # legacy fields no longer control navigation or application access.
    onboarding_completed: bool = False
    accepted_notice_version: str | None = None
    welcome_card_dismissed: bool = False
    run_mode: RunMode = RunMode.RESEARCH_PREVIEW
    theme: ThemeMode = ThemeMode.SYSTEM
    market_color_convention: MarketColorConvention = MarketColorConvention.INTERNATIONAL
    selected_markets: tuple[str, ...] = ("A", "HK", "US")
    ai_provider: str = "disabled"
    backup_directory: str | None = None
    backup_prompt_dismissed: bool = False
    exclude_position_amounts_from_diagnostics: bool = True
    allow_portfolio_evidence_to_ai: bool = False


def default_application_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "PersonalAlphaTerminal"
    return Path.home() / ".PersonalAlphaTerminal"


def preferences_path(root: Path | None = None) -> Path:
    return (root or default_application_data_dir()) / "user-preferences.json"


def load_preferences(root: Path | None = None) -> UserPreferences:
    path = preferences_path(root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return UserPreferences()
    if not isinstance(payload, dict):
        return UserPreferences()
    try:
        markets = payload.get("selected_markets", ("A", "HK", "US"))
        if not isinstance(markets, (list, tuple)):
            markets = ("A", "HK", "US")
        return UserPreferences(
            schema_version=int(payload.get("schema_version", 1)),
            onboarding_completed=bool(payload.get("onboarding_completed", False)),
            accepted_notice_version=_optional_string(payload.get("accepted_notice_version")),
            welcome_card_dismissed=bool(payload.get("welcome_card_dismissed", False)),
            run_mode=RunMode(str(payload.get("run_mode", RunMode.RESEARCH_PREVIEW))),
            theme=ThemeMode(str(payload.get("theme", ThemeMode.SYSTEM))),
            market_color_convention=MarketColorConvention(
                str(
                    payload.get(
                        "market_color_convention",
                        MarketColorConvention.INTERNATIONAL,
                    )
                )
            ),
            selected_markets=tuple(
                market for market in markets if str(market) in {"A", "HK", "US"}
            ),
            ai_provider=str(payload.get("ai_provider", "disabled")),
            backup_directory=_optional_string(payload.get("backup_directory")),
            backup_prompt_dismissed=bool(payload.get("backup_prompt_dismissed", False)),
            exclude_position_amounts_from_diagnostics=bool(
                payload.get("exclude_position_amounts_from_diagnostics", True)
            ),
            allow_portfolio_evidence_to_ai=bool(
                payload.get("allow_portfolio_evidence_to_ai", False)
            ),
        )
    except (TypeError, ValueError):
        return UserPreferences()


def save_preferences(preferences: UserPreferences, root: Path | None = None) -> Path:
    path = preferences_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _serialize(asdict(preferences))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _serialize(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value
