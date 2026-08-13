"""Canonical CIK-to-issuer and issuer-to-security PIT identity resolution.

The database table is the long-lived mapping store.  The import path reads
official SEC filing identity evidence into that store; it is not the runtime
query path for daily acquisition.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_alpha_terminal.intelligence.schemas import RawInformation
from personal_alpha_terminal.intelligence.sec_edgar_acquisition import CikSecurityMapping
from personal_alpha_terminal.models import IssuerSecurityIdentity, SecurityMaster

IDENTITY_SOURCE = "sec-edgar-filing-identity"
IDENTITY_SOURCE_VERSION = "sec-edgar-filing-identity-v1"
IDENTITY_PROVIDER = "sec-edgar"
ISSUER_RESOLVED_STATUS = "ISSUER_RESOLVED"
SECURITY_MAPPED_STATUS = "SECURITY_MAPPED"
SECURITY_MAPPING_MISSING_STATUS = "SECURITY_MAPPING_MISSING"


class IssuerResolutionStatus(StrEnum):
    ISSUER_RESOLVED = "ISSUER_RESOLVED"
    ISSUER_UNRESOLVED = "ISSUER_UNRESOLVED"
    FUTURE_MAPPING_EXCLUDED = "FUTURE_MAPPING_EXCLUDED"


class SecurityMappingStatus(StrEnum):
    SECURITY_MAPPED = "SECURITY_MAPPED"
    SECURITY_MAPPING_MISSING = "SECURITY_MAPPING_MISSING"
    SECURITY_MAPPING_AMBIGUOUS = "SECURITY_MAPPING_AMBIGUOUS"
    SECURITY_NOT_AVAILABLE = "SECURITY_NOT_AVAILABLE"
    DELISTED_SECURITY = "DELISTED_SECURITY"


@dataclass(frozen=True, slots=True)
class IssuerSecurityCandidate:
    cik: int
    issuer_id: str
    issuer_name: str
    ticker_as_of: str
    available_at: datetime
    effective_from: date
    evidence_identifier: str
    evidence_hash: str


@dataclass(frozen=True, slots=True)
class IssuerSecurityMapping:
    cik: int
    issuer_id: str
    issuer_name: str
    ticker_as_of: str | None
    stock_id: int | None
    permanent_security_id: str | None
    effective_from: date
    effective_to: date | None
    available_at: datetime
    mapping_source_type: str
    source: str
    source_version: str
    provider: str
    evidence_identifier: str | None
    evidence_hash: str | None

    def __post_init__(self) -> None:
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise ValueError("issuer security identity available_at must be timezone-aware")
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("issuer security identity period is invalid")
        if self.permanent_security_id is not None and not self.ticker_as_of:
            raise ValueError("issuer security mapping requires ticker_as_of")

    def security_mapping(self) -> CikSecurityMapping | None:
        if not self.permanent_security_id or not self.ticker_as_of:
            return None
        source_identity = f"{self.source}:{self.source_version}"
        if self.evidence_identifier:
            source_identity = f"{source_identity}:{self.evidence_identifier}"
        return CikSecurityMapping(
            cik=self.cik,
            permanent_security_id=self.permanent_security_id,
            ticker_as_of=self.ticker_as_of,
            mapping_source_type=self.mapping_source_type,
            source_identity=source_identity,
            source_version=self.source_version,
            available_at=self.available_at,
        )


@dataclass(frozen=True, slots=True)
class IssuerIdentityResolution:
    cik: int
    issuer_id: str | None
    issuer_name: str | None
    status: IssuerResolutionStatus
    security_status: SecurityMappingStatus | None
    mapping: IssuerSecurityMapping | None
    blockers: tuple[str, ...]

    @property
    def issuer_resolved(self) -> bool:
        return self.status is IssuerResolutionStatus.ISSUER_RESOLVED


class IssuerIdentityResolver:
    """Query the canonical identity store at an exact PIT cutoff."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def resolve(self, cik: int, as_of: datetime) -> IssuerIdentityResolution:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("issuer identity cutoff must be timezone-aware")
        rows = tuple(
            self.session.scalars(
                select(IssuerSecurityIdentity)
                .where(IssuerSecurityIdentity.cik == cik)
                .order_by(
                    IssuerSecurityIdentity.available_at.desc(),
                    IssuerSecurityIdentity.effective_from.desc(),
                    IssuerSecurityIdentity.id.desc(),
                )
            )
        )
        if not rows:
            return IssuerIdentityResolution(
                cik,
                None,
                None,
                IssuerResolutionStatus.ISSUER_UNRESOLVED,
                None,
                None,
                ("ISSUER_IDENTITY_MISSING",),
            )
        visible_rows: list[tuple[datetime, IssuerSecurityIdentity]] = []
        future: list[IssuerSecurityIdentity] = []
        for row in rows:
            available_at = _as_aware_utc(row.available_at)
            if available_at <= as_of and row.effective_from <= as_of.date() and (
                row.effective_to is None or row.effective_to >= as_of.date()
            ):
                visible_rows.append((available_at, row))
            elif available_at > as_of or row.effective_from > as_of.date():
                future.append(row)
        visible = tuple(row for _, row in visible_rows)
        if not visible:
            blockers = (
                ("FUTURE_MAPPING_EXCLUDED",) if future else ("MAPPING_NOT_VISIBLE_AT_CUTOFF",)
            )
            latest = rows[0]
            return IssuerIdentityResolution(
                cik,
                latest.issuer_id,
                latest.issuer_name,
                IssuerResolutionStatus.ISSUER_RESOLVED,
                SecurityMappingStatus.SECURITY_MAPPING_MISSING,
                None,
                blockers,
            )
        issuer_id = visible[0].issuer_id
        issuer_name = visible[0].issuer_name
        mapped = tuple(
            row for row in visible if row.permanent_security_id is not None and row.ticker_as_of
        )
        if not mapped:
            return IssuerIdentityResolution(
                cik,
                issuer_id,
                issuer_name,
                IssuerResolutionStatus.ISSUER_RESOLVED,
                SecurityMappingStatus.SECURITY_MAPPING_MISSING,
                None,
                ("SECURITY_MAPPING_MISSING",),
            )
        unique: dict[tuple[str | None, str | None], IssuerSecurityIdentity] = {}
        for row in mapped:
            unique.setdefault((row.permanent_security_id, row.ticker_as_of), row)
        if len(unique) > 1:
            return IssuerIdentityResolution(
                cik,
                issuer_id,
                issuer_name,
                IssuerResolutionStatus.ISSUER_RESOLVED,
                SecurityMappingStatus.SECURITY_MAPPING_AMBIGUOUS,
                None,
                ("MULTIPLE_SECURITY_CANDIDATES",),
            )
        row = next(iter(unique.values()))
        if row.stock_id is None:
            return IssuerIdentityResolution(
                cik,
                issuer_id,
                issuer_name,
                IssuerResolutionStatus.ISSUER_RESOLVED,
                SecurityMappingStatus.SECURITY_MAPPING_MISSING,
                None,
                ("SECURITY_MASTER_REFERENCE_MISSING",),
            )
        security = self.session.get(SecurityMaster, row.stock_id)
        if security is None:
            return IssuerIdentityResolution(
                cik,
                issuer_id,
                issuer_name,
                IssuerResolutionStatus.ISSUER_RESOLVED,
                SecurityMappingStatus.SECURITY_MAPPING_MISSING,
                None,
                ("SECURITY_MASTER_REFERENCE_MISSING",),
            )
        if security.delist_date is not None and as_of.date() > security.delist_date:
            return IssuerIdentityResolution(
                cik,
                issuer_id,
                issuer_name,
                IssuerResolutionStatus.ISSUER_RESOLVED,
                SecurityMappingStatus.DELISTED_SECURITY,
                None,
                ("DELISTED_SECURITY_AT_CUTOFF",),
            )
        if security.list_date is not None and as_of.date() < security.list_date:
            return IssuerIdentityResolution(
                cik,
                issuer_id,
                issuer_name,
                IssuerResolutionStatus.ISSUER_RESOLVED,
                SecurityMappingStatus.SECURITY_NOT_AVAILABLE,
                None,
                ("SECURITY_NOT_LISTED_AT_CUTOFF",),
            )
        mapping = IssuerSecurityMapping(
            cik=row.cik,
            issuer_id=row.issuer_id,
            issuer_name=row.issuer_name,
            ticker_as_of=row.ticker_as_of,
            stock_id=row.stock_id,
            permanent_security_id=row.permanent_security_id,
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            available_at=_as_aware_utc(row.available_at),
            mapping_source_type=row.mapping_source_type,
            source=row.source,
            source_version=row.source_version,
            provider=row.provider,
            evidence_identifier=row.evidence_identifier,
            evidence_hash=row.evidence_hash,
        )
        return IssuerIdentityResolution(
            cik,
            issuer_id,
            issuer_name,
            IssuerResolutionStatus.ISSUER_RESOLVED,
            SecurityMappingStatus.SECURITY_MAPPED,
            mapping,
            (),
        )

    def security_mapping_for(self, cik: int, as_of: datetime) -> CikSecurityMapping | None:
        resolution = self.resolve(cik, as_of)
        return resolution.mapping.security_mapping() if resolution.mapping is not None else None


