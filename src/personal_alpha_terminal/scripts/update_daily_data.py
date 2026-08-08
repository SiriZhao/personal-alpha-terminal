import argparse
import logging
from datetime import date
from typing import cast

from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope
from personal_alpha_terminal.data.market_data import Market, build_market_data_engine

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Incrementally update daily market data for registered instruments."
    )
    parser.add_argument(
        "--market",
        action="append",
        choices=("A", "HK", "US"),
        help="Restrict updates to a market. May be repeated.",
    )
    parser.add_argument(
        "--symbol",
        action="append",
        help="Restrict updates to a registered symbol; requires exactly one --market.",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=None,
        help=(
            "Force an inclusive historical re-fetch from YYYY-MM-DD. "
            "Use after timestamp-safety migrations."
        ),
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Inclusive end date in YYYY-MM-DD format. Defaults to today.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    raw_markets: list[str] | None = args.market
    markets = {cast(Market, market) for market in raw_markets} if raw_markets else None
    symbols = set(args.symbol) if args.symbol else None
    if symbols and (not markets or len(markets) != 1):
        raise ValueError("--symbol requires exactly one --market.")

    init_database()
    with session_scope() as session:
        engine = build_market_data_engine(session)
        report = engine.update_daily_data(
            markets=markets,
            symbols=symbols,
            start_date=args.start_date,
            end_date=args.end_date,
        )

    if not report.results:
        logger.warning("No active registered instruments matched the update filters.")

    for result in report.results:
        logger.info(
            "Daily update result: market=%s symbol=%s source=%s provider=%s status=%s "
            "fetched=%s valid=%s inserted=%s updated=%s issues=%s error=%s",
            result.market,
            result.symbol,
            result.source,
            result.provider,
            result.status,
            result.fetched_count,
            result.valid_count,
            result.inserted_count,
            result.updated_count,
            len(result.quality_issues),
            result.error,
        )
    logger.info(
        "Daily update completed: success=%s no_data=%s failed=%s inserted=%s updated=%s",
        report.success_count,
        report.no_data_count,
        report.failure_count,
        report.inserted_count,
        report.updated_count,
    )
    if not report.analysis_safe:
        logger.error(
            "Daily data is not safe for downstream analysis; analytical jobs must remain blocked."
        )
        return 1
    return 0


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    try:
        exit_code = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
