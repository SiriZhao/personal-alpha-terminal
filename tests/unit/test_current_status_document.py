import json
from pathlib import Path

from personal_alpha_terminal.core.status_document import render_current_status


def test_current_status_markdown_is_generated_from_canonical_json() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "docs/CURRENT_STATUS.json").read_text(encoding="utf-8"))
    rendered = render_current_status(payload)

    assert (root / "docs/CURRENT_STATUS.md").read_text(encoding="utf-8") == rendered
    assert payload["capabilities"]["Live Capital"]["state"] == "DISABLED"
    assert "LIVE_CAPITAL_NOT_APPROVED" in rendered
