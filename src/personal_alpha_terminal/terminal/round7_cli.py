"""CLI handlers for ROUND 7 historical PIT certification and gated research rerun."""
from __future__ import annotations

import json
from argparse import Namespace
from datetime import date
from pathlib import Path
from typing import cast

from rich.console import Console
from rich.table import Table

from personal_alpha_terminal.quant_engine.historical_pit import (
    HistoricalDatasetVersionRegistry,
    HistoricalPitVerdict,
    build_version,
    certify_historical_pit,
    run_historical_research,
)
from personal_alpha_terminal.quant_engine.historical_pit.providers import (
    ResearchProviderCapabilities,
)
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchUseScope,
    certify_research_package,
    load_persisted_research_dataset,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderContract,
)

console = Console()


def round7_research_command(args: Namespace) -> int:
    action = str(args.round7_action)
    root = cast(Path, args.root)
    if action == "status":
        return _status(root)
    if action == "certify":
        return _certify(root, args)
    if action == "rerun":
        return _rerun(root, args)
    console.print(f"Unknown round7 action: {action}")
    return 2


def _versions_root(root: Path) -> Path:
    return root / "versions"


def _status(root: Path) -> int:
    registry = HistoricalDatasetVersionRegistry(_versions_root(root))
    latest = registry.latest()
    console.print("[bold]ROUND 7 - HISTORICAL PIT STATUS[/bold]")
    console.print(f"Research data root: {root.resolve()}")
    if latest is None:
        console.print("Latest certified version: NONE")
        console.print("Verdict: HISTORICAL_PIT_LIMITED")
        console.print(
            "No licensed survivorship-safe historical dataset is installed. "
            "The free current-directory providers cannot certify historical "
            "membership or delisting returns, so certification is honestly withheld."
        )
        console.print("Providers available (official capability audit):")
        _provider_table()
        return 0
    console.print(f"Latest certified version: {latest.research_data_version}")
    console.print(f"Snapshot hash: {latest.snapshot_hash[:16]}")
    console.print(f"Security master hash: {latest.security_master_hash[:16]}")
    console.print(f"Corporate action hash: {latest.corporate_action_hash[:16]}")
    console.print(f"Universe hash: {latest.universe_hash[:16]}")
    console.print(f"Certification state: {latest.certification_state.value}")
    console.print(f"Published at: {latest.published_at.isoformat()}")
    return 0


def _certify(root: Path, args: Namespace) -> int:
    """Certify the latest imported research dataset through the ROUND 7 framework.

    This publishes an immutable dataset version; any later change to the inputs
    invalidates the old certification.  A provider without delisting returns or
    historical membership is honestly classified HISTORICAL_PIT_LIMITED.
    """
    from personal_alpha_terminal.quant_engine.research_dataset import latest_manifest

    manifest_path = latest_manifest(root)
    if manifest_path is None:
        console.print("NOT_CERTIFIABLE: no imported research dataset under root")
        return 3
    package = load_persisted_research_dataset(manifest_path)
    if package.use_scope is not ResearchUseScope.PRODUCTION_RESEARCH:
        console.print("NOT_CERTIFIABLE: imported package is not PRODUCTION_RESEARCH")
        return 3
    manifest = certify_research_package(
        package,
        required_start=(
            date.fromisoformat(args.required_start) if args.required_start else None
        ),
        required_end=(
            date.fromisoformat(args.required_end) if args.required_end else None
        ),
    )
    capabilities = ResearchProviderCapabilities(
        provider_id=package.provider,
        provider_version=package.provider_version,
        raw_ohlcv=True,
        delisting_history=bool(getattr(args, "claim_delisting_history", False)),
        delisting_returns=bool(getattr(args, "claim_delisting_returns", False)),
        historical_membership=bool(getattr(args, "claim_historical_membership", False)),
        identifier_history=True,
        permanent_identifiers=True,
        corporate_actions_pit=True,
        total_return_pit=bool(manifest.total_return_certified),
        exchange_calendar=True,
    )
    contract = ProviderContract(
        provider_id=package.provider,
        provider_version=package.provider_version or "1.0",
        provider_security_id_scheme="PROVIDER_PERMANENT_ID",
        permanent_identifiers=True,
        delisting_history=capabilities.delisting_history,
        delisting_returns=capabilities.delisting_returns,
        historical_membership=capabilities.historical_membership,
        corporate_actions_pit=True,
        total_return_pit=capabilities.total_return_pit,
        benchmark_same_pit=True,
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        schema_mapping_version="historical-pit-provider-v1",
        source_identity=f"{package.provider}:{package.provider_version}",
        known_limitations=package.known_limitations,
    )
    version = build_version(package, manifest)
    certification = certify_historical_pit(
        package,
        contract,
        capabilities,
        version,
        required_start=(
            date.fromisoformat(args.required_start) if args.required_start else None
        ),
        required_end=(
            date.fromisoformat(args.required_end) if args.required_end else None
        ),
    )
    if certification.verdict is HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED:
        registry = HistoricalDatasetVersionRegistry(_versions_root(root))
        registry.publish(version)
    rendered = json.dumps(certification.document(), ensure_ascii=False, indent=2, sort_keys=True)
    console.print(rendered)
    console.print(f"Verdict: {certification.verdict.value}")
    if certification.verdict is HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED:
        console.print(f"Published version: {version.research_data_version}")
    return 0 if certification.verdict is HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED else 3


