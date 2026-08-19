# ruff: noqa: E501
"""ROUND74 immutable external-data import contracts and fail-closed certification.

This module deliberately does *not* write an unverified external package into the
production database.  It validates an immutable, provider-neutral import package
first, records the exact coverage it claims, and only reports PASS when every
critical evidence class is represented by a complete versioned package.  Current
operational rows are therefore never relabelled as historical research evidence.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import cast

from personal_alpha_terminal.core.fingerprints import fingerprint
from personal_alpha_terminal.research.data_evidence import EvidenceStatus, default_inventory


class CertifiedEvidenceClass(StrEnum):
    PERMANENT_SECURITY_IDENTITY = "permanent_security_identity"
    SYMBOL_HISTORY = "historical_symbol_history"
    HISTORICAL_UNIVERSE_MEMBERSHIP = "historical_universe_membership"
    DELISTINGS_AND_RETURNS = "delistings_and_delisted_returns"
    RAW_PIT_OHLCV = "raw_pit_ohlcv"
    CORPORATE_ACTIONS = "corporate_actions"
    TOTAL_RETURN_VINTAGES = "total_return_vintages"
    PIT_BENCHMARK = "pit_benchmark_prices_returns"
    FUNDAMENTALS = "fundamentals_with_availability"
    FILINGS = "filings_with_availability"
    NEWS_EVENTS = "news_events_with_availability"
    EXECUTABLE_OPENS = "historical_executable_opens"


_ALL_EVIDENCE_CLASSES = tuple(CertifiedEvidenceClass)
_SURVIVORSHIP_CLASSES = frozenset(
    {
        CertifiedEvidenceClass.PERMANENT_SECURITY_IDENTITY,
        CertifiedEvidenceClass.SYMBOL_HISTORY,
        CertifiedEvidenceClass.HISTORICAL_UNIVERSE_MEMBERSHIP,
        CertifiedEvidenceClass.DELISTINGS_AND_RETURNS,
    }
)


@dataclass(frozen=True, slots=True)
class ImmutableDataRecord:
    """One historical observation with explicit visibility and revision lineage."""

    evidence_class: CertifiedEvidenceClass
    permanent_security_id: str | None
    symbol_at_time: str | None
    effective_at: datetime
    observed_at: datetime
    published_at: datetime | None
    available_at: datetime
    ingested_at: datetime
    vintage: str
    source: str
    provider: str
    source_identifier: str
    content_hash: str
    adjustment_semantics: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        for field_name in (
            "effective_at",
            "observed_at",
            "available_at",
            "ingested_at",
        ):
            _require_aware_datetime(getattr(self, field_name), field_name)
        if self.published_at is not None:
            _require_aware_datetime(self.published_at, "published_at")
        if self.observed_at > self.available_at:
            raise ValueError("observed_at cannot be after available_at")
        if self.published_at is not None and self.published_at > self.available_at:
            raise ValueError("published_at cannot be after available_at")
        if self.available_at > self.ingested_at:
            raise ValueError("available_at cannot be after ingested_at")
        for field_name in (
            "vintage",
            "source",
            "provider",
            "source_identifier",
            "content_hash",
            "adjustment_semantics",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if self.evidence_class is not CertifiedEvidenceClass.NEWS_EVENTS:
            if not self.permanent_security_id or not self.permanent_security_id.strip():
                raise ValueError("permanent_security_id is required for this evidence class")
        if self.evidence_class in {
            CertifiedEvidenceClass.PERMANENT_SECURITY_IDENTITY,
            CertifiedEvidenceClass.SYMBOL_HISTORY,
            CertifiedEvidenceClass.RAW_PIT_OHLCV,
            CertifiedEvidenceClass.EXECUTABLE_OPENS,
        } and (not self.symbol_at_time or not self.symbol_at_time.strip()):
            raise ValueError("symbol_at_time is required for this evidence class")

    @property
    def record_hash(self) -> str:
        return fingerprint(asdict(self))

    @property
    def immutable_key(self) -> tuple[str, str, str, str]:
        return (
            self.evidence_class.value,
            self.source,
            self.source_identifier,
            self.vintage,
        )

    def visible_at(self, decision_time: datetime) -> bool:
        _require_aware_datetime(decision_time, "decision_time")
        return self.available_at <= decision_time

    def document(self) -> dict[str, object]:
        document = asdict(self)
        for field_name in (
            "effective_at",
            "observed_at",
            "published_at",
            "available_at",
            "ingested_at",
        ):
            value = document[field_name]
            document[field_name] = value.isoformat() if isinstance(value, datetime) else None
        document["evidence_class"] = self.evidence_class.value
        document["record_hash"] = self.record_hash
        return document


@dataclass(frozen=True, slots=True)
class EvidenceCoverageDeclaration:
    """Provider-attested scope for a single required data class."""

    evidence_class: CertifiedEvidenceClass
    source: str
    provider: str
    coverage_start: date
    coverage_end: date
    security_scope_hash: str
    source_contract_hash: str
    expected_record_count: int
    supplied_record_count: int
    declared_complete: bool

    def __post_init__(self) -> None:
        if self.coverage_start > self.coverage_end:
            raise ValueError("coverage date range is reversed")
        if self.expected_record_count <= 0:
            raise ValueError("expected_record_count must be positive")
        if self.supplied_record_count < 0:
            raise ValueError("supplied_record_count must be non-negative")
        for field_name in ("source", "provider", "security_scope_hash", "source_contract_hash"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")


@dataclass(frozen=True, slots=True)
class CertifiedDataPackage:
    """A candidate historical package; validation never fills omitted evidence."""

    schema_version: str
    dataset_id: str
    dataset_vintage: str
    created_at: datetime
    coverage: tuple[EvidenceCoverageDeclaration, ...]
    records: tuple[ImmutableDataRecord, ...]

    def __post_init__(self) -> None:
        _require_aware_datetime(self.created_at, "created_at")
        for field_name in ("schema_version", "dataset_id", "dataset_vintage"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        classes = [item.evidence_class for item in self.coverage]
        if len(classes) != len(set(classes)):
            raise ValueError("coverage declarations must be unique by evidence class")

    @property
    def package_hash(self) -> str:
        return fingerprint(
            {
                "schema_version": self.schema_version,
                "dataset_id": self.dataset_id,
                "dataset_vintage": self.dataset_vintage,
                "created_at": self.created_at,
                "coverage": self.coverage,
                "records": tuple(record.record_hash for record in self.records),
            }
        )

    def document(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "dataset_id": self.dataset_id,
            "dataset_vintage": self.dataset_vintage,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "coverage": [
                {
                    **asdict(item),
                    "evidence_class": item.evidence_class.value,
                    "coverage_start": item.coverage_start.isoformat(),
                    "coverage_end": item.coverage_end.isoformat(),
                }
                for item in self.coverage
            ],
            "records": [item.document() for item in self.records],
            "package_hash": self.package_hash,
        }


@dataclass(frozen=True, slots=True)
class EvidenceClassCertification:
    evidence_class: CertifiedEvidenceClass
    status: EvidenceStatus
    record_count: int
    blockers: tuple[str, ...]
    source_contract_hash: str | None
    coverage_scope_hash: str | None


@dataclass(frozen=True, slots=True)
class CertifiedDataResult:
    overall_status: EvidenceStatus
    package_hash: str | None
    classes: tuple[EvidenceClassCertification, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    promotion_allowed: bool

    def document(self) -> dict[str, object]:
        return {
            "overall_status": self.overall_status.value,
            "package_hash": self.package_hash,
            "classes": [
                {
                    **asdict(item),
                    "evidence_class": item.evidence_class.value,
                    "status": item.status.value,
                }
                for item in self.classes
            ],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "promotion_allowed": self.promotion_allowed,
        }


@dataclass(frozen=True, slots=True)
class ReturnSemanticsContract:
    """Explicit return semantics for an asset panel and its benchmark."""

    asset_price_semantics: str
    corporate_actions_applied_separately: bool
    benchmark_return_semantics: str
    benchmark_corporate_actions_applied_separately: bool


def validate_return_semantics(contract: ReturnSemanticsContract) -> tuple[str, ...]:
    """Reject double adjustment and unmatched strategy/benchmark return definitions."""

    blockers: list[str] = []
    asset = contract.asset_price_semantics.strip().upper()
    benchmark = contract.benchmark_return_semantics.strip().upper()
    if asset not in {"RAW", "SPLIT_ADJUSTED", "POINT_IN_TIME_TOTAL_RETURN"}:
        blockers.append("ASSET_ADJUSTMENT_SEMANTICS_INVALID")
    if benchmark not in {"RAW", "SPLIT_ADJUSTED", "POINT_IN_TIME_TOTAL_RETURN"}:
        blockers.append("BENCHMARK_ADJUSTMENT_SEMANTICS_INVALID")
    if asset == "POINT_IN_TIME_TOTAL_RETURN" and contract.corporate_actions_applied_separately:
        blockers.append("ASSET_DOUBLE_CORPORATE_ACTION_ADJUSTMENT")
    if benchmark == "POINT_IN_TIME_TOTAL_RETURN" and contract.benchmark_corporate_actions_applied_separately:
        blockers.append("BENCHMARK_DOUBLE_CORPORATE_ACTION_ADJUSTMENT")
    if asset == "RAW" and not contract.corporate_actions_applied_separately:
        blockers.append("RAW_ASSET_REQUIRES_EXPLICIT_CORPORATE_ACTION_RECONSTRUCTION")
    if benchmark == "RAW" and not contract.benchmark_corporate_actions_applied_separately:
        blockers.append("RAW_BENCHMARK_REQUIRES_EXPLICIT_CORPORATE_ACTION_RECONSTRUCTION")
    asset_total_return = asset == "POINT_IN_TIME_TOTAL_RETURN" or contract.corporate_actions_applied_separately
    benchmark_total_return = (
        benchmark == "POINT_IN_TIME_TOTAL_RETURN"
        or contract.benchmark_corporate_actions_applied_separately
    )
    if asset_total_return != benchmark_total_return:
        blockers.append("BENCHMARK_RETURN_SEMANTICS_MISMATCH")
    return tuple(blockers)


def parse_certified_data_package(document: Mapping[str, object]) -> CertifiedDataPackage:
    """Parse a JSON import document without mutating the production database."""

    coverage_document = _require_sequence(document, "coverage")
    records_document = _require_sequence(document, "records")
    coverage = tuple(_parse_coverage(_require_mapping(item, "coverage item")) for item in coverage_document)
    records = tuple(_parse_record(_require_mapping(item, "record")) for item in records_document)
    return CertifiedDataPackage(
        schema_version=_require_text(document, "schema_version"),
        dataset_id=_require_text(document, "dataset_id"),
        dataset_vintage=_require_text(document, "dataset_vintage"),
        created_at=_parse_datetime(_require_text(document, "created_at"), "created_at"),
        coverage=coverage,
        records=records,
    )


def load_certified_data_package(path_text: str) -> CertifiedDataPackage:
    """Load an operator-supplied package for validation; no implicit provider fetch occurs."""

    with open(path_text, encoding="utf-8") as handle:
        document = json.load(handle)
    return parse_certified_data_package(_require_mapping(document, "certified data package"))


def certify_data_package(package: CertifiedDataPackage) -> CertifiedDataResult:
    """Certify completeness, immutable vintage identity, and class-specific blockers."""

    records_by_class: dict[CertifiedEvidenceClass, list[ImmutableDataRecord]] = defaultdict(list)
    for record in package.records:
        records_by_class[record.evidence_class].append(record)
    declarations = {item.evidence_class: item for item in package.coverage}
    immutability_blockers = _validate_immutable_vintages(package.records)
    classes: list[EvidenceClassCertification] = []
    blockers: list[str] = list(immutability_blockers)
    for evidence_class in _ALL_EVIDENCE_CLASSES:
        declaration = declarations.get(evidence_class)
        records = records_by_class[evidence_class]
        class_blockers: list[str] = []
        if declaration is None:
            class_blockers.append("MISSING_COVERAGE_DECLARATION")
        else:
            if not declaration.declared_complete:
                class_blockers.append("SOURCE_DID_NOT_ATTEST_COMPLETE_COVERAGE")
            if declaration.supplied_record_count != len(records):
                class_blockers.append("SUPPLIED_RECORD_COUNT_MISMATCH")
            if declaration.expected_record_count != len(records):
                class_blockers.append("EXPECTED_RECORD_COUNT_NOT_MET")
        class_immutability = [
            blocker for blocker in immutability_blockers if blocker.startswith(evidence_class.value + ":")
        ]
        class_blockers.extend(class_immutability)
        status = _blocked_status_for(evidence_class) if class_blockers else EvidenceStatus.PASS
        classes.append(
            EvidenceClassCertification(
                evidence_class=evidence_class,
                status=status,
                record_count=len(records),
                blockers=tuple(class_blockers),
                source_contract_hash=(declaration.source_contract_hash if declaration else None),
                coverage_scope_hash=(declaration.security_scope_hash if declaration else None),
            )
        )
        blockers.extend(f"{evidence_class.value}:{item}" for item in class_blockers)
    unique_blockers = tuple(dict.fromkeys(blockers))
    return CertifiedDataResult(
        overall_status=EvidenceStatus.BLOCKED_DATA_QUALITY if unique_blockers else EvidenceStatus.PASS,
        package_hash=package.package_hash,
        classes=tuple(classes),
        blockers=unique_blockers,
        warnings=(),
        promotion_allowed=not unique_blockers,
    )


def current_data_certification() -> CertifiedDataResult:
    """Report current truth without reclassifying operational rows as certified history."""

    statuses = {field.field_id: field.status for field in default_inventory().fields}
    field_by_class = {
        CertifiedEvidenceClass.PERMANENT_SECURITY_IDENTITY: "symbol_history",
        CertifiedEvidenceClass.SYMBOL_HISTORY: "symbol_history",
        CertifiedEvidenceClass.HISTORICAL_UNIVERSE_MEMBERSHIP: "universe_membership",
        CertifiedEvidenceClass.DELISTINGS_AND_RETURNS: "delistings",
        CertifiedEvidenceClass.RAW_PIT_OHLCV: "prices_ohlcv",
        CertifiedEvidenceClass.CORPORATE_ACTIONS: "corporate_actions",
        CertifiedEvidenceClass.TOTAL_RETURN_VINTAGES: "corporate_actions",
        CertifiedEvidenceClass.PIT_BENCHMARK: "benchmark_prices",
        CertifiedEvidenceClass.FUNDAMENTALS: "fundamentals",
        CertifiedEvidenceClass.FILINGS: "filing_availability",
        CertifiedEvidenceClass.NEWS_EVENTS: "news_events",
        CertifiedEvidenceClass.EXECUTABLE_OPENS: "execution_price_availability",
    }
    classes: list[EvidenceClassCertification] = []
    blockers: list[str] = []
    warnings: list[str] = []
    for evidence_class in _ALL_EVIDENCE_CLASSES:
        source_status = statuses[field_by_class[evidence_class]]
        status = source_status if source_status is not EvidenceStatus.PASS else EvidenceStatus.PASS_WITH_WARNINGS
        message = "NO_BOUND_IMMUTABLE_IMPORT_PACKAGE"
        if status is EvidenceStatus.PASS_WITH_WARNINGS:
            warnings.append(f"{evidence_class.value}:{message}")
        else:
            blockers.append(f"{evidence_class.value}:{message}")
        classes.append(
            EvidenceClassCertification(
                evidence_class=evidence_class,
                status=status,
                record_count=0,
                blockers=(message,),
                source_contract_hash=None,
                coverage_scope_hash=None,
            )
        )
    return CertifiedDataResult(
        overall_status=EvidenceStatus.BLOCKED_DATA_QUALITY,
        package_hash=None,
        classes=tuple(classes),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        promotion_allowed=False,
    )


def build_procurement_manifest(*, generated_at: datetime | None = None) -> dict[str, object]:
    """Return the exact unfilled provider/import contract for all 12 evidence classes."""

    now = (generated_at or datetime.now(UTC)).astimezone(UTC)
    current = current_data_certification()
    by_class = {item.evidence_class: item for item in current.classes}
    requirements: list[dict[str, object]] = []
    for evidence_class in _ALL_EVIDENCE_CLASSES:
        item = by_class[evidence_class]
        requirements.append(
            {
                "evidence_class": evidence_class.value,
                "required_dataset": _dataset_name(evidence_class),
                "required_fields": _required_fields(evidence_class),
                "securities": _security_scope(evidence_class),
                "date_range": {
                    "start": None,
                    "end": None,
                    "requirement": "Must exactly cover the future sealed train, validation, and locked-OOS intervals; no current-list substitution.",
                    "current_coverage": "UNBOUND_NO_CERTIFIED_IMPORT",
                },
                "timestamp_requirements": _timestamp_requirement(evidence_class),
                "expected_source_contract": _source_contract(evidence_class),
                "current_status": item.status.value,
                "current_coverage": "No bound immutable external package; operational schemas and rows are not historical certification.",
                "missing_coverage": list(item.blockers),
            }
        )
    return {
        "schema_version": "ROUND74-PROCUREMENT-MANIFEST-v1",
        "generated_at": now.isoformat(),
        "certification_status": current.overall_status.value,
        "requirements": requirements,
        "import_schema": {
            "schema_version": "ROUND74-CERTIFIED-DATA-IMPORT-v1",
            "required_top_level_fields": [
                "schema_version",
                "dataset_id",
                "dataset_vintage",
                "created_at",
                "coverage",
                "records",
            ],
            "record_critical_fields": [
                "permanent_security_id where applicable",
                "symbol_at_time where applicable",
                "effective_at",
                "observed_at",
                "published_at where applicable",
                "available_at",
                "ingested_at",
                "vintage",
                "source",
                "provider",
                "source_identifier",
                "content_hash",
                "adjustment_semantics",
            ],
            "overwrite_policy": "Same evidence_class/source/source_identifier/vintage must be byte-identical; differing content is rejected as an immutable-vintage overwrite conflict.",
        },
    }


def render_certification_chinese(result: CertifiedDataResult) -> str:
    """Compact Chinese operator view; blockers remain explicit and non-actionable."""

    names = {
        CertifiedEvidenceClass.PERMANENT_SECURITY_IDENTITY: "永久证券身份",
        CertifiedEvidenceClass.SYMBOL_HISTORY: "历史代码变更",
        CertifiedEvidenceClass.HISTORICAL_UNIVERSE_MEMBERSHIP: "历史成分股",
        CertifiedEvidenceClass.DELISTINGS_AND_RETURNS: "退市与退市收益",
        CertifiedEvidenceClass.RAW_PIT_OHLCV: "原始 PIT OHLCV",
        CertifiedEvidenceClass.CORPORATE_ACTIONS: "公司行为",
        CertifiedEvidenceClass.TOTAL_RETURN_VINTAGES: "总收益版本",
        CertifiedEvidenceClass.PIT_BENCHMARK: "PIT 基准",
        CertifiedEvidenceClass.FUNDAMENTALS: "带可用时间的基本面",
        CertifiedEvidenceClass.FILINGS: "带可用时间的文件",
        CertifiedEvidenceClass.NEWS_EVENTS: "带可用时间的新闻事件",
        CertifiedEvidenceClass.EXECUTABLE_OPENS: "历史可执行开盘价",
    }
    lines = [
        "ROUND74 数据认证",
        f"总状态: {result.overall_status.value}",
        "历史研究/锁定 OOS/模型提升: 禁止" if not result.promotion_allowed else "历史研究/锁定 OOS/模型提升: 已满足数据门禁",
    ]
    lines.extend(f"{names[item.evidence_class]}: {item.status.value}" for item in result.classes)
    if result.blockers:
        lines.append("阻塞原因: " + "; ".join(result.blockers))
    return "\n".join(lines)


def _validate_immutable_vintages(records: Sequence[ImmutableDataRecord]) -> tuple[str, ...]:
    grouped: dict[tuple[str, str, str, str], list[ImmutableDataRecord]] = defaultdict(list)
    for record in records:
        grouped[record.immutable_key].append(record)
    blockers: list[str] = []
    for key, versions in grouped.items():
        hashes = {item.record_hash for item in versions}
        prefix = key[0] + ":"
        if len(versions) > 1 and len(hashes) > 1:
            blockers.append(prefix + "IMMUTABLE_VINTAGE_OVERWRITE_CONFLICT")
        elif len(versions) > 1:
            blockers.append(prefix + "DUPLICATE_IMMUTABLE_VINTAGE_RECORD")
    return tuple(blockers)


def _blocked_status_for(evidence_class: CertifiedEvidenceClass) -> EvidenceStatus:
    if evidence_class in _SURVIVORSHIP_CLASSES:
        return EvidenceStatus.BLOCKED_SURVIVORSHIP
    if evidence_class is CertifiedEvidenceClass.EXECUTABLE_OPENS:
        return EvidenceStatus.BLOCKED_TRADABILITY
    return EvidenceStatus.BLOCKED_PIT


def _parse_coverage(document: Mapping[str, object]) -> EvidenceCoverageDeclaration:
    return EvidenceCoverageDeclaration(
        evidence_class=CertifiedEvidenceClass(_require_text(document, "evidence_class")),
        source=_require_text(document, "source"),
        provider=_require_text(document, "provider"),
        coverage_start=date.fromisoformat(_require_text(document, "coverage_start")),
        coverage_end=date.fromisoformat(_require_text(document, "coverage_end")),
        security_scope_hash=_require_text(document, "security_scope_hash"),
        source_contract_hash=_require_text(document, "source_contract_hash"),
        expected_record_count=_require_int(document, "expected_record_count"),
        supplied_record_count=_require_int(document, "supplied_record_count"),
        declared_complete=_require_bool(document, "declared_complete"),
    )


def _parse_record(document: Mapping[str, object]) -> ImmutableDataRecord:
    published_value = document.get("published_at")
    permanent_value = document.get("permanent_security_id")
    symbol_value = document.get("symbol_at_time")
    payload_value = document.get("payload", {})
    return ImmutableDataRecord(
        evidence_class=CertifiedEvidenceClass(_require_text(document, "evidence_class")),
        permanent_security_id=str(permanent_value) if permanent_value is not None else None,
        symbol_at_time=str(symbol_value) if symbol_value is not None else None,
        effective_at=_parse_datetime(_require_text(document, "effective_at"), "effective_at"),
        observed_at=_parse_datetime(_require_text(document, "observed_at"), "observed_at"),
        published_at=(
            _parse_datetime(str(published_value), "published_at")
            if published_value is not None
            else None
        ),
        available_at=_parse_datetime(_require_text(document, "available_at"), "available_at"),
        ingested_at=_parse_datetime(_require_text(document, "ingested_at"), "ingested_at"),
        vintage=_require_text(document, "vintage"),
        source=_require_text(document, "source"),
        provider=_require_text(document, "provider"),
        source_identifier=_require_text(document, "source_identifier"),
        content_hash=_require_text(document, "content_hash"),
        adjustment_semantics=_require_text(document, "adjustment_semantics"),
        payload=dict(_require_mapping(payload_value, "payload")),
    )


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return cast(Mapping[str, object], value)


def _require_sequence(document: Mapping[str, object], field_name: str) -> Sequence[object]:
    value = document.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return value


def _require_text(document: Mapping[str, object], field_name: str) -> str:
    value = document.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _require_int(document: Mapping[str, object], field_name: str) -> int:
    value = document.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _require_bool(document: Mapping[str, object], field_name: str) -> bool:
    value = document.get(field_name)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _parse_datetime(value: str, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _require_aware_datetime(parsed, field_name)
    return parsed.astimezone(UTC)


def _require_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _dataset_name(evidence_class: CertifiedEvidenceClass) -> str:
    return {
        CertifiedEvidenceClass.PERMANENT_SECURITY_IDENTITY: "Permanent US security master with immutable issuer/security identifiers",
        CertifiedEvidenceClass.SYMBOL_HISTORY: "Historical ticker/exchange alias history keyed by permanent security ID",
        CertifiedEvidenceClass.HISTORICAL_UNIVERSE_MEMBERSHIP: "Versioned historical universe constituent membership",
        CertifiedEvidenceClass.DELISTINGS_AND_RETURNS: "Delisting lifecycle and terminal-return history",
        CertifiedEvidenceClass.RAW_PIT_OHLCV: "Raw unadjusted OHLCV with event/observed/available/ingested times",
        CertifiedEvidenceClass.CORPORATE_ACTIONS: "Versioned splits, dividends, mergers and symbol-action ledger",
        CertifiedEvidenceClass.TOTAL_RETURN_VINTAGES: "Point-in-time total-return reconstruction vintages",
        CertifiedEvidenceClass.PIT_BENCHMARK: "Benchmark price and total-return vintages aligned to strategy semantics",
        CertifiedEvidenceClass.FUNDAMENTALS: "Versioned fundamentals with publication and availability times",
        CertifiedEvidenceClass.FILINGS: "Filing corpus with acceptance/publication availability times",
        CertifiedEvidenceClass.NEWS_EVENTS: "News/event corpus with source provenance and decision-time availability",
        CertifiedEvidenceClass.EXECUTABLE_OPENS: "Historical next-session open, volume, halt and trading-status evidence",
    }[evidence_class]


def _required_fields(evidence_class: CertifiedEvidenceClass) -> list[str]:
    fields = [
        "effective_at",
        "observed_at",
        "available_at",
        "ingested_at",
        "vintage",
        "source",
        "provider",
        "source_identifier",
        "content_hash",
        "adjustment_semantics",
    ]
    if evidence_class is not CertifiedEvidenceClass.NEWS_EVENTS:
        fields.insert(0, "permanent_security_id")
    if evidence_class in {
        CertifiedEvidenceClass.PERMANENT_SECURITY_IDENTITY,
        CertifiedEvidenceClass.SYMBOL_HISTORY,
        CertifiedEvidenceClass.RAW_PIT_OHLCV,
        CertifiedEvidenceClass.EXECUTABLE_OPENS,
    }:
        fields.insert(1, "symbol_at_time")
    if evidence_class in {
        CertifiedEvidenceClass.FUNDAMENTALS,
        CertifiedEvidenceClass.FILINGS,
        CertifiedEvidenceClass.NEWS_EVENTS,
    }:
        fields.insert(3, "published_at")
    return fields


def _security_scope(evidence_class: CertifiedEvidenceClass) -> str:
    if evidence_class is CertifiedEvidenceClass.PIT_BENCHMARK:
        return "Every benchmark used by the sealed protocol, keyed as a permanent benchmark identity."
    if evidence_class is CertifiedEvidenceClass.NEWS_EVENTS:
        return "All issuer and market-wide events used by the sealed protocol, including explicit unmapped market events."
    return "Every security in historical train/validation/locked-OOS universe, including delisted and renamed securities."


def _timestamp_requirement(evidence_class: CertifiedEvidenceClass) -> str:
    if evidence_class in {
        CertifiedEvidenceClass.FUNDAMENTALS,
        CertifiedEvidenceClass.FILINGS,
        CertifiedEvidenceClass.NEWS_EVENTS,
    }:
        return "published_at and available_at must be timezone-aware; feature is invisible when available_at is after decision_time."
    if evidence_class is CertifiedEvidenceClass.EXECUTABLE_OPENS:
        return "Next legal session, executable open, quote observation, volume and trading-status availability must all precede the recorded execution time."
    return "effective_at, observed_at, available_at and ingested_at must be timezone-aware; revisions require an immutable vintage."


def _source_contract(evidence_class: CertifiedEvidenceClass) -> str:
    if evidence_class in _SURVIVORSHIP_CLASSES:
        return "Provider must supply historical, permanent-ID keyed lifecycle history; a current ticker directory is rejected as proof."
    if evidence_class in {
        CertifiedEvidenceClass.CORPORATE_ACTIONS,
        CertifiedEvidenceClass.TOTAL_RETURN_VINTAGES,
    }:
        return "Provider must supply revisioned corporate-action vintages and explicit raw/split/total-return semantics; no forward adjustment."
    if evidence_class is CertifiedEvidenceClass.PIT_BENCHMARK:
        return "Benchmark package must use the same PIT availability, calendar and return semantics as the strategy panel."
    if evidence_class is CertifiedEvidenceClass.EXECUTABLE_OPENS:
        return "Provider must include legal next session, open, volume and halt/trading-status lineage; missing data blocks execution certification."
    return "Provider must deliver immutable content hashes, source identifiers, and decision-time availability timestamps for the sealed scope."
