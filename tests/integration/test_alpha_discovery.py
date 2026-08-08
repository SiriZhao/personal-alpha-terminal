from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.alpha_discovery.factor_generator import FACTOR_BY_NAME
from personal_alpha_terminal.alpha_discovery.repository import (
    AlphaDiscoveryRepository,
)
from personal_alpha_terminal.alpha_discovery.schemas import AlphaDiscoveryConfig
from personal_alpha_terminal.alpha_discovery.service import AlphaDiscoveryService
from personal_alpha_terminal.analysis.factors.repository import (
    FactorResearchRepository,
)
from personal_alpha_terminal.analysis.factors.schemas import (
    FactorAssetData,
    FactorDataset,
    FactorPricePoint,
)
from personal_alpha_terminal.analysis.market_graph.schemas import GraphInstrument
from personal_alpha_terminal.models import (
    AlphaCombinationResult,
    AlphaDiscoveryRun,
    AlphaFactorEvaluation,
    ResearchReport,
)
from personal_alpha_terminal.reports.service import ResearchReportService


def _dataset() -> FactorDataset:
    assets: list[FactorAssetData] = []
    for asset_index in range(8):
        close = 100.0
        prices: list[FactorPricePoint] = []
        for day_index in range(130):
            close *= 1 + 0.0005 * (asset_index + 1)
            prices.append(
                FactorPricePoint(
                    date=date(2020, 1, 1) + timedelta(days=day_index),
                    close=close,
                    raw_close=close,
                )
            )
        assets.append(
            FactorAssetData(
                instrument=GraphInstrument(
                    id=asset_index + 1,
                    key=f"stock:{asset_index + 1}",
                    symbol=f"S{asset_index + 1}",
                    name=f"S{asset_index + 1}",
                    market="US",
                    asset_type="stock",
                    industry="Test",
                ),
                prices=tuple(prices),
                financials=(),
            )
        )
    return FactorDataset(assets=tuple(assets))


def test_alpha_discovery_persists_split_ic_combinations_and_report(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        service = AlphaDiscoveryService(
            FactorResearchRepository(session),
            AlphaDiscoveryRepository(session),
            ResearchReportService(session),
        )
        result, report = service.run(
            _dataset(),
            market="US",
            start_date=date(2020, 1, 26),
            end_date=date(2020, 4, 20),
            config=AlphaDiscoveryConfig(
                horizon_days=5,
                rebalance_interval=5,
                minimum_cross_section=6,
                minimum_dates_per_split=3,
                train_fraction=0.50,
                validation_fraction=0.25,
                maximum_combination_size=1,
                maximum_universe_size=20,
            ),
            definitions=(FACTOR_BY_NAME["momentum_1m"],),
            data_sources=("synthetic:prices",),
        )
        session.commit()

        assert result.run_id is not None
        assert result.combinations
        assert result.combinations[0].status == "test_confirmed"
        assert report.subject_key == str(result.run_id)
        assert session.scalar(select(func.count(AlphaDiscoveryRun.id))) == 1
        assert session.scalar(select(func.count(AlphaFactorEvaluation.id))) == 3
        assert session.scalar(select(func.count(AlphaCombinationResult.id))) == 1
        assert (
            session.scalar(
                select(func.count(ResearchReport.id)).where(
                    ResearchReport.report_type == "alpha_discovery"
                )
            )
            == 1
        )
