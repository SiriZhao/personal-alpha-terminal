import argparse
import logging
from datetime import date

from personal_alpha_terminal.analysis.lead_lag.repository import LeadLagRepository
from personal_alpha_terminal.analysis.lead_lag.service import LeadLagAnalysisService
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and persist cross-correlation and Granger lead-lag analysis."
    )
    parser.add_argument("--instrument-id", type=int, action="append", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--maximum-lag-days", type=int)
    return parser


def run(args: argparse.Namespace) -> int:
    init_database()
    with session_scope() as session:
        service = LeadLagAnalysisService(
            LeadLagRepository(session),
            get_settings(),
        )
        result = service.run(
            instrument_ids=tuple(args.instrument_id),
            start_date=args.start_date,
            end_date=args.end_date,
            maximum_lag_days=args.maximum_lag_days,
        )
    logger.info(
        "Lead-lag analysis completed: run_id=%s pairs=%s significant=%s",
        result.run_id,
        len(result.pairs),
        len(result.significant_pairs),
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
