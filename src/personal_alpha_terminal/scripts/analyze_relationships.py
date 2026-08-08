import argparse
import logging
from datetime import date, timedelta

from personal_alpha_terminal.analysis.relationships.repository import RelationshipRepository
from personal_alpha_terminal.analysis.relationships.service import RelationshipAnalysisService
from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate and persist market relationship analysis."
    )
    parser.add_argument(
        "--universe",
        choices=("stock", "etf", "industry"),
        required=True,
        help="Entity type to analyze.",
    )
    parser.add_argument(
        "--entity-id",
        action="append",
        type=int,
        help="Database entity ID. Repeat for multiple entities; defaults to all.",
    )
    parser.add_argument(
        "--method",
        choices=("pearson", "spearman"),
        default="pearson",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=date.today() - timedelta(days=730),
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=date.today(),
    )
    return parser


def run(args: argparse.Namespace) -> int:
    init_database()
    with session_scope() as session:
        service = RelationshipAnalysisService(
            RelationshipRepository(session),
            get_settings(),
        )
        entity_ids = (
            tuple(args.entity_id)
            if args.entity_id
            else tuple(option.id for option in service.list_entities(args.universe))
        )
        result = service.run(
            universe_type=args.universe,
            entity_ids=entity_ids,
            method=args.method,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    logger.info(
        "Relationship analysis completed: run_id=%s universe=%s method=%s "
        "entities=%s matrix_pairs=%s rolling_observations=%s anomalies=%s",
        result.run_id,
        result.universe_type,
        result.method,
        len(result.entities),
        len(result.matrix),
        len(result.rolling),
        len(result.anomalies),
    )
    return 0


def main() -> None:
    configure_logging()
    parser = build_parser()
    try:
        exit_code = run(parser.parse_args())
    except ValueError as error:
        parser.error(str(error))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
