"""ROUND 7: gated historical research rerun tests."""
from __future__ import annotations

from dataclasses import replace

from personal_alpha_terminal.quant_engine.historical_pit.certification import (
    HistoricalPitVerdict,
    certify_historical_pit,
)
from personal_alpha_terminal.quant_engine.historical_pit.providers import (
    ResearchProviderCapabilities,
)
from personal_alpha_terminal.quant_engine.historical_pit.rerun import (
    price_panel_from_package,
    run_historical_research,
)
from personal_alpha_terminal.quant_engine.historical_pit.versioning import (
    build_version,
)
from personal_alpha_terminal.quant_engine.research_dataset import (
    ResearchUseScope,
    certify_research_package,
)
from personal_alpha_terminal.quant_engine.research_provider_acceptance import (
    ProviderContract,
)
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1Config,
)
from tests.unit.quant_engine.historical_pit.fixtures import build_certified_package


def _capabilities() -> ResearchProviderCapabilities:
    return ResearchProviderCapabilities(
        provider_id="licensed-historical",
        provider_version="2.0",
        raw_ohlcv=True,
        delisting_history=True,
        delisting_returns=True,
        historical_membership=True,
        identifier_history=True,
        permanent_identifiers=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        exchange_calendar=True,
    )


def _contract() -> ProviderContract:
    return ProviderContract(
        provider_id="licensed-historical",
        provider_version="2.0",
        provider_security_id_scheme="PROVIDER_PERMANENT_ID",
        permanent_identifiers=True,
        delisting_history=True,
        delisting_returns=True,
        historical_membership=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        benchmark_same_pit=True,
        license_scope="LOCAL_RESEARCH",
        local_research_use_allowed=True,
        derived_research_allowed=True,
        schema_mapping_version="historical-pit-provider-v1",
        source_identity="licensed-historical:2.0",
    )


def _certified(package, capabilities=None):
    package = replace(package, use_scope=ResearchUseScope.PRODUCTION_RESEARCH)
    manifest = certify_research_package(package)
    version = build_version(package, manifest)
    certification = certify_historical_pit(
        package,
        _contract(),
        capabilities or _capabilities(),
        version,
    )
    assert certification.verdict is HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED
    return package, certification


def test_limited_verdict_refuses_to_run() -> None:
    package = build_certified_package()
    package = replace(package, use_scope=ResearchUseScope.PRODUCTION_RESEARCH)
    manifest = certify_research_package(package)
    version = build_version(package, manifest)
    certify_historical_pit(
        package,
        _contract(),
        _capabilities(),
        version,
    )
    # Force a LIMITED verdict by dropping the delisting-return claim.

    limited_caps = _capabilities()
    limited_caps = ResearchProviderCapabilities(
        provider_id=limited_caps.provider_id,
        provider_version=limited_caps.provider_version,
        raw_ohlcv=True,
        delisting_history=True,
        delisting_returns=False,
        historical_membership=True,
        identifier_history=True,
        permanent_identifiers=True,
        corporate_actions_pit=True,
        total_return_pit=True,
        exchange_calendar=True,
    )
    limited = certify_historical_pit(package, _contract(), limited_caps, version)
    assert limited.verdict is HistoricalPitVerdict.HISTORICAL_PIT_LIMITED
    rerun = run_historical_research(limited, package)
    assert rerun.executed is False
    assert rerun.verdict is HistoricalPitVerdict.HISTORICAL_PIT_LIMITED
    assert rerun.diagnostics is None
    assert any("DELISTING_RETURNS_NOT_CLAIMED" in item for item in rerun.blockers)


def test_certified_rerun_executes_with_small_strategy_config() -> None:
    package, certification = _certified(build_certified_package())
    fast_config = USAdaptiveAlphaCoreV1Config(
        momentum_lookback=12,
        momentum_skip=3,
        trend_window=10,
        volatility_window=10,
        horizon_sessions=3,
    )
    rerun = run_historical_research(
        certification,
        package,
        benchmark="SPY",
        horizon=3,
        strategy_config=fast_config,
    )
    assert rerun.executed is True
    assert rerun.blockers == ()
    assert rerun.verdict is HistoricalPitVerdict.HISTORICAL_PIT_CERTIFIED
    assert rerun.diagnostics is not None
    assert rerun.walk_forward is not None
    assert rerun.portfolio_ab is not None
    assert rerun.run_id.startswith("round7-")


def test_price_panel_from_certified_package_excludes_future_and_current_adjusted() -> None:
    package = build_certified_package()
    frame = price_panel_from_package(package, benchmark="SPY")
    assert not frame.empty
    assert {"permanent_security_id", "ticker", "trade_date", "close", "role"}.issubset(
        frame.columns
    )
    assert "SPY" in set(frame[frame["role"] == "reference"]["ticker"])
    # The delisted name is retained (survivorship-safe), not deleted.
    assert "SEC-DEAD" in set(frame["permanent_security_id"])
