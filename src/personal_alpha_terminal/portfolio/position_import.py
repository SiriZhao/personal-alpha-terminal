from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import Portfolio, PortfolioPosition, Stock


@dataclass(frozen=True, slots=True)
class PositionImportRow:
    symbol: str
    quantity: Decimal
    average_cost: Decimal | None


@dataclass(frozen=True, slots=True)
class ParsedPositionFile:
    format_name: str
    rows: tuple[PositionImportRow, ...]
    cash_balance: Decimal | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PositionImportResult:
    portfolio_id: int
    as_of_date: date
    imported_count: int
    unmatched_symbols: tuple[str, ...]
    cash_balance_updated: bool
    format_name: str
    warnings: tuple[str, ...]


def parse_position_csv(content: bytes) -> ParsedPositionFile:
    """Parse generic or Charles Schwab position exports without guessing assets."""

    if len(content) > 5_000_000:
        raise ValueError("position CSV exceeds the 5 MB local import limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = content.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ValueError("position CSV must use UTF-8 or Windows-1252 encoding") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("position CSV has no header")
    normalized = {_normalize_header(name): name for name in reader.fieldnames}
    is_schwab = "marketvalue" in normalized and (
        "costbasis" in normalized or "%ofaccount" in normalized
    )
    symbol_header = _required_header(normalized, "symbol", aliases=("ticker",))
    quantity_header = _required_header(normalized, "quantity", aliases=("shares",))
    average_header = normalized.get("averagecost") or normalized.get("pricepaid")
    cost_basis_header = normalized.get("costbasis")
    rows: list[PositionImportRow] = []
    cash_balance: Decimal | None = None
    warnings: list[str] = []
    seen: set[str] = set()
    for line_number, item in enumerate(reader, start=2):
        raw_symbol = (item.get(symbol_header) or "").strip()
        if not raw_symbol:
            continue
        symbol = raw_symbol.upper()
        if symbol in {"CASH", "CASH & CASH INVESTMENTS", "CASH&CASHEQUIVALENTS"}:
            market_value_header = normalized.get("marketvalue")
            if market_value_header is not None:
                cash_balance = _decimal(item.get(market_value_header), line_number, "cash")
            continue
        if symbol in seen:
            raise ValueError(f"duplicate symbol {symbol} at CSV line {line_number}")
        seen.add(symbol)
        quantity = _decimal(item.get(quantity_header), line_number, "quantity")
        if quantity <= 0:
            raise ValueError(f"quantity must be positive at CSV line {line_number}")
        average_cost: Decimal | None = None
        if average_header is not None and (item.get(average_header) or "").strip():
            average_cost = _decimal(item.get(average_header), line_number, "average cost")
        elif cost_basis_header is not None and (item.get(cost_basis_header) or "").strip():
            total_cost = _decimal(item.get(cost_basis_header), line_number, "cost basis")
            average_cost = total_cost / quantity
        if average_cost is not None and average_cost <= 0:
            raise ValueError(f"average cost must be positive at CSV line {line_number}")
        rows.append(PositionImportRow(symbol, quantity, average_cost))
    if not rows and cash_balance is None:
        raise ValueError("position CSV contains no importable holdings")
    if is_schwab:
        warnings.append(
            "Schwab position exports are snapshots, not transaction history; realized performance "
            "requires a separate transaction import."
        )
    return ParsedPositionFile(
        format_name="charles_schwab_positions" if is_schwab else "generic_positions",
        rows=tuple(rows),
        cash_balance=cash_balance,
        warnings=tuple(warnings),
    )


class PositionImportService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def import_snapshot(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
        parsed: ParsedPositionFile,
        market: str = "US",
    ) -> PositionImportResult:
        portfolio = self.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise ValueError("portfolio does not exist")
        symbols = {item.symbol for item in parsed.rows}
        stocks = tuple(
            self.session.scalars(
                select(Stock).where(
                    Stock.market == market,
                    Stock.symbol.in_(symbols),
                    Stock.is_active.is_(True),
                )
            )
        )
        by_symbol: dict[str, list[Stock]] = {}
        for stock in stocks:
            by_symbol.setdefault(stock.symbol.upper(), []).append(stock)
        ambiguous = sorted(symbol for symbol, matches in by_symbol.items() if len(matches) > 1)
        if ambiguous:
            raise ValueError(f"ambiguous security-master symbols: {ambiguous}")
        unmatched = tuple(sorted(symbols - set(by_symbol)))
        matched_rows = tuple(item for item in parsed.rows if item.symbol in by_symbol)
        if parsed.rows and not matched_rows:
            raise ValueError("no CSV symbols matched the US security master")
        self.session.execute(
            delete(PortfolioPosition).where(
                PortfolioPosition.portfolio_id == portfolio_id,
                PortfolioPosition.as_of_date == as_of_date,
            )
        )
        self.session.add_all(
            PortfolioPosition(
                portfolio_id=portfolio_id,
                stock_id=by_symbol[item.symbol][0].id,
                as_of_date=as_of_date,
                quantity=item.quantity,
                average_cost=item.average_cost,
            )
            for item in matched_rows
        )
        if parsed.cash_balance is not None:
            if parsed.cash_balance < 0:
                raise ValueError("cash balance cannot be negative")
            portfolio.cash_balance = parsed.cash_balance
        self.session.flush()
        warnings = list(parsed.warnings)
        if unmatched:
            warnings.append(
                "Unmatched symbols were not created automatically and were excluded: "
                + ", ".join(unmatched)
            )
        return PositionImportResult(
            portfolio_id=portfolio_id,
            as_of_date=as_of_date,
            imported_count=len(matched_rows),
            unmatched_symbols=unmatched,
            cash_balance_updated=parsed.cash_balance is not None,
            format_name=parsed.format_name,
            warnings=tuple(warnings),
        )

    def upsert_position(
        self,
        *,
        portfolio_id: int,
        as_of_date: date,
        symbol: str,
        quantity: Decimal,
        average_cost: Decimal | None,
        market: str = "US",
    ) -> PortfolioPosition:
        """Add or update one snapshot row without rewriting the real transaction ledger."""

        if self.session.get(Portfolio, portfolio_id) is None:
            raise ValueError("portfolio does not exist")
        normalized = symbol.strip().upper()
        if not normalized or quantity <= 0:
            raise ValueError("symbol and positive quantity are required")
        if average_cost is not None and average_cost <= 0:
            raise ValueError("average cost must be positive")
        matches = tuple(
            self.session.scalars(
                select(Stock).where(
                    Stock.market == market,
                    Stock.symbol == normalized,
                    Stock.is_active.is_(True),
                )
            )
        )
        if len(matches) != 1:
            raise ValueError("symbol must match exactly one active security-master record")
        stock = matches[0]
        position = self.session.scalar(
            select(PortfolioPosition).where(
                PortfolioPosition.portfolio_id == portfolio_id,
                PortfolioPosition.stock_id == stock.id,
                PortfolioPosition.as_of_date == as_of_date,
            )
        )
        if position is None:
            position = PortfolioPosition(
                portfolio_id=portfolio_id,
                stock_id=stock.id,
                as_of_date=as_of_date,
                quantity=quantity,
                average_cost=average_cost,
            )
            self.session.add(position)
        else:
            position.quantity = quantity
            position.average_cost = average_cost
        self.session.flush()
        return position


def _normalize_header(value: str) -> str:
    return "".join(
        character
        for character in value.lower()
        if character.isalnum() or character == "%"
    )


def _required_header(
    headers: dict[str, str], name: str, *, aliases: tuple[str, ...] = ()
) -> str:
    for key in (name, *aliases):
        if key in headers:
            return headers[key]
    raise ValueError(f"position CSV is missing required column: {name}")


def _decimal(value: str | None, line: int, label: str) -> Decimal:
    cleaned = (value or "").strip().replace(",", "").replace("$", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid {label} at CSV line {line}") from exc
    if not result.is_finite():
        raise ValueError(f"non-finite {label} at CSV line {line}")
    return result
