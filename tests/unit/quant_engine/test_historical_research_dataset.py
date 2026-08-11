import csv
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from personal_alpha_terminal.quant_engine.research_data import ResearchDatasetState
from personal_alpha_terminal.quant_engine.research_dataset import (
    AdjustmentKind,
    HistoricalSecurity,
    HistoricalUniverseMembership,
    ResearchCorporateAction,
    ResearchDatasetPackage,
    ResearchPrice,
    ResearchUseScope,
    SecurityType,
    certify_research_package,
    generate_xnys_sessions,
    import_research_package,
    load_persisted_research_dataset,
    package_to_import_rows,
    persist_research_dataset,
)

CUTOFF = datetime(2024, 1, 6, tzinfo=UTC)


def _complete_package() -> ResearchDatasetPackage:
    securities = (
        HistoricalSecurity(
            "SEC-ALPHA", "OLD", date(2020, 1, 1), date(2024, 1, 3), "XNYS",
            date(2020, 1, 1), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2019, 12, 1, tzinfo=UTC), "licensed fixture", "test-provider",
        ),
        HistoricalSecurity(
            "SEC-ALPHA", "NEW", date(2024, 1, 4), None, "XNYS",
            date(2020, 1, 1), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2024, 1, 3, tzinfo=UTC), "licensed fixture", "test-provider",
        ),
        HistoricalSecurity(
            "SEC-DEAD", "DEAD", date(2020, 1, 1), date(2024, 1, 3), "XNYS",
            date(2020, 1, 1), date(2024, 1, 3), "BANKRUPTCY", SecurityType.US_EQUITY,
            datetime(2019, 12, 1, tzinfo=UTC), "licensed fixture", "test-provider",
        ),
    )
    memberships = (
        HistoricalUniverseMembership(
            "SEC-ALPHA", "TEST-EQUITY", SecurityType.US_EQUITY, date(2024, 1, 2),
            None, datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC), "HISTORICAL_TIMELINE",
            "licensed fixture", "test-provider",
        ),
        HistoricalUniverseMembership(
            "SEC-DEAD", "TEST-EQUITY", SecurityType.US_EQUITY, date(2024, 1, 2),
            date(2024, 1, 3), datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC), "HISTORICAL_TIMELINE",
            "licensed fixture", "test-provider",
        ),
    )
    price_rows: list[ResearchPrice] = []
    sessions = generate_xnys_sessions(date(2024, 1, 2), date(2024, 1, 5), available_at=CUTOFF)
    for index, session in enumerate(sessions):
        ticker = "OLD" if session.session_date <= date(2024, 1, 3) else "NEW"
        price_rows.append(
            ResearchPrice(
                "SEC-ALPHA", ticker, session.session_date,
                datetime.combine(session.session_date, datetime.min.time(), tzinfo=UTC).replace(
                    hour=22
                ),
                "XNYS", 100 + index, 102 + index, 99 + index, 101 + index, 1_000_000,
                AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE, 1000 + index,
                datetime.combine(session.session_date, datetime.min.time(), tzinfo=UTC).replace(
                    hour=22
                ),
                f"tr-{session.session_date.isoformat()}", "licensed fixture", "test-provider",
            )
        )
        if session.session_date <= date(2024, 1, 3):
            price_rows.append(
                ResearchPrice(
                    "SEC-DEAD", "DEAD", session.session_date,
                    datetime.combine(
                        session.session_date, datetime.min.time(), tzinfo=UTC
                    ).replace(hour=22),
                    "XNYS", 10 - index, 11 - index, 8 - index, 9 - index, 100_000,
                    AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE, 100 - index,
                    datetime.combine(
                        session.session_date, datetime.min.time(), tzinfo=UTC
                    ).replace(hour=22),
                    f"tr-dead-{session.session_date.isoformat()}",
                    "licensed fixture", "test-provider",
                )
            )
    actions = (
        ResearchCorporateAction(
            "SEC-ALPHA", "SYMBOL_CHANGE", date(2024, 1, 4), date(2024, 1, 3),
            datetime(2024, 1, 3, 12, tzinfo=UTC), "licensed fixture", "test-provider",
            successor_security_id="SEC-ALPHA",
        ),
        ResearchCorporateAction(
            "SEC-DEAD", "DELISTING", date(2024, 1, 3), date(2024, 1, 2),
            datetime(2024, 1, 2, 12, tzinfo=UTC), "licensed fixture", "test-provider",
            terminal_return=-0.80,
        ),
    )
    return ResearchDatasetPackage(
        "historical-contract-fixture", "research-package-v1", "test-provider",
        "licensed fixture", CUTOFF, date(2024, 1, 5), CUTOFF,
        ResearchUseScope.TEST_FIXTURE, securities, memberships, tuple(price_rows), actions,
        sessions,
    )


