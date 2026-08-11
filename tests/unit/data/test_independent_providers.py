from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from personal_alpha_terminal.application.universe import ResearchAsset
from personal_alpha_terminal.data.market_data.independent_providers import (
    AlphaVantageProvider,
    IndependentProviderError,
    IndependentProviderRouter,
    ProviderFailureCategory,
    TwelveDataProvider,
)

ASSET = ResearchAsset("SPY", "SPDR S&P 500 ETF", "ARCX", "etf", "benchmark")
STOCK = ResearchAsset("AAPL", "Apple", "XNAS", "stock", "technology")
START = date(2026, 8, 6)
LATEST = date(2026, 8, 7)


def _response(payload: object, status: int = 200):
    encoded = json.dumps(payload).encode("utf-8")
    return lambda _url, _timeout: (status, {}, encoded)


def _twelve_payload(latest: date = LATEST) -> dict[str, object]:
    return {
        "status": "ok",
        "meta": {"symbol": "SPY", "type": "ETF"},
        "values": [
            {"datetime": latest.isoformat(), "close": "637.10"},
            {"datetime": START.isoformat(), "close": "635.25"},
        ],
    }


def _alpha_payload(latest: date = LATEST, symbol: str = "SPY") -> dict[str, object]:
    return {
        "Meta Data": {"2. Symbol": symbol},
        "Time Series (Daily)": {
            latest.isoformat(): {"4. close": "637.10"},
            START.isoformat(): {"4. close": "635.25"},
        },
    }


def _twelve(tmp_path: Path, payload: object, *, key: str | None = "secret-key"):
    return TwelveDataProvider(
        api_key=key,
        max_retries=0,
        cache_dir=tmp_path,
        http_get=_response(payload),
    )


def _alpha(tmp_path: Path, payload: object, *, key: str | None = "secret-key"):
    return AlphaVantageProvider(
        api_key=key,
        max_retries=0,
        cache_dir=tmp_path,
        http_get=_response(payload),
    )


def test_twelve_data_supports_etf_and_reuses_latest_session_cache(tmp_path: Path) -> None:
    calls = 0

    def get(_url: str, _timeout: int):
        nonlocal calls
        calls += 1
        return 200, {}, json.dumps(_twelve_payload()).encode()

    provider = TwelveDataProvider(
        api_key="secret-key", max_retries=0, cache_dir=tmp_path, http_get=get
    )
    first = provider.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    second = provider.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert first.latest_session == LATEST
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert calls == 1
    health = IndependentProviderRouter(
        twelve=provider,
        alpha=_alpha(tmp_path / "alpha", {}, key=""),
    ).health()[0]
    assert health.latest_session == LATEST.isoformat()
    assert health.last_success is not None


def test_twelve_data_classifies_missing_auth(tmp_path: Path) -> None:
    provider = _twelve(tmp_path, _twelve_payload(), key="")
    with pytest.raises(IndependentProviderError) as captured:
        provider.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert captured.value.category is ProviderFailureCategory.AUTH_NOT_CONFIGURED


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        (
            {"status": "error", "code": 401, "message": "bad key"},
            ProviderFailureCategory.AUTH_FAILED,
        ),
        (
            {"status": "error", "code": 429, "message": "quota"},
            ProviderFailureCategory.RATE_LIMITED,
        ),
        ({"unexpected": []}, ProviderFailureCategory.SCHEMA_MISMATCH),
    ],
)
def test_twelve_data_classifies_error_payloads(
    tmp_path: Path, payload: object, category: ProviderFailureCategory
) -> None:
    with pytest.raises(IndependentProviderError) as captured:
        _twelve(tmp_path, payload).fetch(
            ASSET, START, LATEST, expected_latest_session=LATEST
        )
    assert captured.value.category is category


def test_twelve_data_rejects_malformed_json_and_missing_latest(tmp_path: Path) -> None:
    malformed = TwelveDataProvider(
        api_key="secret-key",
        max_retries=0,
        cache_dir=tmp_path,
        http_get=lambda _url, _timeout: (200, {}, b"not-json"),
    )
    with pytest.raises(IndependentProviderError) as captured:
        malformed.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert captured.value.category is ProviderFailureCategory.MALFORMED_RESPONSE

    with pytest.raises(IndependentProviderError) as captured:
        _twelve(tmp_path, _twelve_payload(START)).fetch(
            ASSET, START, LATEST, expected_latest_session=LATEST
        )
    assert captured.value.category is ProviderFailureCategory.LATEST_SESSION_MISSING


def test_provider_timeout_is_bounded_and_classified(tmp_path: Path) -> None:
    calls = 0

    def timeout(_url: str, _timeout: int):
        nonlocal calls
        calls += 1
        raise TimeoutError

    provider = TwelveDataProvider(
        api_key="secret-key",
        max_retries=1,
        retry_backoff_seconds=0,
        cache_dir=tmp_path,
        http_get=timeout,
    )
    with pytest.raises(IndependentProviderError) as captured:
        provider.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert captured.value.category is ProviderFailureCategory.TIMEOUT
    assert calls == 2


