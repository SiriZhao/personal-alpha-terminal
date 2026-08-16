"""Write the ROUND29 frozen LLM-output replay artifact (no external calls)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from personal_alpha_terminal.application.round29_replay import replay_round29_brief


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-id",
        default="daily-c3c0107d1d7641b49bbb81c32615fbbc",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run_dir = root / "reports" / "daily-runs" / args.run_id
    report = replay_round29_brief(run_dir)
    output = root / "reports" / "validation-artifacts" / "round29_frozen_replay.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
