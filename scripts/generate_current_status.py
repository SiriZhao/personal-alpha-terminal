from __future__ import annotations

import argparse
import json
from pathlib import Path

from personal_alpha_terminal.core.status_document import render_current_status


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize CURRENT_STATUS.md from JSON")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "docs" / "CURRENT_STATUS.json"
    target = root / "docs" / "CURRENT_STATUS.md"
    rendered = render_current_status(json.loads(source.read_text(encoding="utf-8")))
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != rendered:
            raise SystemExit("CURRENT_STATUS.md is not synchronized with CURRENT_STATUS.json")
    else:
        target.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
