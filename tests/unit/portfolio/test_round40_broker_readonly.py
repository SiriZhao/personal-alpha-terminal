from __future__ import annotations

import csv
from pathlib import Path

import pytest

from personal_alpha_terminal.portfolio.broker_readonly import (
    parse_transaction_csv,
    schwab_readiness,
)


def _csv_path(tmp_path: Path) -> Path:
    path = tmp_path / "transactions.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "account_id",
                "external_id",
                "trade_date",
                "symbol",
                "action",
                "quantity",
                "price",
                "fees",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "account_id": "A1",
                "external_id": "t1",
                "trade_date": "2026-08-14",
                "symbol": "aaa",
                "action": "buy",
                "quantity": "10",
                "price": "100",
                "fees": "1",
            }
        )
    return path


def test_csv_import_normalizes_symbol_and_duplicate_ids_are_rejected(
    tmp_path: Path,
) -> None:
    rows = parse_transaction_csv(_csv_path(tmp_path))
    assert rows[0].symbol == "AAA"
    with pytest.raises(ValueError, match="duplicate"):
        duplicate = _csv_path(tmp_path)
        duplicate.write_text(
            duplicate.read_text(encoding="utf-8")
            + "A1,t1,2026-08-14,AAA,BUY,1,100,0\n",
            encoding="utf-8",
        )
        parse_transaction_csv(duplicate)


def test_schwab_readiness_never_fabricates_connection() -> None:
    result = schwab_readiness(credentials_configured=False)
    assert result["status"] == "SCHWAB_READONLY_READY_AUTH_REQUIRED"
    assert result["write_path"] == "NONE"
