from datetime import UTC, date, datetime
from typing import Any, cast

import pytest

from personal_alpha_terminal.data.production_market_data import providers
from personal_alpha_terminal.data.production_market_data.providers import (
    ArchivedSecurityMasterCSVAdapter,
    HKEXSecurityMasterAdapter,
)
from personal_alpha_terminal.data.production_market_data.reference_adapters import (
    ExchangeCalendarsAdapter,
)
from personal_alpha_terminal.data.production_market_data.repository import (
    ProductionMarketDataRepository,
)


def test_archived_security_master_requires_exact_point_in_time_snapshot(tmp_path) -> None:
    fixture = tmp_path / "security_master.csv"
    fixture.write_text(
        "snapshot_date,symbol,name,market,exchange,currency,timezone,listing_date,"
        "delisting_date,security_type,is_active,segment,source,provider,available_time\n"
        "2020-01-02,AAPL,Apple,US,NASDAQ,USD,America/New_York,1980-12-12,,"
        "stock,true,nasdaq,nasdaq_trader,immutable_archive,2020-01-02T22:00:00+00:00\n",
        encoding="utf-8",
    )

    batch = ArchivedSecurityMasterCSVAdapter().read(
        fixture,
        expected_snapshot_date=date(2020, 1, 2),
    )

    assert batch.snapshot_date == date(2020, 1, 2)
    assert batch.records[0].canonical_code == "US:NASDAQ:AAPL"
    assert not batch.research_eligible
    repository = ProductionMarketDataRepository(cast(Any, object()))
    with pytest.raises(ValueError, match="not certified for research"):
        repository.store_snapshot(batch=batch, securities=[])
    trusted_batch = ArchivedSecurityMasterCSVAdapter(trusted_archive=True).read(
        fixture,
        expected_snapshot_date=date(2020, 1, 2),
    )
    assert trusted_batch.research_eligible
    with pytest.raises(ValueError, match="does not match expected snapshot date"):
        ArchivedSecurityMasterCSVAdapter().read(
            fixture,
            expected_snapshot_date=date(2019, 12, 31),
        )


def test_exchange_calendar_has_explicit_open_and_closed_dates() -> None:
    rows = ExchangeCalendarsAdapter().fetch_sessions(
        exchange="NYSE",
        start_date=date(2026, 7, 4),
        end_date=date(2026, 7, 6),
    )

    assert [row.session_date for row in rows] == [
        date(2026, 7, 4),
        date(2026, 7, 5),
        date(2026, 7, 6),
    ]
    assert [row.is_open for row in rows] == [False, False, True]
    assert rows[0].open_time is None and rows[0].close_time is None
    assert rows[2].open_time is not None and rows[2].close_time is not None
    assert rows[2].available_time <= datetime.now(UTC)


def test_hkex_adapter_parses_embedded_header_and_rejects_future_publication(
    monkeypatch,
) -> None:
    import pandas as pd

    raw = pd.DataFrame(
        [
            ["List of Securities", None, None, None, None],
            ["Updated as at 03/08/2026", None, None, None, None],
            [
                "Stock Code",
                "Name of Securities",
                "Category",
                "Sub-Category",
                "Trading Currency",
            ],
            [
                "00001",
                "CKH HOLDINGS",
                "Equity",
                "Equity Securities (Main Board)",
                "HKD",
            ],
        ]
    )
    monkeypatch.setattr(providers.importlib, "import_module", lambda _name: pd)
    monkeypatch.setattr(pd, "read_excel", lambda *_args, **_kwargs: raw)

    with pytest.raises(ValueError, match="future-dated"):
        HKEXSecurityMasterAdapter().fetch_current(as_of_date=date(2026, 7, 31))

    batch = HKEXSecurityMasterAdapter().fetch_current(as_of_date=date(2026, 8, 3))
    assert batch.research_eligible
    assert len(batch.records) == 1
    assert batch.records[0].symbol == "00001"
    assert batch.records[0].segment.value == "hk_main"
