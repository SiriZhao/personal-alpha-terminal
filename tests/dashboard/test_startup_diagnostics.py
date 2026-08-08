from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from personal_alpha_terminal.dashboard.startup_diagnostics import (  # noqa: E402
    initialize_dashboard,
)


def test_configuration_exception_returns_safe_initialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "personal_alpha_terminal.dashboard.startup_diagnostics.get_settings",
        lambda: (_ for _ in ()).throw(ValueError("invalid optional provider config")),
    )

    initialization = initialize_dashboard()

    assert initialization.settings is None
    assert initialization.issues[0].component == "Configuration"
    assert initialization.issues[0].error_type == "ValueError"


def test_app_renders_safe_system_status_when_config_initialization_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "personal_alpha_terminal.dashboard.startup_diagnostics.get_settings",
        lambda: (_ for _ in ()).throw(ValueError("invalid optional provider config")),
    )
    app_path = (
        Path(__file__).parents[2]
        / "src"
        / "personal_alpha_terminal"
        / "dashboard"
        / "app.py"
    )

    app = AppTest.from_file(app_path, default_timeout=30).run()

    assert not app.exception
    rendered = "\n".join(
        [
            *(item.value for item in app.title),
            *(item.value for item in app.markdown),
            *(item.value for item in app.caption),
        ]
    )
    assert "Personal Alpha Terminal" in rendered
    assert "Safe Startup Diagnostics" in rendered
    assert any(metric.label == "Data Gate" and metric.value == "BLOCKED" for metric in app.metric)
