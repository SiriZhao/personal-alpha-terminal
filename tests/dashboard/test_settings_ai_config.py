from pathlib import Path

import pytest

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from personal_alpha_terminal.core.config import get_settings  # noqa: E402


def test_ai_configuration_saves_without_plaintext_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PAT_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("PAT_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(
        "personal_alpha_terminal.core.credentials.read_api_key",
        lambda _provider: None,
    )
    get_settings.cache_clear()
    page = (
        Path(__file__).parents[2]
        / "src"
        / "personal_alpha_terminal"
        / "dashboard"
        / "pages"
        / "settings.py"
    )

    try:
        app = AppTest.from_file(page, default_timeout=30).run()
        assert not app.exception
        app.selectbox[3].select("mock")
        save = next(button for button in app.button if button.label == "保存设置")
        app = save.click().run()
        assert not app.exception

        config_path = tmp_path / "PersonalAlphaTerminal" / "config.env"
        config = config_path.read_text(encoding="utf-8")
        assert "PAT_LLM_PROVIDER=mock" in config
        assert "API_KEY" not in config
    finally:
        get_settings.cache_clear()
