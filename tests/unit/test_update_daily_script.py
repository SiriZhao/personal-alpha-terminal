from personal_alpha_terminal.scripts.update_daily_data import build_parser


def test_daily_update_parser_accepts_market_symbol_and_end_date() -> None:
    args = build_parser().parse_args(
        ["--market", "US", "--symbol", "AAPL", "--end-date", "2026-07-29"]
    )

    assert args.market == ["US"]
    assert args.symbol == ["AAPL"]
    assert args.end_date.isoformat() == "2026-07-29"