def extract_issuer_identity_candidates(
    documents: tuple[RawInformation, ...],
) -> tuple[IssuerSecurityCandidate, ...]:
    """Extract generic PIT ticker identity evidence from SEC raw filings."""
    output: list[IssuerSecurityCandidate] = []
    for raw in documents:
        if raw.issuer_id is None:
            continue
        try:
            cik = int(str(raw.issuer_id))
        except ValueError:
            continue
        available_at = raw.available_at or raw.accepted_at or raw.observed_at
        if available_at is None:
            continue
        symbols = _extract_trading_symbols(raw.body)
        if not symbols:
            continue
        issuer_name = _extract_issuer_name(raw)
        for ticker in sorted(set(symbols)):
            evidence = f"{raw.source}|{raw.source_identifier}|{ticker}|{available_at.isoformat()}"
            output.append(
                IssuerSecurityCandidate(
                    cik=cik,
                    issuer_id=str(cik),
                    issuer_name=issuer_name,
                    ticker_as_of=ticker,
                    available_at=available_at,
                    effective_from=available_at.date(),
                    evidence_identifier=raw.source_identifier,
                    evidence_hash=sha256(evidence.encode("utf-8")).hexdigest(),
                )
            )
    return tuple(output)


def import_issuer_security_mappings(
    session: Session,
    candidates: tuple[IssuerSecurityCandidate, ...],
    *,
    ingested_at: datetime | None = None,
    source: str = IDENTITY_SOURCE,
    source_version: str = IDENTITY_SOURCE_VERSION,
    provider: str = IDENTITY_PROVIDER,
) -> int:
    ingested = ingested_at or datetime.now(UTC)
    changed = 0
    for candidate in sorted(
        candidates, key=lambda item: (item.cik, item.available_at, item.ticker_as_of)
    ):
        security = _find_security(session, candidate.ticker_as_of)
        existing = session.scalar(
            select(IssuerSecurityIdentity).where(
                IssuerSecurityIdentity.cik == candidate.cik,
                IssuerSecurityIdentity.evidence_identifier == candidate.evidence_identifier,
                IssuerSecurityIdentity.ticker_as_of == candidate.ticker_as_of,
                IssuerSecurityIdentity.effective_from == candidate.effective_from,
                IssuerSecurityIdentity.source == source,
                IssuerSecurityIdentity.source_version == source_version,
            )
        )
        if existing is not None:
            if existing.stock_id != (security.id if security else None):
                existing.stock_id = security.id if security else None
                changed += 1
            if existing.permanent_security_id != (security.canonical_code if security else None):
                existing.permanent_security_id = security.canonical_code if security else None
                changed += 1
            continue
        session.add(
            IssuerSecurityIdentity(
                cik=candidate.cik,
                issuer_id=candidate.issuer_id,
                issuer_name=candidate.issuer_name,
                stock_id=security.id if security else None,
                permanent_security_id=security.canonical_code if security else None,
                ticker_as_of=candidate.ticker_as_of,
                effective_from=candidate.effective_from,
                effective_to=None,
                available_at=candidate.available_at,
                mapping_source_type="SEC_FILING_PIT_IDENTITY",
                source=source,
                source_version=source_version,
                provider=provider,
                evidence_identifier=candidate.evidence_identifier,
                evidence_hash=candidate.evidence_hash,
                ingested_at=ingested,
            )
        )
        changed += 1
    session.flush()
    return changed


