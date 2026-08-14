"""ROUND22 official universe PIT visibility, forward bootstrap and session tests."""
from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from personal_alpha_terminal.data.us_market.broad_universe import (
    latest_directory_snapshot_at,
    list_directory_snapshots,
    parse_symbol_directories,
    write_directory_snapshot,
)
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1Config,
)
from personal_alpha_terminal.terminal.market_sessions import MarketSessionCalendar

ET = ZoneInfo("America/New_York")

NASDAQ = (
    "Symbol|Security Name|Market Category|Test Issue|Financial Status|"
    "Round Lot Size|ETF|NextShares\n"
    "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\n"
    "File Creation Time: 0812202604:14|||||||\n"
)
OTHER = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Corporation Common Stock|N|IBM|N|100|N|IBM
File Creation Time: 0812202604:14|||||||
"""


def _write_snapshot(root, retrieved_at: datetime) -> str:
    snapshot = parse_symbol_directories(NASDAQ, OTHER, retrieved_at=retrieved_at)
    write_directory_snapshot(snapshot, root)
    return snapshot.content_hash


def test_directory_snapshot_selection_is_decision_visible(tmp_path) -> None:
    root = tmp_path / "us-current-directory"
    root.mkdir()
    older = _write_snapshot(root, datetime(2026, 8, 12, 4, 14, tzinfo=UTC))
    newer = _write_snapshot(root, datetime(2026, 8, 14, 2, 21, tzinfo=UTC))
    assert len(list_directory_snapshots(root)) == 2
    visible_at_cutoff = latest_directory_snapshot_at(
        root, datetime(2026, 8, 12, 20, 30, tzinfo=UTC)
    )
    assert visible_at_cutoff is not None
    assert visible_at_cutoff.content_hash == older
    visible_later = latest_directory_snapshot_at(
        root, datetime(2026, 8, 14, 3, 0, tzinfo=UTC)
    )
    assert visible_later is not None
    assert visible_later.content_hash == newer


def test_no_historical_backdating_before_first_snapshot(tmp_path) -> None:
    root = tmp_path / "us-current-directory"
    root.mkdir()
    _write_snapshot(root, datetime(2026, 8, 12, 4, 14, tzinfo=UTC))
    assert (
        latest_directory_snapshot_at(root, datetime(2026, 8, 11, 20, 0, tzinfo=UTC))
        is None
    )


def test_immutable_snapshot_survives_later_capture(tmp_path) -> None:
    root = tmp_path / "us-current-directory"
    root.mkdir()
    older_hash = _write_snapshot(root, datetime(2026, 8, 12, 4, 14, tzinfo=UTC))
    old_path = root / f"{older_hash}.json"
    before = old_path.read_bytes()
    _write_snapshot(root, datetime(2026, 8, 14, 2, 21, tzinfo=UTC))
    assert old_path.read_bytes() == before


def test_forward_bootstrap_uses_first_visible_snapshot(tmp_path) -> None:
    root = tmp_path / "us-current-directory"
    root.mkdir()
    captured = _write_snapshot(root, datetime(2026, 8, 14, 2, 21, tzinfo=UTC))
    visible = latest_directory_snapshot_at(
        root, datetime(2026, 8, 14, 3, 0, tzinfo=UTC)
    )
    assert visible is not None and visible.content_hash == captured
    assert visible.historical_use_allowed is False
    assert visible.capabilities.historical_membership is False


def test_history_requirement_derived_from_active_factors() -> None:
    config = USAdaptiveAlphaCoreV1Config()
    assert config.required_history_sessions == 253
    by_factor = {
        str(item["factor"]): int(item["effective_required_sessions"])
        for item in config.history_requirements
    }
    assert by_factor["momentum_12_1"] == 253
    assert config.required_history_sessions == max(by_factor.values())


def test_completed_session_selected_after_close() -> None:
    calendar = MarketSessionCalendar()
    after_close = calendar.completed_session_date(
        datetime(2026, 8, 13, 22, 30, tzinfo=ET)
    )
    assert after_close == date(2026, 8, 13)
    before_open = calendar.completed_session_date(
        datetime(2026, 8, 13, 8, 0, tzinfo=ET)
    )
    assert before_open == date(2026, 8, 12)


def test_weekend_resolves_to_friday_session() -> None:
    calendar = MarketSessionCalendar()
    assert calendar.completed_session_date(
        datetime(2026, 8, 15, 12, 0, tzinfo=ET)
    ) == date(2026, 8, 14)


def test_same_timestamp_capture_prefers_latest_pointer(tmp_path) -> None:
    root = tmp_path / "us-current-directory"
    root.mkdir()
    retrieved = datetime(2026, 8, 12, 4, 14, tzinfo=UTC)
    first = parse_symbol_directories(NASDAQ, OTHER, retrieved_at=retrieved)
    write_directory_snapshot(first, root)
    second_rows = NASDAQ.replace("AAPL|Apple", "AAPL|Apple Inc - Updated")
    second = parse_symbol_directories(second_rows, OTHER, retrieved_at=retrieved)
    write_directory_snapshot(second, root)
    second_hash = second.content_hash
    visible = latest_directory_snapshot_at(root, datetime(2026, 8, 12, 20, 30, tzinfo=UTC))
    assert visible is not None
    assert visible.content_hash == second_hash