def test_complete_fixture_certifies_but_is_never_production_eligible() -> None:
    manifest = certify_research_package(_complete_package())
    assert manifest.certification_state is ResearchDatasetState.CERTIFIED
    assert manifest.production_eligible is False
    assert manifest.security_count == 2
    assert manifest.ticker_vintage_count == 3
    assert manifest.row_count == 17


def test_current_members_cannot_backfill_historical_universe() -> None:
    package = _complete_package()
    memberships = (replace(package.memberships[0], membership_source_type="CURRENT_SNAPSHOT"),)
    manifest = certify_research_package(replace(package, memberships=memberships))
    assert manifest.certification_state is ResearchDatasetState.NOT_CERTIFIABLE
    assert "CURRENT_CONSTITUENT_HISTORY_NOT_ALLOWED" in manifest.blockers


def test_permanent_id_survives_ticker_change_and_membership_dates_are_pit() -> None:
    package = _complete_package()
    alpha = [item for item in package.securities if item.permanent_security_id == "SEC-ALPHA"]
    assert [item.ticker for item in alpha] == ["OLD", "NEW"]
    membership = package.memberships[0]
    assert not membership.active_on(
        date(2024, 1, 2), datetime(2023, 12, 19, tzinfo=UTC)
    )
    assert membership.active_on(date(2024, 1, 2), datetime(2024, 1, 2, tzinfo=UTC))
    split_identity = replace(
        package.corporate_actions[0], successor_security_id="SEC-NEW-INDEPENDENT"
    )
    manifest = certify_research_package(
        replace(package, corporate_actions=(split_identity, package.corporate_actions[1]))
    )
    assert "SYMBOL_CHANGE_CREATED_NEW_SECURITY_ID" in manifest.blockers


def test_delisted_security_cannot_disappear_and_unknown_return_is_not_zero() -> None:
    package = _complete_package()
    without_terminal = replace(
        package,
        corporate_actions=tuple(
            item for item in package.corporate_actions if item.action_type != "DELISTING"
        ),
    )
    assert "DELISTED_SECURITY_LIFECYCLE_INCOMPLETE" in certify_research_package(
        without_terminal
    ).blockers
    unknown = replace(
        package,
        corporate_actions=tuple(
            replace(item, terminal_return=None) if item.action_type == "DELISTING" else item
            for item in package.corporate_actions
        ),
    )
    manifest = certify_research_package(unknown)
    assert "DELISTING_RETURN_UNAVAILABLE" in manifest.blockers
    terminal = next(item for item in unknown.corporate_actions if item.action_type == "DELISTING")
    assert terminal.terminal_return is None
    missing_prices = replace(
        package,
        prices=tuple(
            item for item in package.prices if item.permanent_security_id != "SEC-DEAD"
        ),
    )
    assert "MEMBER_PRICE_HISTORY_MISSING" in certify_research_package(
        missing_prices
    ).blockers


def test_future_corporate_action_and_future_price_fail_closed() -> None:
    package = _complete_package()
    bad_action = replace(package.corporate_actions[1], available_at=datetime(2024, 1, 4,
                                                                           tzinfo=UTC))
    manifest = certify_research_package(
        replace(package, corporate_actions=(package.corporate_actions[0], bad_action))
    )
    assert manifest.certification_state is ResearchDatasetState.REJECTED
    assert "FUTURE_CORPORATE_ACTION_LEAKAGE" in manifest.blockers
    future_price = replace(package.prices[0], observation_date=date(2024, 1, 8))
    assert "FUTURE_PRICE_ROW" in certify_research_package(
        replace(package, prices=(future_price, *package.prices[1:]))
    ).blockers


def test_current_adjusted_series_cannot_become_pit_total_return() -> None:
    package = _complete_package()
    current = replace(
        package.prices[0], adjustment_kind=AdjustmentKind.CURRENT_FINAL_ADJUSTED,
        total_return_value=None, total_return_available_at=None, adjustment_vintage_id=None,
    )
    manifest = certify_research_package(replace(package, prices=(current, *package.prices[1:])))
    assert "CURRENT_ADJUSTED_SERIES_NOT_PIT_VINTAGE" in manifest.blockers
    assert manifest.total_return_certified is False