def _rerun(root: Path, args: Namespace) -> int:
    """Gated historical research rerun; refuses to run on non-certified data."""
    registry = HistoricalDatasetVersionRegistry(_versions_root(root))
    latest = registry.latest()
    if latest is None:
        console.print("HISTORICAL_PIT_LIMITED: no certified historical dataset version")
        return 3
    from personal_alpha_terminal.quant_engine.research_dataset import latest_manifest

    manifest_path = latest_manifest(root)
    if manifest_path is None:
        console.print("HISTORICAL_PIT_LIMITED: dataset rows are missing")
        return 3
    package = load_persisted_research_dataset(manifest_path)
    manifest = certify_research_package(package)
    delisted = {item.permanent_security_id for item in package.securities if item.delisting_date}
    terminal_types = {"DELISTING", "MERGER", "ACQUISITION"}
    terminal_returns = {
        item.permanent_security_id
        for item in package.corporate_actions
        if item.action_type in terminal_types and item.terminal_return is not None
    }
    historical_rows = sum(
        1
        for item in package.memberships
        if item.membership_source_type.upper() != "CURRENT_SNAPSHOT"
    )
    capabilities = ResearchProviderCapabilities(
        provider_id=package.provider,
        provider_version=package.provider_version,
        raw_ohlcv=True,
        delisting_history=bool(delisted),
        delisting_returns=bool(delisted) and terminal_returns == delisted,
        historical_membership=historical_rows > 0,
        identifier_history=True,
        permanent_identifiers=True,
        corporate_actions_pit=True,
        total_return_pit=bool(manifest.total_return_certified),
        exchange_calendar=True,
    )
    contract = ProviderContract(
        provider_id=package.provider,
        provider_version=package.provider_version or "1.0",
        provider_security_id_scheme="PROVIDER_PERMANENT_ID",
        permanent_identifiers=True,
        delisting_history=True,
        delisting_returns=True,
        historical_membership=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        benchmark_same_pit=True,
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        schema_mapping_version="historical-pit-provider-v1",
        source_identity=f"{package.provider}:{package.provider_version}",
    )
    version = build_version(package, manifest)
    certification = certify_historical_pit(package, contract, capabilities, version)
    rerun = run_historical_research(
        certification,
        package,
        benchmark=args.benchmark,
        horizon=args.horizon,
        round4_baseline=None,
    )
    console.print(json.dumps(rerun.document(), ensure_ascii=False, indent=2, sort_keys=True))
    console.print(f"Verdict: {rerun.verdict.value}")
    console.print(f"Executed: {rerun.executed}")
    return 0 if rerun.executed else 3


def _provider_table() -> None:
    from personal_alpha_terminal.quant_engine.historical_data_acquisition import (
        provider_capability_matrix,
    )

    table = Table(title="Provider Capability Evidence (official audit)")
    for column in (
        "Provider",
        "Delisted",
        "Permanent ID",
        "Ticker history",
        "Historical membership",
        "Delisting return",
        "PIT vintages",
        "Total return",
        "Grade",
    ):
        table.add_column(column)
    for item in provider_capability_matrix():
        table.add_row(
            item.provider_id,
            item.delisted_securities.value,
            item.permanent_identifiers.value,
            item.ticker_history.value,
            item.historical_membership.value,
            item.delisting_return.value,
            item.pit_vintages.value,
            item.total_return.value,
            item.certification_grade,
        )
    console.print(table)
