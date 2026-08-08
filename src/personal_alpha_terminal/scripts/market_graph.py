import argparse
import logging
from datetime import date

from personal_alpha_terminal.analysis.market_graph.repository import MarketGraphRepository
from personal_alpha_terminal.analysis.market_graph.service import MarketGraphService
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and persist a dynamic market relationship graph."
    )
    parser.add_argument("--instrument-id", type=int, action="append", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    return parser


def run(args: argparse.Namespace) -> int:
    init_database()
    with session_scope() as session:
        service = MarketGraphService(
            MarketGraphRepository(session),
            get_settings(),
        )
        result = service.run(
            instrument_ids=tuple(args.instrument_id),
            start_date=args.start_date,
            end_date=args.end_date,
        )
    logger.info(
        "Market graph completed: run_id=%s nodes=%s edges=%s paths=%s",
        result.run_id,
        len(result.nodes),
        len(result.edges),
        len(result.paths),
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
