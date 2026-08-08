import argparse
import logging
from datetime import date

from personal_alpha_terminal.core.config import get_settings
from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import init_database, session_scope
from personal_alpha_terminal.portfolio.repository import PortfolioRiskRepository
from personal_alpha_terminal.portfolio.schemas import StressScenario
from personal_alpha_terminal.portfolio.service import PortfolioRiskService

logger = logging.getLogger(__name__)


def currency_shock(value: str) -> tuple[str, float]:
    try:
        currency, raw_shock = value.split("=", maxsplit=1)
        normalized = currency.strip().upper()
        shock = float(raw_shock)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "currency shock must use CODE=DECIMAL, for example USD=0.20"
        ) from error
    if len(normalized) != 3 or not normalized.isalpha():
        raise argparse.ArgumentTypeError("currency code must contain three letters")
    if not -1 <= shock <= 10:
        raise argparse.ArgumentTypeError("currency shock must be between -1 and 10")
    return normalized, shock


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Calculate and persist portfolio risk and stress scenarios."
    )
    parser.add_argument("--portfolio-id", type=int, required=True)
    parser.add_argument("--benchmark-id", type=int, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--end-date", type=date.fromisoformat, required=True)
    parser.add_argument("--scenario-name", default="Custom stress")
    parser.add_argument(
        "--benchmark-shock",
        type=float,
        default=0.0,
        help="Decimal return, for example -0.30.",
    )
    parser.add_argument(
        "--currency-shock",
        type=currency_shock,
        action="append",
        default=[],
        metavar="CODE=DECIMAL",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    init_database()
    scenario = StressScenario(
        name=args.scenario_name,
        benchmark_shock=args.benchmark_shock,
        currency_shocks=dict(args.currency_shock),
    )
    with session_scope() as session:
        result = PortfolioRiskService(
            PortfolioRiskRepository(session),
            get_settings(),
        ).run(
            portfolio_id=args.portfolio_id,
            benchmark_stock_id=args.benchmark_id,
            start_date=args.start_date,
            end_date=args.end_date,
            scenarios=(scenario,),
        )
        stress = result.stress_tests[0]
        logger.info(
            "Portfolio risk completed: run_id=%s value=%.2f beta=%s "
            "stress_pnl=%.2f%% uncovered=%.2f%%",
            result.risk.run_id,
            result.risk.total_value,
            f"{result.risk.beta:.4f}" if result.risk.beta is not None else "NA",
            stress.pnl_percent * 100,
            stress.uncovered_weight * 100,
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
