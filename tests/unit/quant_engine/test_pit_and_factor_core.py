from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from personal_alpha_terminal.quant_engine.factors.cross_sectional import (
    FactorSignalStatus,
    FactorSpec,
    process_cross_section,
)
from personal_alpha_terminal.quant_engine.factors.features import compute_price_features
from personal_alpha_terminal.quant_engine.pit import (
    PITStatus,
    select_fundamental_vintages,
    select_universe_snapshot,
)

CUTOFF = datetime(2024, 5, 1, 21, tzinfo=UTC)


def test_future_fundamental_with_perfect_prediction_is_invisible_before_available() -> None:
    frame = pd.DataFrame(
        [
            {
                "permanent_security_id": "A",
                "fiscal_period_end": "2023-12-31",
                "fiscal_period": "FY2023",
                "filing_date": "2024-02-01",
                "publication_time": "2024-02-01T20:00:00Z",
                "available_at": "2024-02-01T21:00:00Z",
                "ingested_at": "2024-02-02T00:00:00Z",
                "revision_id": "original",
                "data_version": "v1",
                "future_alpha": 0.0,
            },
            {
                "permanent_security_id": "A",
                "fiscal_period_end": "2023-12-31",
                "fiscal_period": "FY2023",
                "filing_date": "2024-06-01",
                "publication_time": "2024-06-01T20:00:00Z",
                "available_at": "2024-06-01T21:00:00Z",
                "ingested_at": "2024-06-02T00:00:00Z",
                "revision_id": "perfect-future-revision",
                "data_version": "v2",
                "future_alpha": 999.0,
            },
        ]
    )
    result = select_fundamental_vintages(frame, information_cutoff=CUTOFF)
    assert result.status is PITStatus.VALID
    assert result.frame.iloc[0]["revision_id"] == "original"
    assert result.frame.iloc[0]["future_alpha"] == 0.0


def test_universe_selects_only_snapshot_known_at_cutoff_and_marks_uncertified_history() -> None:
    frame = pd.DataFrame(
        [
            {
                "snapshot_id": "old",
                "snapshot_date": "2024-04-30",
                "available_at": "2024-04-30T22:00:00Z",
                "permanent_security_id": "A",
                "listing_date": "2020-01-01",
                "delisting_date": None,
                "source": "fixture",
            },
            {
                "snapshot_id": "future",
                "snapshot_date": "2024-05-01",
                "available_at": "2024-05-02T22:00:00Z",
                "permanent_security_id": "B",
                "listing_date": "2020-01-01",
                "delisting_date": None,
                "source": "fixture",
            },
        ]
    )
    result = select_universe_snapshot(
        frame, information_cutoff=CUTOFF, certified_history=False
    )
    assert result.status is PITStatus.SURVIVORSHIP_BIAS_RISK
    assert result.frame["snapshot_id"].tolist() == ["old"]


def test_cross_section_winsorizes_neutralizes_and_never_imputes_missing_zero() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 10_000.0, np.nan, 8.0]
    frame = pd.DataFrame(
        {
            "permanent_security_id": [f"S{i}" for i in range(len(values))],
            "available_at": [CUTOFF - timedelta(hours=1)] * len(values),
            "quality": values,
            "sector": ["A", "A", "A", "B", "B", "B", "B", "B"],
            "market_cap": [10, 20, 30, 10, 20, 30, 40, 50],
        }
    )
    result = process_cross_section(
        frame,
        (FactorSpec("quality", lower_percentile=0.1, upper_percentile=0.9),),
        as_of=CUTOFF,
        minimum_required_factors=1,
    )
    output = result.frame.set_index("permanent_security_id")
    assert result.statuses["quality"] is FactorSignalStatus.VALID
    assert pd.isna(output.loc["S6", "quality__normalized"])
    assert not output.loc["S6", "eligible"]
    assert output["quality__normalized"].dropna().abs().max() <= 5
    assert output["quality__winsorized"].max() < 10_000


def test_cross_section_filters_future_available_rows_before_ranking() -> None:
    current = pd.DataFrame(
        {
            "permanent_security_id": ["A", "B", "C", "D", "E"],
            "available_at": [CUTOFF - timedelta(hours=1)] * 5,
            "momentum": [1, 2, 3, 4, 5],
            "sector": ["x"] * 5,
            "market_cap": [10, 20, 30, 40, 50],
        }
    )
    future = current.iloc[[0]].copy()
    future["available_at"] = CUTOFF + timedelta(days=1)
    future["momentum"] = 1_000_000
    result = process_cross_section(
        pd.concat([current, future], ignore_index=True),
        (FactorSpec("momentum"),),
        as_of=CUTOFF,
        minimum_required_factors=1,
    )
    output = result.frame.set_index("permanent_security_id")
    assert output.loc["A", "momentum__raw"] == 1


def test_professional_12_1_momentum_excludes_most_recent_month() -> None:
    sessions = pd.bdate_range("2023-01-02", periods=280)
    close = np.linspace(100, 200, len(sessions))
    close[-21:] = np.linspace(200, 100, 21)  # severe recent reversal must be skipped
    prices = pd.DataFrame(
        {
            "permanent_security_id": "A",
            "ticker": "A",
            "trade_date": sessions,
            "available_time": [
                datetime.combine(day.date(), datetime.min.time(), UTC)
                for day in sessions
            ],
            "close": close,
        }
    )
    result = compute_price_features(
        prices,
        information_cutoff=datetime.combine(sessions[-1].date(), datetime.max.time(), UTC),
    )
    assert result.iloc[0]["momentum_12_1"] > 0
    assert "trend_slope" in result
    assert "volatility" in result
