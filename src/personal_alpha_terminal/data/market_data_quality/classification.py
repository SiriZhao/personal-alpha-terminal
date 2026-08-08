from personal_alpha_terminal.data.market_data_quality.schemas import (
    MarketSegment,
    UniverseCandidate,
)


def validate_symbol_mapping(candidate: UniverseCandidate) -> None:
    """Validate canonical market/exchange mapping without guessing board from prefixes."""

    exchange = candidate.exchange.upper()
    symbol = candidate.symbol.upper()
    if candidate.market == "A":
        if len(symbol) != 6 or not symbol.isdigit():
            raise ValueError(f"A-share symbol must be six digits: {candidate.symbol}")
        if exchange not in {"SSE", "XSHG", "SZSE", "XSHE"}:
            raise ValueError(f"Unsupported A-share exchange: {candidate.exchange}")
        sse_segments = {
            MarketSegment.SSE_MAIN,
            MarketSegment.STAR,
            MarketSegment.A_ETF,
        }
        szse_segments = {
            MarketSegment.SZSE_MAIN,
            MarketSegment.CHINEXT,
            MarketSegment.A_ETF,
        }
        allowed = sse_segments if exchange in {"SSE", "XSHG"} else szse_segments
        if candidate.segment not in allowed:
            raise ValueError(
                f"{candidate.segment.value} is inconsistent with exchange {exchange}."
            )
        return

    if candidate.market == "US":
        if not symbol or any(character.isspace() for character in symbol):
            raise ValueError(f"Invalid US symbol: {candidate.symbol}")
        expected = {
            MarketSegment.NYSE: {"NYSE", "XNYS"},
            MarketSegment.NASDAQ: {"NASDAQ", "XNAS"},
            MarketSegment.US_ETF: {"NYSE", "XNYS", "NASDAQ", "XNAS", "ARCX"},
            MarketSegment.US_INDEX: {"XCBO"},
        }
        if exchange not in expected.get(candidate.segment, set()):
            raise ValueError(
                f"{candidate.segment.value} is inconsistent with exchange {exchange}."
            )
        return

    if not symbol.isdigit() or len(symbol) > 5:
        raise ValueError(f"Hong Kong symbol must be numeric: {candidate.symbol}")
    if exchange not in {"HKEX", "XHKG"}:
        raise ValueError(f"Unsupported Hong Kong exchange: {candidate.exchange}")
    if candidate.segment not in {MarketSegment.HK_MAIN, MarketSegment.HK_ETF}:
        raise ValueError(f"Unsupported Hong Kong segment: {candidate.segment.value}")
