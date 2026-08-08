from datetime import UTC, date, datetime, timedelta

import pandas as pd

from personal_alpha_terminal.quant_engine.factors.factor_engine import FactorEngine
from personal_alpha_terminal.quant_engine.factors.qlib_adapter import QlibFactorResearchAdapter
from personal_alpha_terminal.research.data_gate import (
    ResearchDataAuthorization,
    ResearchDataEvidence,
    ResearchDataGate,
    ResearchDataRequest,
    ResearchPurpose,
)


def _research_authorization() -> ResearchDataAuthorization:
    now = datetime(2026, 1, 10, tzinfo=UTC)
    request = ResearchDataRequest(
        ResearchPurpose.RESEARCH,
        "US",
        "stock",
        date(2025, 1, 1),
        date(2026, 1, 9),
        now,
        "raw",
        maximum_age=timedelta(days=10),
    )
    evidence = ResearchDataEvidence(
        market="US",
        asset_type="stock",
        quality_status="passed",
        source="fixture",
        provider="fixture",
        source_ids=("fixture:factor",),
        latest_available_time=now - timedelta(days=1),
        point_in_time_status="uncertified",
        adjustment_mode="raw",
        universe_snapshot_id=None,
        universe_available_time=None,
        corporate_actions_complete=False,
        trading_calendar_complete=True,
        missing_rate=0,
        anomaly_rate=0,
        maximum_missing_rate=0.01,
        maximum_anomaly_rate=0.01,
        data_version="fixture-factor-v1",
        allow_backtest=False,
        allow_display=True,
        allow_portfolio_decision=False,
        dual_source_verified=False,
    )
    return ResearchDataGate().authorize(request, evidence, evaluated_at=now)


def test_factor_engine_uses_only_available_vintage_and_disables_missing_groups() -> None:
    cutoff = datetime(2026, 1, 10, tzinfo=UTC)
    observations = pd.DataFrame(
        [
            *[
                {
                    "permanent_security_id": f"US-{ticker}",
                    "ticker": ticker,
                    "available_at": "2026-01-09T20:00:00Z",
                    "pe": pe,
                    "momentum_12_1": momentum,
                    "volatility": volatility,
                    "sector": "Technology" if index < 3 else "Industrials",
                    "market_cap": 10_000_000_000 * (index + 1),
                }
                for index, (ticker, pe, momentum, volatility) in enumerate(
                    (
                        ("A", 10, 0.20, 0.15),
                        ("B", 20, 0.10, 0.25),
                        ("C", 30, 0.05, 0.20),
                        ("D", 15, 0.12, 0.18),
                        ("E", 25, -0.02, 0.30),
                        ("F", 18, 0.08, 0.22),
                    )
                )
            ],
            {
                "permanent_security_id": "US-A",
                "ticker": "A",
                "available_at": "2026-01-11T20:00:00Z",
                "pe": 1000,
                "momentum_12_1": -0.50,
                "volatility": 0.90,
                "sector": "Technology",
                "market_cap": 10_000_000_000,
            },
        ]
    )
    result = FactorEngine().score_snapshot(
        authorization=_research_authorization(),
        observations=observations,
        decision_time=cutoff,
    )

    assert {item.ticker for item in result.scores} == {"A", "B", "C", "D", "E", "F"}
    assert all("quality" in item.disabled_components for item in result.scores)
    assert all("growth" in item.disabled_components for item in result.scores)
    assert all(not item.production_eligible for item in result.scores)
    assert result.source_rows == 6


def test_qlib_adapter_is_feature_only_and_reports_runtime_status() -> None:
    adapter = QlibFactorResearchAdapter()
    frame = adapter.build_feature_frame(
        pd.DataFrame(
            [{"datetime": "2026-01-01T00:00:00Z", "instrument": "A", "momentum": 0.2}]
        )
    )

    assert list(frame.columns) == ["momentum"]
    assert "prediction" in adapter.status().permitted_use
    assert not hasattr(adapter, "predict")
