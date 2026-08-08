from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.models import (
    PortfolioPosition,
    PortfolioReconciliationRecord,
    SecurityMaster,
)


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    symbol: str
    quantity: float


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    snapshot_hash: str
    status: str
    differences: tuple[dict[str, object], ...]
    reconciled_at: datetime


class PortfolioReconciliationService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def reconcile(
        self,
        *,
        portfolio_id: int,
        broker: str,
        positions: tuple[BrokerPosition, ...],
        reconciled_at: datetime,
        source_file_hash: str | None = None,
    ) -> ReconciliationResult:
        if reconciled_at.tzinfo is None:
            raise ValueError("reconciliation timestamp must be timezone-aware")
        if len({item.symbol for item in positions}) != len(positions):
            raise ValueError("broker snapshot has duplicate symbols")
        broker_map = {item.symbol: item.quantity for item in positions}
        if any(quantity < 0 for quantity in broker_map.values()):
            raise ValueError("long-only broker quantities cannot be negative")
        latest_dates = self.session.execute(
            select(PortfolioPosition.stock_id, PortfolioPosition.as_of_date)
            .where(PortfolioPosition.portfolio_id == portfolio_id)
            .order_by(PortfolioPosition.stock_id, PortfolioPosition.as_of_date.desc())
        ).all()
        latest_by_stock: dict[int, object] = {}
        for stock_id, as_of_date in latest_dates:
            latest_by_stock.setdefault(stock_id, as_of_date)
        ledger: dict[str, float] = {}
        for stock_id, as_of_date in latest_by_stock.items():
            row = self.session.scalar(
                select(PortfolioPosition).where(
                    PortfolioPosition.portfolio_id == portfolio_id,
                    PortfolioPosition.stock_id == stock_id,
                    PortfolioPosition.as_of_date == as_of_date,
                )
            )
            security = self.session.get(SecurityMaster, stock_id)
            if row is not None and security is not None:
                ledger[security.symbol] = float(row.quantity)
        symbols = sorted(set(ledger) | set(broker_map))
        differences = tuple(
            {
                "symbol": symbol,
                "ledger_quantity": ledger.get(symbol, 0.0),
                "broker_quantity": broker_map.get(symbol, 0.0),
                "difference": broker_map.get(symbol, 0.0) - ledger.get(symbol, 0.0),
            }
            for symbol in symbols
            if abs(broker_map.get(symbol, 0.0) - ledger.get(symbol, 0.0)) > 1e-8
        )
        payload = {
            "portfolio_id": portfolio_id,
            "broker": broker,
            "positions": sorted(broker_map.items()),
            "reconciled_at": reconciled_at.isoformat(),
        }
        snapshot_hash = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        status = "RECONCILED" if not differences else "RECONCILIATION_REQUIRED"
        existing = self.session.scalar(
            select(PortfolioReconciliationRecord).where(
                PortfolioReconciliationRecord.portfolio_id == portfolio_id,
                PortfolioReconciliationRecord.snapshot_hash == snapshot_hash,
            )
        )
        if existing is None:
            self.session.add(
                PortfolioReconciliationRecord(
                    portfolio_id=portfolio_id,
                    snapshot_hash=snapshot_hash,
                    broker=broker,
                    status=status,
                    differences=list(differences),
                    reconciled_at=reconciled_at,
                    source_file_hash=source_file_hash,
                )
            )
            self.session.flush()
        return ReconciliationResult(snapshot_hash, status, differences, reconciled_at)
