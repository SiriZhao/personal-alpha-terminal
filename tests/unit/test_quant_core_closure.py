from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.core.audit_lock import AuditBuildLock
from personal_alpha_terminal.core.config import Settings
from personal_alpha_terminal.core.runtime_context import RuntimeContext, RuntimeProfile
from personal_alpha_terminal.data.us_market.repository import USPointInTimeRepository
from personal_alpha_terminal.models import (
    FundamentalVintage,
    MarketUniverseSnapshot,
    ModelRegistryRecord,
    SecurityMaster,
    SymbolAlias,
    TradingStatus,
    UniverseDefinition,
    UniverseMembership,
)
from personal_alpha_terminal.quant_engine.model_registry import (
    ModelPromotionEvidence,
    ModelRegistryService,
)


def _security(symbol: str, available: datetime, **overrides: object) -> SecurityMaster:
    values: dict[str, object] = {
        "canonical_code": f"US-XNAS-{symbol}",
        "symbol": symbol,
        "name": symbol,
        "market": "US",
        "exchange": "XNAS",
        "asset_type": "stock",
        "currency": "USD",
        "timezone": "America/New_York",
        "list_date": date(2010, 1, 4),
        "delist_date": None,
        "is_active": True,
        "source": "fixture_archive",
        "provider": "fixture_primary",
        "available_time": available,
        "ingested_time": available,
    }
    values.update(overrides)
    return SecurityMaster(**values)


def test_runtime_profiles_never_share_the_production_database(tmp_path: Path) -> None:
    desktop = RuntimeContext.from_settings(
        Settings(runtime_profile="PRODUCTION_DESKTOP"),
        project_root=tmp_path / "project",
        local_app_data=tmp_path / "local",
    )
    test_db = tmp_path / "tests" / "isolated.db"
    test = RuntimeContext.from_settings(
        Settings(runtime_profile="TEST", database_url=f"sqlite:///{test_db.as_posix()}"),
        project_root=tmp_path / "project",
        local_app_data=tmp_path / "local",
    )

    assert desktop.profile is RuntimeProfile.PRODUCTION_DESKTOP
    assert desktop.database_path == (
        tmp_path / "local" / "PersonalAlphaTerminal" / "data" / "personal_alpha.db"
    )
    assert test.database_path == test_db
    with pytest.raises(RuntimeError, match="split-brain"):
        desktop.assert_same_database(test.database_url)


def test_audit_lock_detects_source_hash_drift(tmp_path: Path) -> None:
    source = tmp_path / "src" / "package.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="source hash drifted"):
        with AuditBuildLock(tmp_path, purpose="test"):
            source.write_text("VALUE = 2\n", encoding="utf-8")


def test_pit_universe_rejects_future_membership_and_resolves_historical_ticker(
    session_factory: sessionmaker[Session],
) -> None:
    cutoff = datetime(2020, 6, 30, 21, tzinfo=UTC)
    with session_factory.begin() as session:
        old = _security("OLD", cutoff - timedelta(days=365))
        future = _security("FUT", cutoff - timedelta(days=365))
        session.add_all((old, future))
        session.flush()
        definition = UniverseDefinition(
            definition_id="US-CORE",
            version="1",
            market="US",
            name="Certified fixture universe",
            rules={"fixture": True},
            source="licensed_archive",
            provider="independent_primary",
            capability_status="CERTIFIED",
        )
        session.add(definition)
        session.flush()
        session.add_all(
            (
                UniverseMembership(
                    definition_id=definition.id,
                    stock_id=old.id,
                    effective_from=date(2019, 1, 1),
                    effective_to=None,
                    announcement_time=cutoff - timedelta(days=550),
                    available_time=cutoff - timedelta(days=550),
                    ingested_time=cutoff - timedelta(days=500),
                    inclusion_reason="historical member",
                    market_cap=100_000_000_000,
                    revision_id="v1",
                    source="licensed_archive",
                    provider="independent_primary",
                ),
                UniverseMembership(
                    definition_id=definition.id,
                    stock_id=future.id,
                    effective_from=date(2020, 7, 1),
                    effective_to=None,
                    announcement_time=cutoff + timedelta(hours=1),
                    available_time=cutoff + timedelta(hours=1),
                    ingested_time=cutoff + timedelta(hours=2),
                    inclusion_reason="future member",
                    market_cap=50_000_000_000,
                    revision_id="v1",
                    source="licensed_archive",
                    provider="independent_primary",
                ),
                SymbolAlias(
                    stock_id=old.id,
                    exchange="XNAS",
                    symbol="OLD",
                    normalized_symbol="OLD",
                    valid_from=date(2010, 1, 4),
                    valid_to=date(2020, 12, 31),
                    available_time=cutoff - timedelta(days=365),
                    ingested_time=cutoff - timedelta(days=365),
                    source="licensed_archive",
                    provider="independent_primary",
                ),
            )
        )
        snapshot = MarketUniverseSnapshot(
            market="US",
            as_of_date=cutoff.date(),
            source="licensed_archive",
            provider="independent_primary",
            available_time=cutoff - timedelta(minutes=1),
            ingested_time=cutoff - timedelta(minutes=1),
            definition_id=definition.id,
            version_id="snapshot-v1",
            data_version="data-v1",
            content_hash="a" * 64,
            certification_status="CERTIFIED",
        )
        session.add(snapshot)
        session.flush()
        session.add(
            TradingStatus(
                stock_id=old.id,
                status="TRADABLE",
                effective_time=cutoff - timedelta(days=1),
                available_time=cutoff - timedelta(days=1),
                ingested_time=cutoff - timedelta(days=1),
                reason="regular listing",
                source="exchange_archive",
                provider="independent_primary",
            )
        )

    with session_factory() as session:
        repository = USPointInTimeRepository(session)
        universe = repository.certified_universe(as_of=cutoff)
        resolved = repository.resolve_symbol(exchange="XNAS", symbol="OLD", as_of=cutoff)

        assert [item.symbol for item in universe.securities] == ["OLD"]
        assert resolved.canonical_code == "US-XNAS-OLD"
        with pytest.raises(ValueError, match="alias is unavailable"):
            repository.resolve_symbol(exchange="XNAS", symbol="FUT", as_of=cutoff)


