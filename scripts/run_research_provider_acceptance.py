"""Run a provider-neutral historical research provider acceptance audit."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from personal_alpha_terminal.quant_engine.research_dataset import (
    import_research_package,
    persist_research_dataset,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderAcceptanceStatus,
    ProviderContract,
    accept_research_provider,
    persist_provider_acceptance,
)


def _contract(path: Path) -> ProviderContract:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("provider contract must be a JSON object")
    return ProviderContract(**document)


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="CSV, Parquet, or SQLite research package")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("var/research-data/acceptance"))
    parser.add_argument("--required-start", default=None)
    parser.add_argument("--required-end", default=None)
    parser.add_argument("--cutoff", default=None)
    args = parser.parse_args()
    package = import_research_package(args.source)
    evidence = accept_research_provider(
        package,
        _contract(args.contract),
        required_start=_optional_date(args.required_start),
        required_end=_optional_date(args.required_end),
        evaluated_at=(
            datetime.fromisoformat(args.cutoff).astimezone()
            if args.cutoff
            else None
        ),
    )
    acceptance_path = persist_provider_acceptance(evidence, args.output)
    persist_research_dataset(package, evidence.manifest, args.output / "datasets")
    print(f"acceptance_id={evidence.acceptance_id}")
    print(f"status={evidence.status.value}")
    print(f"content_hash={evidence.content_hash}")
    print(f"acceptance_path={acceptance_path.resolve()}")
    for blocker in evidence.blockers:
        print(f"blocker={blocker}")
    for warning in evidence.warnings:
        print(f"warning={warning}")
    return 0 if evidence.status is not ProviderAcceptanceStatus.NOT_CERTIFIABLE else 3


if __name__ == "__main__":
    raise SystemExit(main())
