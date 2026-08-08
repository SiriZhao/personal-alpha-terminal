import argparse
import logging
from datetime import date

from personal_alpha_terminal.analysis.conditional_probability.repository import (
    ConditionalProbabilityRepository,
)
from personal_alpha_terminal.analysis.conditional_probability.service import (
    ConditionalProbabilityService,
)
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Estimate and persist P(B future move | A event).")
    parser.add_argument("--definition-id", type=int, required=True)
    parser.add_argument("--trigger-stock-id", type=int, required=True)
    parser.add_argument("--target-stock-id", type=int, action="append", required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--direction", choices=("up", "down"), default="up")
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument("--horizon", type=int, action="append")
    parser.add_argument("--minimum-sample-size", type=int)
    parser.add_argument("--confidence-level", type=float)
    parser.add_argument("--cooldown-days", type=int)
    return parser


def run(args: argparse.Namespace) -> int:
    init_database()
    with session_scope() as session:
        service = ConditionalProbabilityService(
            ConditionalProbabilityRepository(session),
            get_settings(),
        )
        result = service.run(
            definition_id=args.definition_id,
            trigger_stock_id=args.trigger_stock_id,
            target_stock_ids=tuple(args.target_stock_id),
            start_date=args.start_date,
            end_date=args.end_date,
            outcome_direction=args.direction,
            outcome_threshold=args.threshold,
            horizons=tuple(args.horizon) if args.horizon else None,
            minimum_sample_size=args.minimum_sample_size,
            confidence_level=args.confidence_level,
            cooldown_days=args.cooldown_days,
        )
    logger.info(
        "Conditional probability completed: run_id=%s event_study_run_id=%s "
        "events=%s reliable_results=%s total_results=%s",
        result.run_id,
        result.event_study_run_id,
        result.event_count,
        sum(item.meets_minimum for item in result.results),
        len(result.results),
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
