from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from personal_alpha_terminal.core.config import Settings, get_settings  # noqa: E402
from personal_alpha_terminal.core.product import UserPreferences  # noqa: E402
from personal_alpha_terminal.dashboard.startup import assess_startup  # noqa: E402
from personal_alpha_terminal.data.database import configure_database  # noqa: E402


@pytest.mark.parametrize(
    ("case", "database_ready", "configuration_exists", "gate_status", "reasons"),
    (
        ("first_install", False, False, "BLOCKED", ()),
        ("no_database", False, True, "BLOCKED", ("database unavailable",)),
        ("no_ai_key", True, True, "RESEARCH_ONLY", ()),
        ("no_market_data", True, True, "BLOCKED", ("no certified prices",)),
        ("data_blocked", True, True, "BLOCKED", ("quality validation failed",)),
    ),
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_optional_setup_never_blocks_dashboard_access(
    case: str,
    database_ready: bool,
    configuration_exists: bool,
    gate_status: str,
    reasons: tuple[str, ...],
) -> None:
    del case

    state = assess_startup(
        database_ready=database_ready,
        configuration_exists=configuration_exists,
        data_gate_status=gate_status,
        gate_reasons=reasons,
    )

    assert state.can_enter_dashboard
    if not database_ready or gate_status == "BLOCKED":
        assert state.data_gate_status == "BLOCKED"


def test_first_install_without_database_or_ai_key_renders_main_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PAT_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("PAT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("PAT_LLM_PROVIDER", "disabled")
    monkeypatch.setattr(
        "personal_alpha_terminal.core.logging.configure_logging",
        lambda _settings: None,
    )
    get_settings.cache_clear()
    configure_database(Settings(_env_file=None, database_url="sqlite://", llm_provider="disabled"))
    app_path = (
        Path(__file__).parents[2]
        / "src"
        / "personal_alpha_terminal"
        / "dashboard"
        / "app.py"
    )

    try:
        app = AppTest.from_file(app_path, default_timeout=30).run()
        assert not app.exception
        rendered = "\n".join(
            [
                *(item.value for item in app.title),
                *(item.value for item in app.subheader),
                *(item.value for item in app.markdown),
                *(item.value for item in app.caption),
            ]
        )
        errors = "\n".join(item.value for item in app.error)
        assert "欢迎使用 Personal Alpha Terminal" in rendered
        assert "今日投资驾驶舱" in rendered
        assert "我已了解，进入系统" not in rendered
        assert "Data Gate: BLOCKED" in errors or "Data Gate · BLOCKED" in rendered
        assert UserPreferences().ai_provider == "disabled"
    finally:
        get_settings.cache_clear()


def test_blocking_onboarding_component_is_removed() -> None:
    root = Path(__file__).parents[2]
    dashboard = root / "src" / "personal_alpha_terminal" / "dashboard"
    app_source = dashboard.joinpath("app.py").read_text(encoding="utf-8")
    home_source = dashboard.joinpath("pages", "daily_dashboard.py").read_text(
        encoding="utf-8"
    )

    assert not dashboard.joinpath("onboarding.py").exists()
    assert "render_first_run_wizard" not in app_source
    assert "notice_is_required" not in app_source
    assert "require_database()" not in home_source
    assert "开始配置" in home_source
    assert "查看数据状态" in home_source
    assert "关闭" in home_source
    assert "disabled=" not in home_source
