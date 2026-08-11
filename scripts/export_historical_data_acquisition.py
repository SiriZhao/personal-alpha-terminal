"""Export portable latest historical-research baseline and acquisition evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from personal_alpha_terminal.application.research_data_service import (
    acquire_available_historical_data,
)


def _write(document: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def export(
    config: Path, database: Path, runtime_root: Path, output_root: Path
) -> tuple[Path, Path]:
    baseline, acquisition, _baseline_path, _acquisition_path = (
        acquire_available_historical_data(
            config_path=config,
            database=database,
            root=runtime_root,
        )
    )
    baseline_path = output_root / "historical_research_baseline.json"
    acquisition_path = output_root / "historical_data_acquisition.json"
    _write(baseline.document(), baseline_path)
    _write(acquisition.document(), acquisition_path)
    return baseline_path, acquisition_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--database", type=Path, default=Path("var/personal_alpha.db"))
    parser.add_argument("--runtime-root", type=Path, default=Path("var/research-data"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/latest"))
    args = parser.parse_args()
    for path in export(args.config, args.database, args.runtime_root, args.output):
        print(path.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
