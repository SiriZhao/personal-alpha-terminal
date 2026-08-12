"""Export the official-evidence market-data provider selection matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from personal_alpha_terminal.quant_engine.provider_selection import (
    provider_capability_claims,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/latest/provider_selection_matrix.json"),
    )
    args = parser.parse_args()
    documents = [item.document() for item in provider_capability_claims()]
    rendered = json.dumps(
        {
            "schema_version": "provider-selection-matrix-v1",
            "claims": documents,
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(args.output.resolve())
    print(f"claims={len(documents)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
