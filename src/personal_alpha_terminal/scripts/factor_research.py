import argparse
import logging
from datetime import date

from personal_alpha_terminal.analysis.factors.repository import (
    FactorResearchRepository,
)
from personal_alpha_terminal.analysis.factors.service import FactorResearchService
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate factor scores or run point-in-time factor backtests."
    )
    subparsers = parser.add_subparsers(dest="mode", required=True)
    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--market", choices=("A", "HK", "US"), required=True)
    snapshot.add_argument("--as-of-date", type=date.fromisoformat, required=True)
    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--market", choices=("A", "HK", "US"), required=True)
    backtest.add_argument("--start-date", type=date.fromisoformat, required=True)
    backtest.add_argument("--end-date", type=date.fromisoformat, required=True)
    return parser


def run(args: argparse.Namespace) -> int:
    init_database()
    with session_scope() as session:
        service = FactorResearchService(
            FactorResearchRepository(session),
            get_settings(),
        )
        if args.mode == "snapshot":
            result = service.run_snapshot(
                market=args.market,
                as_of_date=args.as_of_date,
            )
            logger.info(
                "Factor snapshot completed: run_id=%s stocks=%s",
                result.run_id,
                len(result.scores),
            )
        else:
            backtest = service.run_backtest(
                market=args.market,
                start_date=args.start_date,
                end_date=args.end_date,
            )
            logger.info(
                "Factor backtest completed: run_id=%s periods=%s cumulative=%.2f",
                backtest.run_id,
                len(backtest.periods),
                backtest.summary.cumulative_return,
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
