"""ROUND40 broker read-only contract and manual transaction import.

This module intentionally exposes no order-submission methods.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Protocol


class BrokerReadOnlyAdapter(Protocol):
    """Read-only broker interface. No order/write methods are allowed."""

    def account_snapshot(self) -> dict[str, object]: ...

    def balances(self) -> dict[str, object]: ...

    def positions(self) -> tuple[dict[str, object], ...]: ...

    def transaction_history(self) -> tuple[dict[str, object], ...]: ...

    def symbol_mapping(self) -> dict[str, str]: ...


@dataclass(frozen=True, slots=True)
class BrokerTransaction:
    account_id: str
    external_id: str
    trade_date: date
    executed_at: datetime | None
    symbol: str
    action: str
    quantity: float
    price: float
    fees: float


def parse_transaction_csv(path: Path) -> tuple[BrokerTransaction, ...]:
    """Strictly parse broker-exported transaction history."""

    rows: list[BrokerTransaction] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        required = {
            "account_id",
            "external_id",
            "trade_date",
            "symbol",
            "action",
            "quantity",
            "price",
            "fees",
        }
        missing = required - set(reader.fieldnames)
        if missing:
            raise ValueError(f"CSV missing required columns: {sorted(missing)}")
        for row in reader:
            account_id = str(row["account_id"]).strip()
            external_id = str(row["external_id"]).strip()
            symbol = str(row["symbol"]).strip().upper()
            action = str(row["action"]).strip().upper()
            trade_date = date.fromisoformat(str(row["trade_date"]).strip())
            if not account_id or not external_id or not symbol:
                raise ValueError("account, external id, and symbol are required")
            if action not in {"BUY", "SELL"}:
                raise ValueError(f"unsupported action: {action}")
            quantity = float(row["quantity"])
            price = float(row["price"])
            fees = float(row["fees"])
            if quantity <= 0 or price <= 0 or fees < 0:
                raise ValueError("quantity/price/fees are invalid")
            executed_at_raw = str(row.get("executed_at") or "").strip()
            executed_at = (
                datetime.fromisoformat(executed_at_raw.replace("Z", "+00:00"))
                if executed_at_raw
                else None
            )
            if executed_at is not None and executed_at.tzinfo is None:
                executed_at = executed_at.replace(tzinfo=UTC)
            rows.append(
                BrokerTransaction(
                    account_id,
                    external_id,
                    trade_date,
                    executed_at,
                    symbol,
                    action,
                    quantity,
                    price,
                    fees,
                )
            )
    external_ids = [row.external_id for row in rows]
    if len(external_ids) != len(set(external_ids)):
        raise ValueError("CSV contains duplicate external transaction ids")
    return tuple(rows)


def schwab_readiness(*, credentials_configured: bool) -> dict[str, object]:
    if credentials_configured:
        return {
            "status": "SCHWAB_READONLY_CONNECTED",
            "write_path": "NONE",
        }
    return {
        "status": "SCHWAB_READONLY_READY_AUTH_REQUIRED",
        "write_path": "NONE",
        "note": "Live OAuth is not configured; no connection is fabricated.",
    }
