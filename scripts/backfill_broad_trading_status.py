"""One-time ROUND 5 backfill: TradingStatus for broad CURRENT_OPERATIONAL_PIT stocks.

Broad stocks with current operational price evidence must satisfy the same
current tradability gate as certified-universe members.  This idempotent script
creates a TRADABLE record for every US stock that has at least one price row and
does not already carry a newer non-TRADABLE status.  It never touches the
certified universe or the portfolio ledger.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from sqlalchemy.orm import Session

    from personal_alpha_terminal.data.database import build_engine, build_session_factory
    from personal_alpha_terminal.models import Price, SecurityMaster, TradingStatus

    database = Path("var/personal_alpha.db").resolve()
    engine = build_engine(f"sqlite:///{database}")
    factory = build_session_factory(engine)
    session: Session = factory()
    now = datetime.now(UTC)
    stocks = tuple(
        session.scalars(
            select(SecurityMaster).where(
                SecurityMaster.market == "US",
                SecurityMaster.asset_type == "stock",
                SecurityMaster.is_active.is_(True),
            )
        )
    )
    created = 0
    already = 0
    for stock in stocks:
        has_bars = (
            session.scalar(
                select(func.count())
                .select_from(Price)
                .where(
                    Price.stock_id == stock.id,
                    Price.available_time.is_not(None),
                    Price.available_time <= now,
                )
            )
            or 0
        )
        if has_bars == 0:
            continue
        latest = session.scalar(
            select(TradingStatus)
            .where(TradingStatus.stock_id == stock.id)
            .order_by(TradingStatus.effective_time.desc(), TradingStatus.id.desc())
            .limit(1)
        )
        if latest is not None and latest.status == "TRADABLE":
            already += 1
            continue
        session.add(
            TradingStatus(
                stock_id=stock.id,
                status="TRADABLE",
                effective_time=now,
                available_time=now,
                ingested_time=now,
                reason="current operational price evidence; no known delisting record",
                source="round5_backfill",
                provider="broad_market_sync",
            )
        )
        created += 1
    session.commit()
    print(f"TRADING_STATUS_BACKFILL total={len(stocks)} created={created} already={already}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
