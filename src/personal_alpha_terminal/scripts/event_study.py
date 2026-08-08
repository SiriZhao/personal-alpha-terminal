import argparse
import logging
from datetime import date

from personal_alpha_terminal.analysis.event_study.repository import EventStudyRepository
from personal_alpha_terminal.analysis.event_study.service import EventStudyService
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create definitions and run persisted event studies."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    define = commands.add_parser("define", help="Create a new event definition version.")
    define.add_argument("--name", required=True)
    define.add_argument("--description")
    define.add_argument(
        "--rule-type",
        choices=("price_return", "volume_spike", "new_high"),
        required=True,
    )
    define.add_argument("--threshold", type=float, default=0.08)
    define.add_argument("--direction", choices=("above", "below"), default="above")
    define.add_argument("--lookback-days", type=int, default=20)
    define.add_argument("--multiplier", type=float, default=2.0)
    define.add_argument("--breakout-buffer", type=float, default=0.0)

    run = commands.add_parser("run", help="Run a saved event definition.")
    run.add_argument("--definition-id", type=int, required=True)
    run.add_argument("--trigger-stock-id", type=int, required=True)
    run.add_argument("--target-stock-id", type=int, action="append", required=True)
    run.add_argument("--start-date", type=date.fromisoformat, required=True)
    run.add_argument("--end-date", type=date.fromisoformat, required=True)
    run.add_argument("--horizon", type=int, action="append")
    run.add_argument("--cooldown-days", type=int)
    run.add_argument("--win-threshold", type=float)
    return parser


def run_command(args: argparse.Namespace) -> int:
    init_database()
    with session_scope() as session:
        service = EventStudyService(EventStudyRepository(session), get_settings())
        if args.command == "define":
            definition = service.create_definition(
                name=args.name,
                description=args.description,
                rule_type=args.rule_type,
                parameters=_definition_parameters(args),
            )
            logger.info(
                "Event definition saved: id=%s name=%s version=%s rule=%s",
                definition.id,
                definition.name,
                definition.version,
                definition.rule_type,
            )
            return 0

        result = service.run(
            definition_id=args.definition_id,
            trigger_stock_id=args.trigger_stock_id,
            target_stock_ids=tuple(args.target_stock_id),
            start_date=args.start_date,
            end_date=args.end_date,
            horizons=tuple(args.horizon) if args.horizon else None,
            cooldown_days=args.cooldown_days,
            win_threshold=args.win_threshold,
        )
    logger.info(
        "Event study completed: run_id=%s definition=%s trigger=%s events=%s statistic_rows=%s",
        result.run_id,
        result.definition.label,
        result.trigger.symbol,
        len(result.occurrences),
        len(result.statistics),
    )
    return 0


def _definition_parameters(args: argparse.Namespace) -> dict[str, object]:
    if args.rule_type == "price_return":
        return {
            "threshold": args.threshold,
            "direction": args.direction,
        }
    if args.rule_type == "volume_spike":
        return {
            "lookback_days": args.lookback_days,
            "multiplier": args.multiplier,
        }
    return {
        "lookback_days": args.lookback_days,
        "breakout_buffer": args.breakout_buffer,
    }


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging()
    try:
        exit_code = run_command(args)
    except ValueError as error:
        parser.error(str(error))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