def remap_landing_zone(root: Path, resolver: IssuerIdentityResolver) -> int:
    """Refresh normalized landing-zone RawInformation with canonical mappings."""
    changed = 0
    if not (root / "landing").exists():
        return 0
    for jsonl in sorted((root / "landing").glob("*/documents.jsonl")):
        rows: list[RawInformation] = []
        for line in jsonl.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows.append(RawInformation.model_validate_json(line))
        updated: list[RawInformation] = []
        changed_here = 0
        for raw in rows:
            if raw.permanent_security_id is not None or raw.issuer_id is None:
                updated.append(raw)
                continue
            available_at = raw.available_at or raw.accepted_at or raw.observed_at
            if available_at is None:
                updated.append(raw)
                continue
            mapping = resolver.security_mapping_for(int(raw.issuer_id), available_at)
            if mapping is None:
                updated.append(raw)
                continue
            raw = raw.model_copy(
                update={
                    "issuer_resolution_status": ISSUER_RESOLVED_STATUS,
                    "security_mapping_status": SECURITY_MAPPED_STATUS,
                    "permanent_security_id": mapping.permanent_security_id,
                    "ticker_as_of": mapping.ticker_as_of,
                    "security_mapping_source": mapping.source_identity,
                    "security_mapping_source_version": mapping.source_version,
                }
            )
            updated.append(raw)
            changed_here += 1
        if changed_here:
            temporary = jsonl.with_suffix(".tmp")
            temporary.write_text(
                "\n".join(item.model_dump_json() for item in updated) + "\n",
                encoding="utf-8",
            )
            temporary.replace(jsonl)
            changed += changed_here
    return changed


