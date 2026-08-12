import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from personal_alpha_terminal.core.effective_config import EffectiveRuntimeConfig
from personal_alpha_terminal.data.us_market.broad_universe import (
    CurrentDirectorySnapshot,
    CurrentSecurityMasterRecord,
    CurrentSecurityType,
    SurvivorshipStatus,
)
from personal_alpha_terminal.quant_engine.historical_data_acquisition import (
    AcquisitionCheckpoint,
    CapabilityStatus,
    HistoricalResearchClassification,
    ResearchBaseline,
    audit_available_historical_layers,
    build_research_baseline,
    persist_acquisition_checkpoint,
    persist_acquisition_evidence,
    provider_capability_matrix,
    read_acquisition_checkpoint,
)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE security_master (
                id INTEGER PRIMARY KEY,
                canonical_code TEXT NOT NULL,
                symbol TEXT NOT NULL
            );
            CREATE TABLE prices (
                id INTEGER PRIMARY KEY,
                stock_id INTEGER NOT NULL,
                trade_date TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER,
                source TEXT NOT NULL,
                provider TEXT NOT NULL,
                available_time TEXT,
                ingested_at TEXT NOT NULL,
                price_type TEXT NOT NULL
            );
            CREATE TABLE corporate_actions (id INTEGER PRIMARY KEY);
            CREATE TABLE pit_total_return_versions (id INTEGER PRIMARY KEY);
            """
        )
        connection.executemany(
            "INSERT INTO security_master VALUES (?, ?, ?)",
            ((1, "US:ETF:SPY", "SPY"), (2, "US:ETF:QQQ", "QQQ")),
        )
        for index, _symbol in enumerate(("SPY", "QQQ"), start=1):
            connection.execute(
                "INSERT INTO prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    index,
                    index,
                    "2024-01-05",
                    100.0,
                    101.0,
                    99.0,
                    100.5,
                    1_000_000,
                    "fixture-live",
                    "fixture-provider",
                    "2024-01-05T21:30:00+00:00",
                    "2024-01-05T21:31:00+00:00",
                    "unadjusted_ohlcv",
                ),
            )


def _directory() -> CurrentDirectorySnapshot:
    record = CurrentSecurityMasterRecord(
        security_id="CURRENT:XNAS:AAA",
        symbol="AAA",
        company_name="AAA Corp Common Stock",
        security_type=CurrentSecurityType.COMMON_STOCK,
        exchange="XNAS",
        currency="USD",
        country="US",
        listing_date=None,
        delisting_date=None,
        active_from=date(2024, 1, 5),
        active_to=None,
        is_common_stock=True,
        is_etf=False,
        is_adr=False,
        is_reit=False,
        is_preferred=False,
        is_warrant=False,
        is_unit=False,
        is_right=False,
        is_otc=False,
        sector=None,
        industry=None,
        test_issue=False,
        financial_status="NORMAL",
        source="official current snapshot",
        effective_date=date(2024, 1, 5),
        available_at=datetime(2024, 1, 5, 23, tzinfo=UTC),
    )
    return CurrentDirectorySnapshot(
        "current-only",
        "official-current-provider",
        datetime(2024, 1, 5, 23, tzinfo=UTC),
        "2024-01-05",
        (record,),
        "d" * 64,
        "m" * 64,
        SurvivorshipStatus.UNVERIFIED,
        False,
    )


def _baseline() -> ResearchBaseline:
    return build_research_baseline(
        EffectiveRuntimeConfig(),
        git_head="a" * 40,
        git_commit_time=datetime(2024, 1, 6, tzinfo=UTC),
        required_end=date(2024, 1, 5),
    )


def test_baseline_freezes_expanded_universe_strategy_probability_and_oos_policy() -> None:
    first = _baseline()
    second = _baseline()
    assert first == second
    assert first.universe_policy_version.startswith("broad-us-equity-v1-")
    assert first.strategy_candidate_version.startswith("USAdaptiveAlphaCoreV1:1.0.0")
    assert first.probability_role == "SUPPORTING_OVERLAY_UNLESS_EXACT_PRODUCTION_APPROVAL"
    assert first.requirements.locked_oos_sessions == 252
    assert first.requirements.minimum_total_sessions > 252
    assert first.requirements.configured_target_start == date(2015, 1, 1)


def test_required_end_change_creates_new_baseline_identity() -> None:
    first = _baseline()
    changed = build_research_baseline(
        EffectiveRuntimeConfig(),
        git_head="a" * 40,
        git_commit_time=datetime(2024, 1, 6, tzinfo=UTC),
        required_end=date(2025, 1, 3),
    )
    assert changed.requirements.required_end == date(2025, 1, 3)
    assert changed.research_baseline_id != first.research_baseline_id


def test_provider_matrix_is_conservative_and_officially_sourced() -> None:
    matrix = {item.provider_id: item for item in provider_capability_matrix()}
    assert matrix["nasdaq_trader_symbol_directory"].historical_membership is CapabilityStatus.NO
    assert matrix["alpha_vantage"].historical_membership is CapabilityStatus.YES
    assert matrix["norgate_data"].delisted_securities is CapabilityStatus.PARTIAL
    assert matrix["crsp_us_stock"].permanent_identifiers is CapabilityStatus.YES
    assert matrix["massive"].certification_grade == "REQUIRES_LICENSE"
    assert all(item.official_evidence for item in matrix.values())


def test_current_layers_remain_not_certifiable_and_benchmarks_are_live_only(
    tmp_path: Path,
) -> None:
    database = tmp_path / "live.sqlite"
    _database(database)
    manifest = audit_available_historical_layers(
        database=database, directory=_directory(), baseline=_baseline()
    )
    assert manifest.classification is HistoricalResearchClassification.NOT_CERTIFIABLE
    assert manifest.current_directory_securities == 1
    assert manifest.historical_security_count == 0
    assert manifest.historical_membership_rows == 0
    assert manifest.membership_coverage_pct == 0.0
    assert manifest.benchmark_rows == {"SPY": 1, "QQQ": 1}
    assert manifest.layer_content_hashes["benchmark_raw_live_only"] is not None
    assert manifest.research_dataset_content_hash is None
    assert "BENCHMARK_PIT_TOTAL_RETURN_CONVENTION_INCOMPLETE" in manifest.blockers
    assert manifest.oos_lock_status == "NOT_CREATED_RESEARCH_DATA_NOT_CERTIFIED"


def test_changed_benchmark_row_changes_hash_and_publication_is_resumable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "live.sqlite"
    _database(database)
    baseline = _baseline()
    first = audit_available_historical_layers(
        database=database, directory=_directory(), baseline=baseline
    )
    paths = persist_acquisition_evidence(baseline, first, tmp_path / "research")
    repeated = persist_acquisition_evidence(baseline, first, tmp_path / "research")
    assert paths == repeated
    assert all(path.exists() for path in paths)
    assert not tuple((tmp_path / "research").rglob("*.tmp"))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE prices SET close=102.0 WHERE id=1")
    changed = audit_available_historical_layers(
        database=database, directory=_directory(), baseline=baseline
    )
    assert changed.layer_content_hashes["benchmark_raw_live_only"] != (
        first.layer_content_hashes["benchmark_raw_live_only"]
    )
    assert changed.manifest_hash != first.manifest_hash


def test_strategy_or_probability_change_creates_new_baseline_identity() -> None:
    first = _baseline()
    config = replace(
        EffectiveRuntimeConfig(),
        broad_universe=replace(EffectiveRuntimeConfig().broad_universe, include_reit=True),
    )
    changed = build_research_baseline(
        config,
        git_head="a" * 40,
        git_commit_time=datetime(2024, 1, 6, tzinfo=UTC),
        required_end=date(2024, 1, 5),
    )
    assert changed.universe_policy_hash != first.universe_policy_hash
    assert changed.research_baseline_id != first.research_baseline_id


def test_interrupted_chunked_acquisition_resumes_idempotently(tmp_path: Path) -> None:
    checkpoint = AcquisitionCheckpoint(
        "licensed-provider", "historical-us-equity-v1", ("2000-2009", "2010-2019")
    ).complete("2000-2009", "a" * 64, 1_000)
    path = tmp_path / "checkpoint.json"
    persist_acquisition_checkpoint(checkpoint, path)

    resumed = read_acquisition_checkpoint(path)
    assert resumed.pending_chunks == ("2010-2019",)
    assert resumed.complete("2000-2009", "a" * 64, 1_000) == resumed
    completed = resumed.complete("2010-2019", "b" * 64, 1_200)
    assert completed.pending_chunks == ()

    with pytest.raises(ValueError, match="changed after completion"):
        resumed.complete("2000-2009", "c" * 64, 1_000)
