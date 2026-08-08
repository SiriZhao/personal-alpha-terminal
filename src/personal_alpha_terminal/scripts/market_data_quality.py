import argparse
from datetime import date
from pathlib import Path

from personal_alpha_terminal.core.logging import configure_logging
from personal_alpha_terminal.data.database import session_scope
from personal_alpha_terminal.data.market_data_quality.report import render_markdown
from personal_alpha_terminal.data.market_data_quality.repository import (
    MarketDataQualityRepository,
)
from personal_alpha_terminal.data.market_data_quality.sampling import (
    DEFAULT_SAMPLING_PLAN,
    PRODUCTION_STOCK_CERTIFICATION_PLAN,
)
from personal_alpha_terminal.data.market_data_quality.service import (
    MarketDataQualityService,
)
from personal_alpha_terminal.data.migrations import upgrade_database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=("Run the fail-closed market-data quality gate and write an auditable report.")
    )
    parser.add_argument(
        "--history-start",
        type=date.fromisoformat,
        default=date(2010, 1, 1),
    )
    parser.add_argument("--history-end", type=date.fromisoformat, default=None)
    parser.add_argument("--seed", type=int, default=20260731)
    parser.add_argument(
        "--scope",
        choices=("full", "production-stocks"),
        default="full",
        help=(
            "full retains ETF/new/delisted coverage; production-stocks runs the "
            "three-market 100-stock certification gate"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("DATA_QUALITY_REPORT.md"),
    )
    return parser


def run(args: argparse.Namespace) -> int:
    upgrade_database()
    with session_scope() as session:
        service = MarketDataQualityService(MarketDataQualityRepository(session))
        run_id, report = service.run(
            history_start=args.history_start,
            history_end=args.history_end,
            seed=args.seed,
            plan=(
                PRODUCTION_STOCK_CERTIFICATION_PLAN
                if args.scope == "production-stocks"
                else DEFAULT_SAMPLING_PLAN
            ),
        )
        content = render_markdown(report, run_id=run_id)

    report_path: Path = args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content, encoding="utf-8")
    return 0 if report.status.value == "passed" else 2


def main() -> None:
    configure_logging()
    args = build_parser().parse_args()
    raise SystemExit(run(args))


if __name__ == "__main__":
    main()
