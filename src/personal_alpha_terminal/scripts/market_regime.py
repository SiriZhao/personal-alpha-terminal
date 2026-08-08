import argparse
import logging
from datetime import date

from personal_alpha_terminal.analysis.market_regime.repository import (
    MarketRegimeRepository,
)
from personal_alpha_terminal.analysis.market_regime.service import MarketRegimeService
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and persist explainable statistical market-regime detection."
    )
    parser.add_argument("--vix-stock-id", type=int, required=True)
    parser.add_argument("--rate-stock-id", type=int, required=True)
    parser.add_argument("--dollar-stock-id", type=int, required=True)
    parser.add_argument("--benchmark-stock-id", type=int, required=True)
    parser.add_argument("--market", choices=("A", "HK", "US"), required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    return parser


def run(args: argparse.Namespace) -> int:
    init_database()
    with session_scope() as session:
        service = MarketRegimeService(
            MarketRegimeRepository(session),
            get_settings(),
        )
        result = service.run(
            vix_stock_id=args.vix_stock_id,
            rate_stock_id=args.rate_stock_id,
            dollar_stock_id=args.dollar_stock_id,
            benchmark_stock_id=args.benchmark_stock_id,
            market=args.market,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    probabilities = result.current.probabilities
    if probabilities is None:
        logger.info(
            "Market regime completed: run_id=%s state=%s score=%.2f "
            "calibration=%s brier=%s",
            result.run_id,
            result.current.regime,
            max(result.current.scores.values()),
            result.calibration.status,
            result.calibration.brier_score,
        )
    else:
        logger.info(
            "Market regime completed: run_id=%s state=%s calibrated_probability=%.2f "
            "brier=%.4f",
            result.run_id,
            result.current.regime,
            max(probabilities.values()),
            result.calibration.brier_score,
        )
    return 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging()
    try:
        exit_code = run(args)
    except ValueError as error:
        parser.error(str(error))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