def test_etf_equity_benchmark_universes_cannot_be_mixed() -> None:
    package = _complete_package()
    mixed = replace(package.memberships[0], universe_type=SecurityType.US_ETF)
    manifest = certify_research_package(
        replace(package, memberships=(mixed, package.memberships[1]))
    )
    assert manifest.certification_state is ResearchDatasetState.REJECTED
    assert "ETF_EQUITY_BENCHMARK_UNIVERSE_MIXED" in manifest.blockers


def test_session_calendar_respects_us_holiday() -> None:
    sessions = generate_xnys_sessions(
        date(2024, 7, 3), date(2024, 7, 5), available_at=CUTOFF
    )
    assert [item.session_date for item in sessions] == [date(2024, 7, 3), date(2024, 7, 5)]
    assert sessions[0].is_early_close is True


def test_content_hash_is_row_level_not_inventory_and_is_reproducible() -> None:
    package = _complete_package()
    first = certify_research_package(package)
    second = certify_research_package(package)
    assert first.manifest_hash == second.manifest_hash
    assert first.content_hash != first.inventory_hash
    changed_price = replace(package.prices[0], close=package.prices[0].close + 0.25)
    changed = certify_research_package(
        replace(package, prices=(changed_price, *package.prices[1:]))
    )
    assert changed.content_hash != first.content_hash
    assert changed.dataset_version != first.dataset_version


def test_duplicate_provider_rows_are_rejected_deterministically() -> None:
    package = _complete_package()
    duplicated = replace(package, prices=(*package.prices, package.prices[0]))
    first = certify_research_package(duplicated)
    second = certify_research_package(duplicated)
    assert first.certification_state is ResearchDatasetState.REJECTED
    assert "DUPLICATE_PRICE_ROW" in first.blockers
    assert first.manifest_hash == second.manifest_hash


def test_ticker_reuse_does_not_merge_unrelated_permanent_ids() -> None:
    package = _complete_package()
    reused = replace(
        package.securities[2],
        permanent_security_id="SEC-REUSED-INDEPENDENT",
        ticker="OLD",
        ticker_valid_from=date(2025, 1, 1),
        ticker_valid_to=None,
        listing_date=date(2025, 1, 1),
        delisting_date=None,
        delisting_reason="UNKNOWN",
    )
    identities = {item.permanent_security_id for item in (*package.securities, reused)}
    assert "SEC-ALPHA" in identities
    assert "SEC-REUSED-INDEPENDENT" in identities
    assert len(identities) == 3


def test_incomplete_research_data_is_not_certifiable() -> None:
    package = _complete_package()
    manifest = certify_research_package(
        replace(package, memberships=(), corporate_actions=(), calendar=())
    )
    assert manifest.certification_state is ResearchDatasetState.NOT_CERTIFIABLE
    assert manifest.data_domain.value == "RESEARCH_RAW_DATA"
    assert "HISTORICAL_MEMBERSHIP_INCOMPLETE" in manifest.blockers


def test_csv_parquet_and_sqlite_import_normalize_to_identical_content(
    tmp_path: Path,
) -> None:
    package = _complete_package()
    rows = package_to_import_rows(package)
    columns = sorted({key for row in rows for key in row})
    csv_path = tmp_path / "research.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    parquet_path = tmp_path / "research.parquet"
    pd.DataFrame(rows, columns=columns).to_parquet(parquet_path, index=False)
    sqlite_path = tmp_path / "research.sqlite"
    with sqlite3.connect(sqlite_path) as connection:
        declarations = ", ".join(f'"{item}" TEXT' for item in columns)
        connection.execute(f"CREATE TABLE research_rows ({declarations})")
        placeholders = ", ".join("?" for _ in columns)
        names = ", ".join(f'"{item}"' for item in columns)
        connection.executemany(
            f"INSERT INTO research_rows ({names}) VALUES ({placeholders})",
            [tuple(row.get(column) for column in columns) for row in rows],
        )
    imported = tuple(
        import_research_package(path) for path in (csv_path, parquet_path, sqlite_path)
    )
    assert {item.content_hash for item in imported} == {package.content_hash}
    manifest = certify_research_package(imported[0])
    path = persist_research_dataset(imported[0], manifest, tmp_path / "store")
    assert path.exists()
    reloaded = load_persisted_research_dataset(path)
    reproduced = certify_research_package(reloaded)
    assert reproduced.manifest_hash == manifest.manifest_hash
    assert manifest.certification_state is ResearchDatasetState.CERTIFIED
