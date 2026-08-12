"""Run provider acceptance for a licensed local market-data research package."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from personal_alpha_terminal.quant_engine.research_dataset import (
    persist_research_dataset,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderAcceptanceStatus,
    ProviderContract,
    accept_research_provider,
    persist_provider_acceptance,
)
from personal_alpha_terminal.quant_engine.research_provider_adapters import (
    LocalResearchPackageAdapter,
    verify_raw_landing_zone,
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
    parser.add_argument("source", type=Path, help="normalized CSV/Parquet/SQLite package")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--provider-version", required=True)
    parser.add_argument("--raw-root", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("var/research-data/acceptance"))
    parser.add_argument("--required-start", default=None)
    parser.add_argument("--required-end", default=None)
    parser.add_argument("--cutoff", default=None)
    args = parser.parse_args()

    contract = _contract(args.contract)
    adapter = LocalResearchPackageAdapter(contract, args.provider_version)
    if args.raw_root is not None:
        verification = verify_raw_landing_zone(args.raw_root)
        if not verification.ok:
            print("RAW_LANDING_ZONE_FAIL")
            for blocker in verification.blockers:
                print(f"blocker={blocker}")
            return 3
    package = adapter.load(args.source)
    evidence = accept_research_provider(
        package,
        contract,
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
