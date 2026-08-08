from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.lead_lag.repository import LeadLagRepository
from personal_alpha_terminal.analysis.lead_lag.service import LeadLagAnalysisService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    LeadLagAnalysisRun,
    LeadLagMetric,
    LeadLagPairResult,
    Price,
    Stock,
)


def pseudo_random_values(count: int, seed: int) -> list[float]:
    state = seed
    values: list[float] = []
    for _ in range(count):
        state = (1103515245 * state + 12345) % (2**31)
        values.append((state / (2**31) - 0.5) / 30)
    return values


def add_stock(session: Session, symbol: str, returns: list[float]) -> Stock:
    stock = Stock(
        canonical_code=f"US:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="TEST",
        currency="USD",
        timezone="America/New_York",
    )
    session.add(stock)
    close = 100.0
    closes = [close]
    for daily_return in returns:
        close *= 1 + daily_return
        closes.append(close)
    start = date(2025, 1, 1)
    for index, value in enumerate(closes):
        trade_date = start + timedelta(days=index)
        decimal_value = Decimal(str(value))
        session.add(
            Price(
                stock=stock,
                trade_date=trade_date,
                open=decimal_value,
                high=decimal_value,
                low=decimal_value,
                close=decimal_value,
                adjusted_close=decimal_value,
                volume=1_000_000,
                source="yahoo_finance",
                ingested_at=datetime.combine(trade_date, datetime.min.time(), UTC),
            )
        )
    return stock


def test_lead_lag_run_persists_and_restores_auditable_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        source_returns = pseudo_random_values(260, 19)
        noise = pseudo_random_values(260, 83)
        target_returns = [
            0.1 * noise[index] + (0.9 * source_returns[index - 2] if index >= 2 else noise[index])
            for index in range(260)
        ]
        nvda = add_stock(session, "NVDA", source_returns)
        tsm = add_stock(session, "TSM", target_returns)
        session.commit()

        settings = Settings(
            _env_file=None,
            lead_lag_minimum_observations=120,
            lead_lag_maximum_lag_days=5,
            lead_lag_minimum_abs_correlation=0.5,
            lead_lag_fdr_alpha=0.1,
        )
        service = LeadLagAnalysisService(LeadLagRepository(session), settings)
        result = service.run(
            instrument_ids=(nvda.id, tsm.id),
            start_date=date(2025, 1, 2),
            end_date=date(2025, 9, 18),
        )
        session.commit()

        relationship = next(
            pair
            for pair in result.pairs
            if pair.source.symbol == "NVDA" and pair.target.symbol == "TSM"
        )
        assert relationship.best_lag_days == 2
        assert relationship.is_significant
        assert relationship.confidence_score > 0.99
        assert session.scalar(select(func.count(LeadLagAnalysisRun.id))) == 1
        assert session.scalar(select(func.count(LeadLagPairResult.id))) == 2
        assert session.scalar(select(func.count(LeadLagMetric.id))) == 10

        stored_run = session.get(LeadLagAnalysisRun, result.run_id)
        assert stored_run is not None
        assert stored_run.parameters["within_pair_correction"] == "bonferroni"
        restored = service.latest()
        assert restored is not None
        assert restored.run_id == result.run_id
        assert len(restored.pairs) == 2
        assert restored.significant_pairs[0].source.symbol == "NVDA"
