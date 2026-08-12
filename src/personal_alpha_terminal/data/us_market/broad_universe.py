"""Current broad-US security directory and point-in-time eligibility filters.

The Nasdaq Trader symbol directory is a *current* listing source.  It is useful
for discovering today's listed securities, but its rows are never backfilled
into historical membership.  Historical research continues to require the
separate survivorship-safe research-data contract.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from io import StringIO
from pathlib import Path
from statistics import median
from urllib.request import Request, urlopen

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


class CurrentSecurityType(StrEnum):
    COMMON_STOCK = "COMMON_STOCK"
    ADR = "ADR"
    REIT = "REIT"
    ETF = "ETF"
    ETN = "ETN"
    PREFERRED = "PREFERRED"
    WARRANT = "WARRANT"
    RIGHT = "RIGHT"
    UNIT = "UNIT"
    CLOSED_END_FUND = "CLOSED_END_FUND"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class UniverseRole(StrEnum):
    ALPHA_EQUITY = "ALPHA_EQUITY"
    BENCHMARK = "BENCHMARK"
    REGIME_PROXY = "REGIME_PROXY"
    RISK_REFERENCE = "RISK_REFERENCE"


class SurvivorshipStatus(StrEnum):
    SURVIVORSHIP_SAFE = "SURVIVORSHIP_SAFE"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True, slots=True)
class CurrentSecurityMasterRecord:
    security_id: str
    symbol: str
    company_name: str
    security_type: CurrentSecurityType
    exchange: str
    currency: str
    country: str
    listing_date: date | None
    delisting_date: date | None
    active_from: date
    active_to: date | None
    is_common_stock: bool
    is_etf: bool
    is_adr: bool
    is_reit: bool
    is_preferred: bool
    is_warrant: bool
    is_unit: bool
    is_right: bool
    is_otc: bool
    sector: str | None
    industry: str | None
    test_issue: bool
    financial_status: str
    source: str
    effective_date: date
    available_at: datetime

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("security available_at must be timezone-aware")
        if self.effective_date < self.active_from:
            raise ValueError("security effective_date cannot precede active_from")


@dataclass(frozen=True, slots=True)
class SymbolDirectoryCapabilities:
    prices: bool = False
    current_listings: bool = True
    historical_membership: bool = False
    delistings: bool = False
    identifier_history: bool = False
    corporate_actions: bool = False
    total_return_vintages: bool = False
    exchange_classification: bool = True
    etf_classification: bool = True
    common_stock_classification: str = "CONSERVATIVE_NAME_RULES"


@dataclass(frozen=True, slots=True)
class CurrentDirectorySnapshot:
    dataset_id: str
    provider: str
    retrieved_at: datetime
    source_timestamp: str
    records: tuple[CurrentSecurityMasterRecord, ...]
    content_hash: str
    manifest_hash: str
    survivorship_status: SurvivorshipStatus = SurvivorshipStatus.UNVERIFIED
    historical_use_allowed: bool = False
    capabilities: SymbolDirectoryCapabilities = SymbolDirectoryCapabilities()

    def __post_init__(self) -> None:
        if self.retrieved_at.tzinfo is None:
            raise ValueError("directory retrieved_at must be timezone-aware")
        if not self.records:
            raise ValueError("current directory snapshot cannot be empty")

    @property
    def dataset_version(self) -> str:
        return self.content_hash

    def document(self) -> dict[str, object]:
        return {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "provider": self.provider,
            "retrieved_at": self.retrieved_at.isoformat(),
            "source_timestamp": self.source_timestamp,
            "row_count": len(self.records),
            "content_hash": self.content_hash,
            "manifest_hash": self.manifest_hash,
            "survivorship_status": self.survivorship_status,
            "historical_use_allowed": self.historical_use_allowed,
            "capabilities": asdict(self.capabilities),
        }


@dataclass(frozen=True, slots=True)
class EligibilityRules:
    minimum_price: float = 5.0
    minimum_trading_sessions: int = 252
    minimum_average_dollar_volume: float = 10_000_000.0
    minimum_median_dollar_volume: float = 10_000_000.0
    minimum_valid_bar_coverage: float = 0.98
    maximum_missing_ratio: float = 0.02
    include_adr: bool = False
    include_reit: bool = False
    # Production default: the factor universe requires a certified PIT
    # total-return series (corporate-action integrity).  The broad *price-based*
    # ranking layer may set this False; such a universe is explicitly labeled
    # PRICE_BASED_RANKING and never claims total-return or corporate-action
    # certification.
    require_pit_total_return: bool = True
    allowed_exchanges: tuple[str, ...] = ("XNAS", "XNYS", "XASE")

    def __post_init__(self) -> None:
        if self.minimum_price <= 0 or self.minimum_trading_sessions < 1:
            raise ValueError("universe price/history thresholds must be positive")
        if self.minimum_average_dollar_volume <= 0 or self.minimum_median_dollar_volume <= 0:
            raise ValueError("universe liquidity thresholds must be positive")
        if not 0 <= self.maximum_missing_ratio <= 1:
            raise ValueError("maximum_missing_ratio must be in [0, 1]")
        if not 0 <= self.minimum_valid_bar_coverage <= 1:
            raise ValueError("minimum_valid_bar_coverage must be in [0, 1]")

    @property
    def fingerprint(self) -> str:
        return _hash(asdict(self))


@dataclass(frozen=True, slots=True)
class SecurityEligibilityObservation:
    security_id: str
    symbol: str
    as_of_date: date
    available_at: datetime
    latest_price: float | None
    observed_sessions: int
    average_dollar_volume: float | None
    median_dollar_volume: float | None
    valid_bar_coverage: float
    missing_ratio: float
    corporate_action_integrity: bool
    feature_available: bool

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None:
            raise ValueError("eligibility observation available_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class BroadUniverseEligibility:
    universe_date: date
    decision_time: datetime
    raw_listed_securities: int
    raw_listed_equities: int
    security_type_eligible: tuple[CurrentSecurityMasterRecord, ...]
    data_eligible: tuple[CurrentSecurityMasterRecord, ...]
    liquidity_eligible: tuple[CurrentSecurityMasterRecord, ...]
    factor_eligible: tuple[CurrentSecurityMasterRecord, ...]
    signal_eligible: tuple[CurrentSecurityMasterRecord, ...]
    exclusions: dict[str, tuple[str, ...]]
    rules_fingerprint: str
    snapshot_hash: str
    pit_status: str
    survivorship_status: SurvivorshipStatus

    def counts(self) -> dict[str, int]:
        return {
            "raw_listed_securities": self.raw_listed_securities,
            "raw_listed_equities": self.raw_listed_equities,
            "security_type_eligible": len(self.security_type_eligible),
            "data_eligible": len(self.data_eligible),
            "liquidity_eligible": len(self.liquidity_eligible),
            "factor_eligible": len(self.factor_eligible),
            "signal_eligible": len(self.signal_eligible),
        }


class NasdaqTraderSymbolDirectoryAdapter:
    """Read the official current symbol directory with an injected HTTP boundary."""

    provider_id = "nasdaq_trader_symbol_directory"

    def __init__(self, fetch_text: Callable[[str], str] | None = None) -> None:
        self._fetch_text = fetch_text or _download_text

    def fetch(self, *, retrieved_at: datetime | None = None) -> CurrentDirectorySnapshot:
        observed_at = retrieved_at or datetime.now(UTC)
        if observed_at.tzinfo is None:
            raise ValueError("directory retrieval timestamp must be timezone-aware")
        return parse_symbol_directories(
            self._fetch_text(NASDAQ_LISTED_URL),
            self._fetch_text(OTHER_LISTED_URL),
            retrieved_at=observed_at,
        )


def parse_symbol_directories(
    nasdaq_text: str,
    other_text: str,
    *,
    retrieved_at: datetime,
) -> CurrentDirectorySnapshot:
    """Normalize Nasdaq/NYSE/NYSE-American current rows without historical backfill."""

    if retrieved_at.tzinfo is None:
        raise ValueError("directory retrieval timestamp must be timezone-aware")
    effective_date = _directory_effective_date(
        nasdaq_text,
        other_text,
        fallback=retrieved_at.date(),
    )
    records: list[CurrentSecurityMasterRecord] = []
    source_times: list[str] = []
    for row in csv.DictReader(StringIO(nasdaq_text), delimiter="|"):
        symbol = (row.get("Symbol") or "").strip().upper()
        if symbol.startswith("FILE CREATION TIME"):
            source_times.append(symbol)
            continue
        if not symbol:
            continue
        name = (row.get("Security Name") or "").strip()
        records.append(
            _record(
                symbol=symbol,
                name=name,
                exchange="XNAS",
                etf=(row.get("ETF") or "").strip().upper() == "Y",
                test_issue=(row.get("Test Issue") or "").strip().upper() == "Y",
                financial_status=(row.get("Financial Status") or "UNKNOWN").strip().upper(),
                effective_date=effective_date,
                available_at=retrieved_at,
            )
        )
    exchange_map = {"N": "XNYS", "A": "XASE"}
    for row in csv.DictReader(StringIO(other_text), delimiter="|"):
        symbol = (row.get("ACT Symbol") or "").strip().upper()
        if symbol.startswith("FILE CREATION TIME"):
            source_times.append(symbol)
            continue
        exchange = exchange_map.get((row.get("Exchange") or "").strip().upper())
        if not symbol or exchange is None:
            continue
        name = (row.get("Security Name") or "").strip()
        records.append(
            _record(
                symbol=symbol,
                name=name,
                exchange=exchange,
                etf=(row.get("ETF") or "").strip().upper() == "Y",
                test_issue=(row.get("Test Issue") or "").strip().upper() == "Y",
                financial_status="N",
                effective_date=effective_date,
                available_at=retrieved_at,
            )
        )
    unique = {
        (item.exchange, item.symbol): item
        for item in sorted(records, key=lambda value: (value.exchange, value.symbol))
    }
    normalized = tuple(unique[key] for key in sorted(unique))
    row_payload = [_record_document(item) for item in normalized]
    content_hash = _hash(row_payload)
    manifest = {
        "dataset_id": "broad-us-current-listings",
        "provider": NasdaqTraderSymbolDirectoryAdapter.provider_id,
        "retrieved_at": retrieved_at.isoformat(),
        "source_timestamp": ";".join(sorted(source_times)) or "UNAVAILABLE",
        "row_count": len(normalized),
        "content_hash": content_hash,
        "historical_use_allowed": False,
        "survivorship_status": SurvivorshipStatus.UNVERIFIED,
    }
    return CurrentDirectorySnapshot(
        dataset_id="broad-us-current-listings",
        provider=NasdaqTraderSymbolDirectoryAdapter.provider_id,
        retrieved_at=retrieved_at,
        source_timestamp=str(manifest["source_timestamp"]),
        records=normalized,
        content_hash=content_hash,
        manifest_hash=_hash(manifest),
    )


def current_snapshot_from_local_records(
    records: tuple[CurrentSecurityMasterRecord, ...],
    *,
    retrieved_at: datetime,
) -> CurrentDirectorySnapshot:
    """Create a degraded current-only snapshot when the metadata provider is unavailable."""

    if not records:
        raise ValueError("local current directory fallback cannot be empty")
    row_payload = [
        _record_document(item)
        for item in sorted(records, key=lambda row: row.security_id)
    ]
    content_hash = _hash(row_payload)
    manifest = {
        "dataset_id": "local-current-security-master-fallback",
        "provider": "LOCAL_CERTIFIED_DAILY_SNAPSHOT",
        "retrieved_at": retrieved_at,
        "row_count": len(records),
        "content_hash": content_hash,
        "historical_use_allowed": False,
    }
    return CurrentDirectorySnapshot(
        dataset_id="local-current-security-master-fallback",
        provider="LOCAL_CERTIFIED_DAILY_SNAPSHOT",
        retrieved_at=retrieved_at,
        source_timestamp="METADATA_PROVIDER_UNAVAILABLE",
        records=tuple(sorted(records, key=lambda row: row.security_id)),
        content_hash=content_hash,
        manifest_hash=_hash(manifest),
        survivorship_status=SurvivorshipStatus.UNVERIFIED,
    )


def evaluate_broad_universe(
    snapshot: CurrentDirectorySnapshot,
    observations: tuple[SecurityEligibilityObservation, ...],
    *,
    universe_date: date,
    decision_time: datetime,
    rules: EligibilityRules | None = None,
) -> BroadUniverseEligibility:
    """Apply PIT-safe security, data and liquidity gates to a current directory."""

    if decision_time.tzinfo is None:
        raise ValueError("universe decision_time must be timezone-aware")
    configured = rules or EligibilityRules()
    observed = {item.security_id: item for item in observations}
    security_type_eligible: list[CurrentSecurityMasterRecord] = []
    data_eligible: list[CurrentSecurityMasterRecord] = []
    liquidity_eligible: list[CurrentSecurityMasterRecord] = []
    factor_eligible: list[CurrentSecurityMasterRecord] = []
    exclusions: dict[str, tuple[str, ...]] = {}
    visible = tuple(
        item
        for item in snapshot.records
        if item.available_at <= decision_time
        and item.effective_date <= universe_date
        and item.active_from <= universe_date
        and (item.active_to is None or item.active_to >= universe_date)
    )
    for security in visible:
        reasons: list[str] = []
        if security.test_issue:
            reasons.append("TEST_ISSUE")
        if security.exchange not in configured.allowed_exchanges:
            reasons.append("UNSUPPORTED_EXCHANGE")
        type_allowed = security.is_common_stock
        if security.is_adr:
            type_allowed = configured.include_adr
        if security.is_reit:
            type_allowed = configured.include_reit
        if not type_allowed:
            reasons.append(f"SECURITY_TYPE_{security.security_type}_NOT_ELIGIBLE")
        if security.financial_status not in {"", "N", "NORMAL"}:
            reasons.append(f"FINANCIAL_STATUS_{security.financial_status}")
        if reasons:
            exclusions[security.security_id] = tuple(reasons)
            continue
        security_type_eligible.append(security)
        observation = observed.get(security.security_id)
        data_reasons: list[str] = []
        if observation is None:
            data_reasons.append("PIT_PRICE_OBSERVATION_MISSING")
        else:
            if observation.available_at > decision_time:
                data_reasons.append("FUTURE_DATA_NOT_ALLOWED")
            if observation.as_of_date > universe_date:
                data_reasons.append("FUTURE_OBSERVATION_DATE_NOT_ALLOWED")
            if (
                observation.latest_price is None
                or observation.latest_price < configured.minimum_price
            ):
                data_reasons.append("PRICE_BELOW_THRESHOLD_OR_MISSING")
            if observation.observed_sessions < configured.minimum_trading_sessions:
                data_reasons.append("INSUFFICIENT_TRADING_HISTORY")
            if observation.valid_bar_coverage < configured.minimum_valid_bar_coverage:
                data_reasons.append("VALID_BAR_COVERAGE_INSUFFICIENT")
            if observation.missing_ratio > configured.maximum_missing_ratio:
                data_reasons.append("MISSING_DATA_RATIO_EXCESSIVE")
            if not observation.corporate_action_integrity and (
                configured.require_pit_total_return
            ):
                # Production-strict factor universe requires a certified PIT
                # total-return series.  The broad price-based ranking layer
                # skips this check and is labeled PRICE_BASED_RANKING below;
                # it never claims total-return or corporate-action certification.
                data_reasons.append("CORPORATE_ACTION_INTEGRITY_INCOMPLETE")
            if not observation.feature_available:
                data_reasons.append("FEATURES_UNAVAILABLE")
        if data_reasons:
            exclusions[security.security_id] = tuple(data_reasons)
            continue
        assert observation is not None
        data_eligible.append(security)
        liquidity_reasons: list[str] = []
        if (
            observation.average_dollar_volume is None
            or observation.average_dollar_volume < configured.minimum_average_dollar_volume
        ):
            liquidity_reasons.append("ADV_BELOW_THRESHOLD_OR_MISSING")
        if (
            observation.median_dollar_volume is None
            or observation.median_dollar_volume < configured.minimum_median_dollar_volume
        ):
            liquidity_reasons.append("MEDIAN_DOLLAR_VOLUME_BELOW_THRESHOLD_OR_MISSING")
        if liquidity_reasons:
            exclusions[security.security_id] = tuple(liquidity_reasons)
            continue
        liquidity_eligible.append(security)
        factor_eligible.append(security)
    payload = {
        "universe_date": universe_date,
        # Content identity describes the visible PIT selection, not wall-clock
        # invocation time. A later decision changes this hash only when it makes
        # additional directory/data evidence visible and therefore changes the
        # visible hash, eligibility set, or exclusions below.
        "visible_directory_hash": _hash(
            [_record_document(item) for item in sorted(visible, key=lambda row: row.security_id)]
        ),
        "rules_fingerprint": configured.fingerprint,
        "factor_eligible_ids": [item.security_id for item in factor_eligible],
        "exclusions": exclusions,
    }
    return BroadUniverseEligibility(
        universe_date=universe_date,
        decision_time=decision_time,
        raw_listed_securities=len(visible),
        raw_listed_equities=sum(
            not item.is_etf and not item.test_issue for item in visible
        ),
        security_type_eligible=tuple(security_type_eligible),
        data_eligible=tuple(data_eligible),
        liquidity_eligible=tuple(liquidity_eligible),
        factor_eligible=tuple(factor_eligible),
        signal_eligible=tuple(factor_eligible),
        exclusions=exclusions,
        rules_fingerprint=configured.fingerprint,
        snapshot_hash=_hash(payload),
        pit_status=(
            "CURRENT_PIT_ONLY"
            if configured.require_pit_total_return
            else "PRICE_BASED_RANKING"
        ),
        survivorship_status=snapshot.survivorship_status,
    )


def write_directory_snapshot(snapshot: CurrentDirectorySnapshot, root: Path) -> Path:
    """Write a content-addressed snapshot and an atomic latest pointer."""

    root.mkdir(parents=True, exist_ok=True)
    document = {
        **snapshot.document(),
        "records": [_record_document(item) for item in snapshot.records],
    }
    rendered = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
    versioned = root / f"{snapshot.content_hash}.json"
    if versioned.exists() and versioned.read_text(encoding="utf-8") != rendered:
        raise ValueError("directory content hash collision")
    if not versioned.exists():
        versioned.write_text(rendered, encoding="utf-8")
    temporary = root / "latest.json.tmp"
    temporary.write_text(rendered, encoding="utf-8")
    temporary.replace(root / "latest.json")
    return versioned


def read_directory_snapshot(path: Path) -> CurrentDirectorySnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = tuple(_record_from_document(item) for item in payload["records"])
    row_hash = _hash([_record_document(item) for item in records])
    if row_hash != payload["content_hash"]:
        raise ValueError("current directory content hash mismatch")
    snapshot = CurrentDirectorySnapshot(
        dataset_id=str(payload["dataset_id"]),
        provider=str(payload["provider"]),
        retrieved_at=datetime.fromisoformat(str(payload["retrieved_at"])),
        source_timestamp=str(payload["source_timestamp"]),
        records=records,
        content_hash=str(payload["content_hash"]),
        manifest_hash=str(payload["manifest_hash"]),
        survivorship_status=SurvivorshipStatus(str(payload["survivorship_status"])),
        historical_use_allowed=bool(payload["historical_use_allowed"]),
        capabilities=SymbolDirectoryCapabilities(**payload["capabilities"]),
    )
    return snapshot


def dollar_volume_observation(
    security: CurrentSecurityMasterRecord,
    rows: tuple[tuple[date, datetime, float, float], ...],
    *,
    universe_date: date,
    decision_time: datetime,
    expected_sessions: int,
    corporate_action_integrity: bool,
    feature_available: bool,
) -> SecurityEligibilityObservation:
    """Build an eligibility observation using only rows available at decision time."""

    valid = tuple(
        item
        for item in rows
        if item[0] < universe_date
        and item[1] <= decision_time
        and item[2] > 0
        and item[3] >= 0
    )
    recent = valid[-20:]
    dollar_volumes = tuple(price * volume for _day, _available, price, volume in recent)
    observed = len(valid)
    coverage = observed / expected_sessions if expected_sessions > 0 else 0.0
    return SecurityEligibilityObservation(
        security_id=security.security_id,
        symbol=security.symbol,
        as_of_date=valid[-1][0] if valid else universe_date,
        available_at=max((item[1] for item in valid), default=security.available_at),
        latest_price=valid[-1][2] if valid else None,
        observed_sessions=observed,
        average_dollar_volume=(
            sum(dollar_volumes) / len(dollar_volumes) if dollar_volumes else None
        ),
        median_dollar_volume=(median(dollar_volumes) if dollar_volumes else None),
        valid_bar_coverage=min(1.0, coverage),
        missing_ratio=max(0.0, 1.0 - min(1.0, coverage)),
        corporate_action_integrity=corporate_action_integrity,
        feature_available=feature_available,
    )


def _record(
    *,
    symbol: str,
    name: str,
    exchange: str,
    etf: bool,
    test_issue: bool,
    financial_status: str,
    effective_date: date,
    available_at: datetime,
) -> CurrentSecurityMasterRecord:
    security_type = _classify_security(name, etf=etf)
    return CurrentSecurityMasterRecord(
        security_id=f"NASDAQTRADER:{exchange}:{symbol}",
        symbol=symbol,
        company_name=name,
        security_type=security_type,
        exchange=exchange,
        currency="USD",
        country="US",
        listing_date=None,
        delisting_date=None,
        active_from=effective_date,
        active_to=None,
        is_common_stock=security_type is CurrentSecurityType.COMMON_STOCK,
        is_etf=security_type is CurrentSecurityType.ETF,
        is_adr=security_type is CurrentSecurityType.ADR,
        is_reit=security_type is CurrentSecurityType.REIT,
        is_preferred=security_type is CurrentSecurityType.PREFERRED,
        is_warrant=security_type is CurrentSecurityType.WARRANT,
        is_unit=security_type is CurrentSecurityType.UNIT,
        is_right=security_type is CurrentSecurityType.RIGHT,
        is_otc=False,
        sector=None,
        industry=None,
        test_issue=test_issue,
        financial_status=financial_status or "UNKNOWN",
        source="NASDAQ_TRADER_SYMBOL_DIRECTORY_CURRENT",
        effective_date=effective_date,
        available_at=available_at,
    )


def _classify_security(name: str, *, etf: bool) -> CurrentSecurityType:
    if etf:
        return CurrentSecurityType.ETF
    normalized = re.sub(r"\s+", " ", name).upper()
    checks: tuple[tuple[tuple[str, ...], CurrentSecurityType], ...] = (
        (
            ("AMERICAN DEPOSITARY", "AMERICAN DEPOSITORY", " ADR", " ADS"),
            CurrentSecurityType.ADR,
        ),
        (
            ("PREFERRED STOCK", "PREFERRED SHARES", "PREFERENCE SHARES"),
            CurrentSecurityType.PREFERRED,
        ),
        (("WARRANT", "WARRANTS"), CurrentSecurityType.WARRANT),
        (("RIGHT", "RIGHTS"), CurrentSecurityType.RIGHT),
        ((" UNIT", "UNITS"), CurrentSecurityType.UNIT),
        (
            ("EXCHANGE TRADED NOTE", " ETN", "NOTES DUE", "SENIOR NOTES"),
            CurrentSecurityType.ETN,
        ),
        (
            ("CLOSED-END", "CLOSED END", "INCOME FUND", "OPPORTUNITY FUND"),
            CurrentSecurityType.CLOSED_END_FUND,
        ),
        ((" REIT", "REAL ESTATE INVESTMENT TRUST"), CurrentSecurityType.REIT),
    )
    for patterns, kind in checks:
        if any(pattern in normalized for pattern in patterns):
            return kind
    common_markers = (
        "COMMON STOCK",
        "COMMON SHARES",
        "ORDINARY SHARE",
        "ORDINARY SHARES",
        "SHARES OF BENEFICIAL INTEREST",
    )
    if any(marker in normalized for marker in common_markers):
        return CurrentSecurityType.COMMON_STOCK
    return CurrentSecurityType.UNKNOWN


def _directory_effective_date(nasdaq_text: str, other_text: str, *, fallback: date) -> date:
    observed: list[date] = []
    for text in (nasdaq_text, other_text):
        match = re.search(r"File Creation Time:\s*(\d{2})(\d{2})(\d{4})", text, re.I)
        if match is not None:
            observed.append(
                date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
            )
    return min(observed) if observed else fallback


def _record_document(record: CurrentSecurityMasterRecord) -> dict[str, object]:
    return {
        key: (value.isoformat() if isinstance(value, (date, datetime)) else value)
        for key, value in asdict(record).items()
    }


def _record_from_document(payload: dict[str, object]) -> CurrentSecurityMasterRecord:
    values = dict(payload)
    values["security_type"] = CurrentSecurityType(str(values["security_type"]))
    for key in ("listing_date", "delisting_date", "active_to"):
        value = values[key]
        values[key] = date.fromisoformat(str(value)) if value else None
    for key in ("active_from", "effective_date"):
        values[key] = date.fromisoformat(str(values[key]))
    values["available_at"] = datetime.fromisoformat(str(values["available_at"]))
    return CurrentSecurityMasterRecord(**values)  # type: ignore[arg-type]


def _download_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "PersonalAlphaTerminal/1.0"})
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed official HTTPS URLs
        payload = response.read()
    return bytes(payload).decode("utf-8-sig")


def _hash(payload: object) -> str:
    rendered = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":"))
    return sha256(rendered.encode()).hexdigest()
