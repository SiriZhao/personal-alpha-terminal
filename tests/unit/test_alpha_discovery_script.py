from datetime import date

from personal_alpha_terminal.scripts.run_alpha_discovery import build_parser


def test_alpha_discovery_parser_accepts_explicit_research_window() -> None:
    args = build_parser().parse_args(
        [
            "--market",
            "US",
            "--start-date",
            "2015-01-01",
            "--end-date",
            "2025-12-31",
            "--horizon",
            "21",
            "--rebalance-interval",
            "21",
        ]
    )

    assert args.market == "US"
    assert args.start_date == date(2015, 1, 1)
    assert args.end_date == date(2025, 12, 31)
    assert args.horizon == 21