def test_fundamental_restatement_is_invisible_before_available_time(
    session_factory: sessionmaker[Session],
) -> None:
    initial_time = datetime(2022, 2, 1, 22, tzinfo=UTC)
    restatement_time = datetime(2023, 2, 1, 22, tzinfo=UTC)
    with session_factory.begin() as session:
        security = _security("PIT", initial_time - timedelta(days=1000))
        session.add(security)
        session.flush()
        session.add_all(
            (
                FundamentalVintage(
                    stock_id=security.id,
                    fiscal_period_end=date(2021, 12, 31),
                    period_type="annual",
                    filing_id="10K-2021",
                    filing_date=date(2022, 2, 1),
                    publication_time=initial_time,
                    available_at=initial_time,
                    revision_id="original",
                    is_restatement=False,
                    original_values={"roic": 0.2},
                    restated_values=None,
                    currency="USD",
                    unit_scale=1,
                    accounting_standard="US-GAAP",
                    source="sec",
                    provider="archive",
                    ingested_at=initial_time,
                ),
                FundamentalVintage(
                    stock_id=security.id,
                    fiscal_period_end=date(2021, 12, 31),
                    period_type="annual",
                    filing_id="10K-2021",
                    filing_date=date(2023, 2, 1),
                    publication_time=restatement_time,
                    available_at=restatement_time,
                    revision_id="restated",
                    is_restatement=True,
                    original_values={"roic": 0.2},
                    restated_values={"roic": 0.9},
                    currency="USD",
                    unit_scale=1,
                    accounting_standard="US-GAAP",
                    source="sec",
                    provider="archive",
                    ingested_at=restatement_time,
                ),
            )
        )

    with session_factory() as session:
        repository = USPointInTimeRepository(session)
        security = session.query(SecurityMaster).filter_by(symbol="PIT").one()
        before = repository.fundamental_snapshot(
            (security,), as_of=initial_time + timedelta(days=30)
        )
        after = repository.fundamental_snapshot(
            (security,), as_of=restatement_time + timedelta(days=1)
        )

        assert before is not None and float(before.iloc[0]["quality"]) == pytest.approx(0.2)
        assert after is not None and float(after.iloc[0]["quality"]) == pytest.approx(0.9)


def test_model_status_string_cannot_bypass_promotion_evidence(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory.begin() as session:
        registry = ModelRegistryService(session)
        record = registry.ensure_registered(
            model_id="test-model",
            version="1",
            objective="test",
            inputs=["PIT"],
            data_requirements=["certified"],
            hyperparameters={"x": 1},
            limitations=[],
        )
        record.status = "Tested"
        with pytest.raises(ValueError, match="requires locked OOS"):
            registry.promote(
                record,
                ModelPromotionEvidence(
                    data_version="d1",
                    parameter_fingerprint="p1",
                    validation_manifest_hash="v1",
                    locked_oos=False,
                    pit_certified=True,
                    survivorship_bias_controlled=True,
                    costs_included=True,
                    approved_by="test",
                ),
            )

    with session_factory() as session:
        stored = session.query(ModelRegistryRecord).filter_by(model_id="test-model").one()
        assert stored.status == "Tested"