def test_old_cache_cannot_certify_a_new_latest_session(tmp_path: Path) -> None:
    calls = 0

    def get(_url: str, _timeout: int):
        nonlocal calls
        calls += 1
        return 200, {}, json.dumps(_twelve_payload()).encode()

    provider = TwelveDataProvider(
        api_key="secret-key", max_retries=0, cache_dir=tmp_path, http_get=get
    )
    provider.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    future_session = date(2026, 8, 10)
    with pytest.raises(IndependentProviderError) as captured:
        provider.fetch(ASSET, START, future_session, expected_latest_session=future_session)
    assert captured.value.category is ProviderFailureCategory.LATEST_SESSION_MISSING
    assert calls == 2


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        ({"Note": "frequency"}, ProviderFailureCategory.RATE_LIMITED),
        ({"Information": "premium endpoint"}, ProviderFailureCategory.API_INFORMATION),
        ({"Error Message": "bad symbol"}, ProviderFailureCategory.INVALID_SYMBOL),
        ({"Meta Data": {}}, ProviderFailureCategory.SCHEMA_MISMATCH),
    ],
)
def test_alpha_vantage_classifies_api_payloads(
    tmp_path: Path, payload: object, category: ProviderFailureCategory
) -> None:
    with pytest.raises(IndependentProviderError) as captured:
        _alpha(tmp_path, payload).fetch(
            ASSET, START, LATEST, expected_latest_session=LATEST
        )
    assert captured.value.category is category


def test_alpha_vantage_compact_history_and_latest_session(tmp_path: Path) -> None:
    result = _alpha(tmp_path, _alpha_payload()).fetch(
        ASSET, START, LATEST, expected_latest_session=LATEST
    )
    assert result.provider_id == "alpha_vantage"
    assert len(result.prices) == 2

    with pytest.raises(IndependentProviderError) as captured:
        _alpha(tmp_path / "missing", _alpha_payload(START)).fetch(
            ASSET, START, LATEST, expected_latest_session=LATEST
        )
    assert captured.value.category is ProviderFailureCategory.LATEST_SESSION_MISSING


def test_router_falls_back_from_twelve_to_alpha(tmp_path: Path) -> None:
    router = IndependentProviderRouter(
        twelve=_twelve(tmp_path / "twelve", {"status": "error", "code": 429}),
        alpha=_alpha(tmp_path / "alpha", _alpha_payload()),
    )
    result = router.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert result.provider_id == "alpha_vantage"
    assert [item.provider_id for item in result.attempts] == ["twelve_data", "alpha_vantage"]
    assert result.attempts[0].failure_category == "RATE_LIMITED"


def test_router_can_certify_different_symbols_with_multiple_secondaries(
    tmp_path: Path,
) -> None:
    def twelve_get(url: str, _timeout: int):
        payload = (
            _twelve_payload()
            if "symbol=SPY" in url
            else {"status": "error", "code": 429, "message": "quota"}
        )
        return 200, {}, json.dumps(payload).encode()

    router = IndependentProviderRouter(
        twelve=TwelveDataProvider(
            api_key="secret-key",
            max_retries=0,
            cache_dir=tmp_path / "twelve",
            http_get=twelve_get,
        ),
        alpha=_alpha(tmp_path / "alpha", _alpha_payload(symbol="AAPL")),
    )

    spy = router.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    aapl = router.fetch(STOCK, START, LATEST, expected_latest_session=LATEST)

    assert spy.provider_id == "twelve_data"
    assert aapl.provider_id == "alpha_vantage"
    assert {spy.provider_id, aapl.provider_id} == {"twelve_data", "alpha_vantage"}


def test_provider_rejects_response_for_a_different_symbol(tmp_path: Path) -> None:
    with pytest.raises(IndependentProviderError) as twelve_error:
        _twelve(tmp_path / "twelve", _twelve_payload()).fetch(
            STOCK, START, LATEST, expected_latest_session=LATEST
        )
    assert twelve_error.value.category is ProviderFailureCategory.SCHEMA_MISMATCH

    with pytest.raises(IndependentProviderError) as alpha_error:
        _alpha(tmp_path / "alpha", _alpha_payload()).fetch(
            STOCK, START, LATEST, expected_latest_session=LATEST
        )
    assert alpha_error.value.category is ProviderFailureCategory.SCHEMA_MISMATCH


def test_router_uses_stooq_only_as_best_effort(tmp_path: Path, monkeypatch) -> None:
    router = IndependentProviderRouter(
        twelve=_twelve(tmp_path / "twelve", {}, key=""),
        alpha=_alpha(tmp_path / "alpha", {}, key=""),
    )
    monkeypatch.setattr(router, "_stooq", lambda *_args: {START: 100.0, LATEST: 101.0})
    result = router.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert result.provider_id == "stooq"
    assert result.attempts[-1].status == "PASS"


def test_router_fails_closed_when_all_independent_sources_fail(
    tmp_path: Path, monkeypatch
) -> None:
    router = IndependentProviderRouter(
        twelve=_twelve(tmp_path / "twelve", {}, key=""),
        alpha=_alpha(tmp_path / "alpha", {}, key=""),
    )
    monkeypatch.setattr(
        router,
        "_stooq",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("challenge")),
    )
    with pytest.raises(IndependentProviderError) as captured:
        router.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert captured.value.category is ProviderFailureCategory.PROVIDER_UNAVAILABLE
    assert {item.provider_id for item in captured.value.attempts} == {
        "twelve_data",
        "alpha_vantage",
        "stooq",
    }


def test_api_key_is_absent_from_errors_and_cache(tmp_path: Path) -> None:
    secret = "TOP-SECRET-INDEPENDENT-KEY"
    provider = _twelve(
        tmp_path,
        {"status": "error", "code": 401, "message": f"invalid {secret}"},
        key=secret,
    )
    with pytest.raises(IndependentProviderError) as captured:
        provider.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert secret not in str(captured.value)

    good = _twelve(tmp_path / "good", _twelve_payload(), key=secret)
    good.fetch(ASSET, START, LATEST, expected_latest_session=LATEST)
    assert secret not in next((tmp_path / "good").rglob("*.json")).read_text(encoding="utf-8")
