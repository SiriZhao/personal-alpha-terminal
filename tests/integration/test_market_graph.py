from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.analysis.market_graph.repository import MarketGraphRepository
from personal_alpha_terminal.analysis.market_graph.service import MarketGraphService
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.models import (
    MarketGraphEdge,
    MarketGraphNode,
    MarketGraphPath,
    MarketGraphRun,
    Price,
    Stock,
)


def pseudo_random_returns(count: int) -> list[float]:
    state = 29
    values = []
    for _ in range(count):
        state = (1103515245 * state + 12345) % (2**31)
        values.append(((state / (2**31)) - 0.5) / 20)
    return values


def add_stock(
    session: Session,
    symbol: str,
    returns: list[float],
    *,
    asset_type: str = "stock",
) -> Stock:
    stock = Stock(
        canonical_code=f"US:TEST:{symbol}",
        symbol=symbol,
        name=symbol,
        market="US",
        exchange="TEST",
        asset_type=asset_type,
        currency="USD",
        timezone="America/New_York",
    )
    session.add(stock)
    close = 100.0
    closes = [close]
    for daily_return in returns:
        close *= 1 + daily_return
        closes.append(close)
    start = date(2026, 1, 1)
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
                volume=None,
                source="yahoo_finance",
                ingested_at=datetime.combine(trade_date, datetime.min.time(), UTC),
            )
        )
    return stock


def test_market_graph_run_persists_metrics_edges_and_paths(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        first = pseudo_random_returns(100)
        second = [0.0, *first[:-1]]
        third = [0.0, *second[:-1]]
        nvda = add_stock(session, "NVDA", first)
        tsm = add_stock(session, "TSM", second)
        asml = add_stock(session, "ASML", third)
        commodity = add_stock(session, "GC=F", first, asset_type="commodity")
        session.commit()

        settings = Settings(
            _env_file=None,
            market_graph_minimum_observations=60,
            market_graph_correlation_threshold=0.99,
            market_graph_maximum_lag_days=3,
            market_graph_lead_threshold=0.8,
            market_graph_lead_improvement=0.1,
            market_graph_capital_threshold=1,
            market_graph_flow_lookback_days=20,
        )
        service = MarketGraphService(MarketGraphRepository(session), settings)
        result = service.run(
            instrument_ids=(nvda.id, tsm.id, asml.id, commodity.id),
            start_date=date(2026, 1, 2),
            end_date=date(2026, 4, 11),
        )
        session.commit()

        assert len(result.nodes) == 4
        assert any(
            edge.source.symbol == "NVDA"
            and edge.target.symbol == "TSM"
            and edge.relationship_type == "lead_lag"
            for edge in result.edges
        )
        assert any(
            [node.symbol for node in path.nodes] == ["NVDA", "TSM", "ASML"] for path in result.paths
        )
        assert session.scalar(select(func.count(MarketGraphNode.id))) == 4
        assert session.scalar(select(func.count(MarketGraphEdge.id))) == len(result.edges)
        assert session.scalar(select(func.count(MarketGraphPath.id))) == len(result.paths)
        stored_run = session.get(MarketGraphRun, result.run_id)
        assert stored_run is not None
        assert stored_run.parameters["capital_flow_is_proxy"] is True
        assert stored_run.parameters["significance_method"] == "fdr"
        stored_edges = list(session.scalars(select(MarketGraphEdge)))
        assert stored_edges
        assert all(item.p_value is not None for item in stored_edges)
        assert all(item.fdr_q_value is not None for item in stored_edges)
        assert all(item.significant_fdr for item in stored_edges)

        restored = service.latest()
        assert restored is not None
        assert restored.run_id == result.run_id
        assert len(restored.nodes) == 4

        stored_run.parameters = {}
        session.commit()
        assert service.latest() is None
