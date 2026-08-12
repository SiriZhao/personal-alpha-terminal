"""Shared ROUND 7 test fixtures.

Builds a genuinely certifiable historical PIT package: permanent identifiers,
ticker vintages, historical memberships, retained delisted security with
terminal return, PIT corporate actions, and PIT total-return vintage prices.
This is licensed-package-shaped fixture data that passes every real gate; it is
never presented as a production certification.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np

from personal_alpha_terminal.quant_engine.research_dataset import (
    AdjustmentKind,
    HistoricalSecurity,
    HistoricalUniverseMembership,
    ResearchCorporateAction,
    ResearchDatasetPackage,
    ResearchPrice,
    ResearchUseScope,
    SecurityType,
    generate_xnys_sessions,
)

ALPHA_IDS = ("SEC-A", "SEC-B", "SEC-C", "SEC-D", "SEC-E")
CUTOFF = datetime(2024, 8, 1, 23, tzinfo=UTC)
START = date(2024, 1, 2)
END = date(2024, 7, 31)
SESSION_COUNT = 90


def _prices() -> tuple[ResearchPrice, ...]:
    sessions = generate_xnys_sessions(START, END, available_at=CUTOFF)
    prices: list[ResearchPrice] = []
    for index, session in enumerate(sessions):
        available = datetime.combine(
            session.session_date, datetime.min.time(), tzinfo=UTC
        ) + timedelta(hours=22)
        drifts = (0.0016, 0.0005, 0.0017, 0.0004, 0.0018)
        for symbol_index, security_id in enumerate(ALPHA_IDS):
            # SEC-B changed ticker from TB to TBN on 2024-03-01.
            if security_id == "SEC-B":
                ticker = "TBN" if session.session_date >= date(2024, 3, 1) else "TB"
            else:
                ticker = f"T{chr(ord('A') + symbol_index)}"
            base = 50.0 + symbol_index * 10.0
            drift = drifts[symbol_index]
            cycle = 0.005 * np.sin(index / (5.0 + symbol_index))
            close = base * ((1.0 + drift) ** index) * (1.0 + cycle)
            tr = close * 20.0  # total-return index scaled to track the close path
            prices.append(
                ResearchPrice(
                    permanent_security_id=security_id,
                    ticker=ticker,
                    observation_date=session.session_date,
                    available_at=available,
                    exchange="XNYS",
                    open=float(close * 0.999),
                    high=float(close * 1.001),
                    low=float(close * 0.998),
                    close=float(close),
                    volume=1_000_000 + symbol_index * 10_000,
                    adjustment_kind=AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE,
                    total_return_value=float(tr),
                    total_return_available_at=available,
                    adjustment_vintage_id=f"tr-{security_id}-{session.session_date.isoformat()}",
                    source="licensed fixture",
                    provider="licensed-historical",
                )
            )
        # Retain the delisted security's price history up to its delisting date
        # (survivorship-safe; the failed company is never deleted).
        if session.session_date <= date(2024, 2, 15):
            dead_close = 20.0 - index * 0.1
            dead_tr = 200.0 - index
            prices.append(
                ResearchPrice(
                    permanent_security_id="SEC-DEAD",
                    ticker="DEAD",
                    observation_date=session.session_date,
                    available_at=available,
                    exchange="XNYS",
                    open=float(dead_close * 0.999),
                    high=float(dead_close * 1.001),
                    low=float(dead_close * 0.998),
                    close=float(dead_close),
                    volume=500_000,
                    adjustment_kind=AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE,
                    total_return_value=float(dead_tr),
                    total_return_available_at=available,
                    adjustment_vintage_id=f"tr-DEAD-{session.session_date.isoformat()}",
                    source="licensed fixture",
                    provider="licensed-historical",
                )
            )
        benchmark = 400.0 * (1.0008 ** index)
        prices.append(
            ResearchPrice(
                permanent_security_id="SEC-BENCH",
                ticker="SPY",
                observation_date=session.session_date,
                available_at=available,
                exchange="XNYS",
                open=float(benchmark * 0.999),
                high=float(benchmark * 1.001),
                low=float(benchmark * 0.998),
                close=float(benchmark),
                volume=5_000_000,
                adjustment_kind=AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE,
                total_return_value=float(benchmark * 2.0),
                total_return_available_at=available,
                adjustment_vintage_id=f"tr-SPY-{session.session_date.isoformat()}",
                source="licensed fixture",
                provider="licensed-historical",
            )
        )
        qqq = 300.0 * (1.0009 ** index)
        prices.append(
            ResearchPrice(
                permanent_security_id="SEC-BENCH2",
                ticker="QQQ",
                observation_date=session.session_date,
                available_at=available,
                exchange="XNYS",
                open=float(qqq * 0.999),
                high=float(qqq * 1.001),
                low=float(qqq * 0.998),
                close=float(qqq),
                volume=4_000_000,
                adjustment_kind=AdjustmentKind.PIT_TOTAL_RETURN_VINTAGE,
                total_return_value=float(qqq),
                total_return_available_at=available,
                adjustment_vintage_id=f"tr-QQQ-{session.session_date.isoformat()}",
                source="licensed fixture",
                provider="licensed-historical",
            )
        )
    return tuple(prices)


def build_certified_package() -> ResearchDatasetPackage:
    securities = (
        HistoricalSecurity(
            "SEC-A", "TA", date(2024, 1, 2), None, "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-A",
        ),
        HistoricalSecurity(
            "SEC-B", "TB", date(2024, 1, 2), date(2024, 2, 29), "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-B",
        ),
        HistoricalSecurity(
            "SEC-B", "TBN", date(2024, 3, 1), None, "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2024, 2, 29, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-B",
        ),
        HistoricalSecurity(
            "SEC-C", "TC", date(2024, 1, 2), None, "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-C",
        ),
        HistoricalSecurity(
            "SEC-D", "TD", date(2024, 1, 2), None, "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-D",
        ),
        HistoricalSecurity(
            "SEC-E", "TE", date(2024, 1, 2), None, "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.US_EQUITY,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-E",
        ),
        HistoricalSecurity(
            "SEC-DEAD", "DEAD", date(2024, 1, 2), date(2024, 2, 15), "XNYS",
            date(2024, 1, 2), date(2024, 2, 15), "BANKRUPTCY", SecurityType.US_EQUITY,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-DEAD",
        ),
        HistoricalSecurity(
            "SEC-BENCH", "SPY", date(2024, 1, 2), None, "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.BENCHMARK,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-SPY",
        ),
        HistoricalSecurity(
            "SEC-BENCH2", "QQQ", date(2024, 1, 2), None, "XNYS",
            date(2024, 1, 2), None, "UNKNOWN", SecurityType.BENCHMARK,
            datetime(2023, 12, 1, tzinfo=UTC), "licensed fixture", "licensed-historical",
            provider_security_id="PERM-QQQ",
        ),
    )
    memberships = tuple(
        HistoricalUniverseMembership(
            security_id, "HIST-EQUITY", SecurityType.US_EQUITY,
            date(2024, 1, 2),
            (date(2024, 2, 15) if security_id == "SEC-DEAD" else None),
            datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC), "HISTORICAL_TIMELINE",
            "licensed fixture", "licensed-historical",
        )
        for security_id in (*ALPHA_IDS, "SEC-DEAD")
    ) + (
        HistoricalUniverseMembership(
            "SEC-BENCH", "HIST-BENCH", SecurityType.BENCHMARK,
            date(2024, 1, 2), None, datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC), "HISTORICAL_TIMELINE",
            "licensed fixture", "licensed-historical",
        ),
        HistoricalUniverseMembership(
            "SEC-BENCH2", "HIST-BENCH", SecurityType.BENCHMARK,
            date(2024, 1, 2), None, datetime(2023, 12, 20, tzinfo=UTC),
            datetime(2023, 12, 20, tzinfo=UTC), "HISTORICAL_TIMELINE",
            "licensed fixture", "licensed-historical",
        ),
    )
    actions = (
        ResearchCorporateAction(
            "SEC-B", "SYMBOL_CHANGE", date(2024, 3, 1), date(2024, 2, 28),
            datetime(2024, 2, 28, 12, tzinfo=UTC), "licensed fixture", "licensed-historical",
            successor_security_id="SEC-B",
        ),
        ResearchCorporateAction(
            "SEC-DEAD", "DELISTING", date(2024, 2, 15), date(2024, 2, 10),
            datetime(2024, 2, 10, 12, tzinfo=UTC), "licensed fixture", "licensed-historical",
            terminal_return=-0.85,
            terminal_price=1.50,
        ),
        ResearchCorporateAction(
            "SEC-A", "CASH_DIVIDEND", date(2024, 2, 1), date(2024, 1, 20),
            datetime(2024, 1, 20, 12, tzinfo=UTC), "licensed fixture", "licensed-historical",
            cash_amount=0.25,
        ),
    )
    sessions = generate_xnys_sessions(START, END, available_at=CUTOFF)
    package = ResearchDatasetPackage(
        dataset_id="round7-certified-fixture",
        schema_version="research-package-v1",
        provider="licensed-historical",
        source="licensed fixture",
        retrieved_at=CUTOFF - timedelta(days=1),
        as_of=END,
        cutoff=CUTOFF,
        use_scope=ResearchUseScope.TEST_FIXTURE,
        securities=securities,
        memberships=memberships,
        prices=_prices(),
        corporate_actions=actions,
        calendar=sessions,
        provider_version="2.0",
        acquisition_id="licensed-acq-2024-06-01",
        benchmark_universe_id="HIST-BENCH",
    )
    return package
