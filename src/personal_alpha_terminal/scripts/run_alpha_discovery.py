import argparse
import logging
from datetime import date

from personal_alpha_terminal.alpha_discovery.repository import (
    AlphaDiscoveryRepository,
)
from personal_alpha_terminal.alpha_discovery.schemas import AlphaDiscoveryConfig
from personal_alpha_terminal.alpha_discovery.service import AlphaDiscoveryService
from personal_alpha_terminal.analysis.factors.repository import (
    FactorResearchRepository,
)
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import session_scope
from personal_alpha_terminal.data.migrations import upgrade_database
from personal_alpha_terminal.reports.service import ResearchReportService

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run point-in-time alpha hypothesis discovery. "
            "This produces research evidence, not trade signals."
        )
    )
    parser.add_argument("--market", required=True, choices=("A", "HK", "US"))
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    parser.add_argument("--horizon", type=int, default=21)
    parser.add_argument("--rebalance-interval", type=int, default=21)
    parser.add_argument("--minimum-cross-section", type=int, default=20)
    parser.add_argument("--minimum-dates-per-split", type=int, default=12)
    return parser


def run(args: argparse.Namespace) -> int:
    config = AlphaDiscoveryConfig(
        horizon_days=args.horizon,
        rebalance_interval=args.rebalance_interval,
        minimum_cross_section=args.minimum_cross_section,
        minimum_dates_per_split=args.minimum_dates_per_split,
    )
    upgrade_database()
    with session_scope() as session:
        service = AlphaDiscoveryService(
            FactorResearchRepository(session),
            AlphaDiscoveryRepository(session),
            ResearchReportService(session),
        )
        result, _report = service.run_from_database(
            market=args.market,
            start_date=args.start_date,
            end_date=args.end_date,
            config=config,
        )
        confirmed = sum(item.status == "test_confirmed" for item in result.combinations)
        logger.info(
            "Alpha discovery completed: run_id=%s market=%s fingerprint=%s "
            "factors=%s combinations_tested=%s selected=%s test_confirmed=%s",
            result.run_id,
            result.market,
            result.data_fingerprint,
            result.tested_factor_count,
            result.tested_combination_count,
            len(result.combinations),
            confirmed,
        )
    return 0


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    try:
        exit_code = run(args)
    except ValueError as error:
        parser.error(str(error))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