def _extract_trading_symbols(body: str) -> tuple[str, ...]:
    symbols: set[str] = set()
    for match in re.finditer(
        r"""<ix:nonNumeric[^>]*name=["']dei:TradingSymbol["'][^>]*>(.*?)</ix:nonNumeric>""",
        body,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        symbol = _clean_text(match.group(1)).upper()
        if _valid_ticker(symbol):
            symbols.add(symbol)
    if not symbols:
        text = _strip_html(body)
        for match in re.finditer(
            r"Issuer Name and Ticker or Trading Symbol\s+(.*?)\s*\[\s*([A-Z0-9.\-^]+)\s*\]",
            text,
            flags=re.DOTALL,
        ):
            symbol = _clean_text(match.group(2)).upper()
            if _valid_ticker(symbol):
                symbols.add(symbol)
    return tuple(sorted(symbols))


def _extract_issuer_name(raw: RawInformation) -> str:
    match = re.search(
        r"""name=["']dei:EntityRegistrantName["'][^>]*>(.*?)</ix:nonNumeric>""",
        raw.body,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match is not None:
        name = _clean_text(match.group(1))
        if name:
            return name
    text = _strip_html(raw.body)
    form4 = re.search(
        r"Issuer Name and Ticker or Trading Symbol\s+(.*?)\s*\[\s*[A-Z0-9.\-^]+\s*\]",
        text,
        flags=re.DOTALL,
    )
    if form4 is not None:
        name = _clean_text(form4.group(1))
        if name:
            return name
    for form in (
        "10-K/A", "10-Q/A", "8-K/A", "DEF 14A", "10-K", "10-Q",
        "8-K", "20-F", "40-F", "6-K", "4",
    ):
        marker = f" {form} "
        if marker in raw.title:
            return raw.title.split(marker, 1)[0].strip()
    return raw.title.split(" ", 1)[0].strip()


def _strip_html(body: str) -> str:
    without_scripts = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", body)
    text = re.sub(r"(?s)<[^>]+>", " ", without_scripts)
    return _clean_text(text)


def _clean_text(value: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", value)).strip()


def _valid_ticker(value: str) -> bool:
    return re.fullmatch(r"[A-Z][A-Z0-9.\-^]{0,9}", value) is not None


def _find_security(session: Session, ticker: str) -> SecurityMaster | None:
    rows = tuple(
        session.scalars(
            select(SecurityMaster).where(
                SecurityMaster.symbol == ticker,
                SecurityMaster.market == "US",
            )
        )
    )
    if len(rows) == 1:
        return rows[0]
    return None


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value
