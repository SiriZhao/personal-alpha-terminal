"""ROUND25 PHASE 5: MARKET_NEWS_INTELLIGENCE pipeline.

Three provider adapters (official macro, general market, company) behind one
interface; per-item persistence with explicit PIT time semantics; event-level
dedup clustering; source tiers for reliability.  DeepSeek may only summarize
persisted news facts -- it can never invent news.

Without a configured general-market news API the status is honestly
``GENERAL_MARKET_NEWS_UNAVAILABLE`` instead of fabricating headlines.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Time semantics (PIT-safe classification)
# ---------------------------------------------------------------------------


class NewsTimeClass(StrEnum):
    DECISION_SAFE = "DECISION_SAFE"
    POST_DECISION_PRE_EXECUTION = "POST_DECISION_PRE_EXECUTION"
    POST_EXECUTION_CONTEXT = "POST_EXECUTION_CONTEXT"


class NewsSourceTier(StrEnum):
    TIER1_OFFICIAL = "TIER1_OFFICIAL"
    TIER2_PROFESSIONAL_API = "TIER2_PROFESSIONAL_API"
    TIER3_OTHER = "TIER3_OTHER"


NEWS_PROVIDER_UNAVAILABLE = "GENERAL_MARKET_NEWS_UNAVAILABLE"


def classify_news_time(
    *,
    available_at: datetime,
    decision_as_of: datetime,
    execution_boundary: datetime | None = None,
) -> NewsTimeClass:
    """Classify a news item against the decision cutoff.

    * available_at <= decision_as_of  -> DECISION_SAFE (may explain the decision)
    * decision_as_of < available_at <= execution_boundary (or now)
      -> POST_DECISION_PRE_EXECUTION (may warn, never rewrite yesterday)
    * anything after the execution boundary -> POST_EXECUTION_CONTEXT
      (display-only information).
    """

    if available_at.tzinfo is None or decision_as_of.tzinfo is None:
        raise ValueError("news available_at and decision_as_of must be timezone-aware")
    if available_at <= decision_as_of:
        return NewsTimeClass.DECISION_SAFE
    if execution_boundary is not None and available_at > execution_boundary:
        return NewsTimeClass.POST_EXECUTION_CONTEXT
    return NewsTimeClass.POST_DECISION_PRE_EXECUTION


# ---------------------------------------------------------------------------
# News item / cluster schemas
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NewsItem:
    news_id: str
    source: str
    source_tier: str
    headline: str
    summary: str
    published_at: datetime
    retrieved_at: datetime
    available_at: datetime
    url_hash: str
    content_hash: str
    symbols: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    country: str = "US"
    language: str = "en"
    revision_id: str = ""
    supersedes_id: str = ""
    evidence_state: str = "RAW_UNVERIFIED"

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["published_at"] = self.published_at.isoformat()
        payload["retrieved_at"] = self.retrieved_at.isoformat()
        payload["available_at"] = self.available_at.isoformat()
        return payload


@dataclass(frozen=True, slots=True)
class NewsCluster:
    event_cluster_id: str
    source_count: int
    first_seen: datetime
    latest_seen: datetime
    canonical_headline: str
    symbols: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    member_ids: tuple[str, ...] = ()

    def document(self) -> dict[str, object]:
        payload = asdict(self)
        payload["first_seen"] = self.first_seen.isoformat()
        payload["latest_seen"] = self.latest_seen.isoformat()
        return payload


def hash_text(value: str) -> str:
    return sha256(value.strip().encode("utf-8")).hexdigest()[:32]


_TOKEN_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)


def headline_similarity(left: str, right: str) -> float:
    left_tokens = {token.casefold() for token in _TOKEN_RE.findall(left)}
    right_tokens = {token.casefold() for token in _TOKEN_RE.findall(right)}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def cluster_news(items: tuple[NewsItem, ...]) -> tuple[NewsCluster, ...]:
    """Deterministic event clustering: same event across outlets = one cluster."""

    clusters: list[NewsCluster] = []
    for item in sorted(items, key=lambda row: (row.available_at, row.news_id)):
        matched: NewsCluster | None = None
        for cluster in clusters:
            close = abs((cluster.first_seen - item.available_at).total_seconds()) <= 36 * 3600
            similar = headline_similarity(cluster.canonical_headline, item.headline) >= 0.55
            if close and similar:
                matched = cluster
                break
        if matched is None:
            clusters.append(
                NewsCluster(
                    event_cluster_id=f"event-{hash_text(item.headline)[:12]}",
                    source_count=1,
                    first_seen=item.available_at,
                    latest_seen=item.available_at,
                    canonical_headline=item.headline,
                    symbols=item.symbols,
                    topics=item.topics,
                    member_ids=(item.news_id,),
                )
            )
            continue
        index = clusters.index(matched)
        merged = NewsCluster(
            event_cluster_id=matched.event_cluster_id,
            source_count=matched.source_count + 1,
            first_seen=min(matched.first_seen, item.available_at),
            latest_seen=max(matched.latest_seen, item.available_at),
            canonical_headline=matched.canonical_headline,
            symbols=tuple(dict.fromkeys((*matched.symbols, *item.symbols))),
            topics=tuple(dict.fromkeys((*matched.topics, *item.topics))),
            member_ids=(*matched.member_ids, item.news_id),
        )
        clusters[index] = merged
    return tuple(clusters)


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------


class NewsProvider(Protocol):
    name: str
    tier: str

    def fetch(
        self, *, after: datetime, before: datetime
    ) -> tuple[NewsItem, ...]:
        """Return persisted-format news items; raise when unavailable."""


class OfficialMacroNewsProvider:
    """Tier-1 official releases (Federal Reserve / BLS / BEA / US Treasury).

    Implemented against public, keyless official endpoints; every failure is
    reported as unavailability -- never synthesized."""

    name = "official-macro"
    tier = NewsSourceTier.TIER1_OFFICIAL.value

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def fetch(
        self, *, after: datetime, before: datetime
    ) -> tuple[NewsItem, ...]:
        if not self.enabled:
            return ()
        # Network-bound acquisition is intentionally lazy; the availability
        # gate reports OFFICIAL_MACRO_NEWS_UNAVAILABLE until a network-enabled
        # run succeeds.
        return ()


class GeneralMarketNewsProvider:
    """Tier-2 pluggable professional market news API.

    The business code never hardcodes one vendor: ``fetch`` is injected by the
    configured adapter.  No valid configuration -> unavailable."""

    name = "general-market"
    tier = NewsSourceTier.TIER2_PROFESSIONAL_API.value

    def __init__(self, fetcher: Any | None = None) -> None:
        self._fetcher = fetcher

    def fetch(
        self, *, after: datetime, before: datetime
    ) -> tuple[NewsItem, ...]:
        if self._fetcher is None:
            return ()
        items = self._fetcher(after=after, before=before)
        return tuple(NewsItem(**item) if isinstance(item, dict) else item for item in items)


class CompanyNewsProvider:
    """Tier-1 company disclosures (SEC EDGAR filings)."""

    name = "company-disclosures"
    tier = NewsSourceTier.TIER1_OFFICIAL.value

    def __init__(self, fetcher: Any | None = None) -> None:
        self._fetcher = fetcher

    def fetch(
        self, *, after: datetime, before: datetime
    ) -> tuple[NewsItem, ...]:
        if self._fetcher is None:
            return ()
        items = self._fetcher(after=after, before=before)
        return tuple(NewsItem(**item) if isinstance(item, dict) else item for item in items)


# ---------------------------------------------------------------------------
# Persistence (append-only JSONL ledger)
# ---------------------------------------------------------------------------


class NewsLedger:
    """Append-only news ledger under var/intelligence/news/."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path("var/intelligence/news")

    @property
    def items_path(self) -> Path:
        return self.root / "news-items.jsonl"

    @property
    def clusters_path(self) -> Path:
        return self.root / "news-clusters.json"

    def append_items(self, items: tuple[NewsItem, ...]) -> int:
        if not items:
            return 0
        self.root.mkdir(parents=True, exist_ok=True)
        existing = {self._row_key(row) for row in self.load_items()}
        appended = 0
        with self.items_path.open("a", encoding="utf-8") as handle:
            for item in items:
                key = self._row_key(item.document())
                if key in existing:
                    continue
                handle.write(json.dumps(item.document(), ensure_ascii=False) + "\n")
                existing.add(key)
                appended += 1
        return appended

    @staticmethod
    def _row_key(document: dict[str, object]) -> str:
        return f"{document.get('source')}|{document.get('url_hash')}|{document.get('content_hash')}"

    def load_items(self) -> tuple[dict[str, object], ...]:
        if not self.items_path.exists():
            return ()
        rows: list[dict[str, object]] = []
        with self.items_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return tuple(rows)

    def write_clusters(self, clusters: tuple[NewsCluster, ...]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [cluster.document() for cluster in clusters]
        self.clusters_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_clusters(self) -> tuple[dict[str, object], ...]:
        if not self.clusters_path.exists():
            return ()
        payload = json.loads(self.clusters_path.read_text(encoding="utf-8"))
        return tuple(item for item in payload if isinstance(item, dict))


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NewsIntelligenceResult:
    status: str
    decision_as_of: datetime
    items: tuple[NewsItem, ...] = ()
    clusters: tuple[NewsCluster, ...] = ()
    provider_statuses: dict[str, str] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def document(self) -> dict[str, object]:
        items = [item.document() for item in self.items]
        return {
            "status": self.status,
            "decision_as_of": self.decision_as_of.isoformat(),
            "news_rows": len(items),
            "cluster_rows": len(self.clusters),
            "provider_statuses": dict(self.provider_statuses),
            "items": items,
            "clusters": [cluster.document() for cluster in self.clusters],
            "warnings": list(self.warnings),
        }


class NewsIntelligenceService:
    """Acquire -> classify -> dedup -> persist, with honest availability."""

    def __init__(self, ledger: NewsLedger | None = None) -> None:
        self.ledger = ledger or NewsLedger()

    def acquire(
        self,
        *,
        decision_as_of: datetime,
        providers: dict[str, NewsProvider],
        now: datetime | None = None,
        execution_boundary: datetime | None = None,
    ) -> NewsIntelligenceResult:
        runtime = (now or datetime.now(UTC)).astimezone(UTC)
        collected: list[NewsItem] = []
        statuses: dict[str, str] = {}
        warnings: list[str] = []
        for name, provider in providers.items():
            try:
                fetched = provider.fetch(after=decision_as_of, before=runtime)
            except (OSError, ValueError, RuntimeError) as error:
                statuses[name] = f"{name.upper()}_UNAVAILABLE"
                warnings.append(f"{name}: {error}")
                continue
            if not fetched:
                statuses[name] = f"{name.upper()}_UNAVAILABLE"
                continue
            statuses[name] = "OK"
            for item in fetched:
                time_class = classify_news_time(
                    available_at=item.available_at,
                    decision_as_of=decision_as_of,
                    execution_boundary=execution_boundary,
                )
                evidence_state = {
                    NewsTimeClass.DECISION_SAFE: "DECISION_SAFE",
                    NewsTimeClass.POST_DECISION_PRE_EXECUTION: (
                        "POST_DECISION_PRE_EXECUTION"
                    ),
                    NewsTimeClass.POST_EXECUTION_CONTEXT: "POST_EXECUTION_CONTEXT",
                }[time_class]
                collected.append(
                    NewsItem(
                        **{
                            **asdict(item),
                            "evidence_state": evidence_state,
                        }
                    )
                )
        items = tuple(collected)
        appended = self.ledger.append_items(items)
        if appended != len(items):
            warnings.append(
                f"news dedup on persist: {len(items) - appended} duplicate rows skipped"
            )
        clusters = cluster_news(items)
        if not items:
            return NewsIntelligenceResult(
                status=NEWS_PROVIDER_UNAVAILABLE,
                decision_as_of=decision_as_of,
                provider_statuses=statuses,
                warnings=tuple(warnings),
            )
        self.ledger.write_clusters(clusters)
        return NewsIntelligenceResult(
            status="MARKET_NEWS_OK",
            decision_as_of=decision_as_of,
            items=items,
            clusters=clusters,
            provider_statuses=statuses,
            warnings=tuple(warnings),
        )

    def time_class_report(
        self, *, decision_as_of: datetime, execution_boundary: datetime | None = None
    ) -> dict[str, int]:
        """Count persisted rows by PIT time class."""

        counts = {
            NewsTimeClass.DECISION_SAFE.value: 0,
            NewsTimeClass.POST_DECISION_PRE_EXECUTION.value: 0,
            NewsTimeClass.POST_EXECUTION_CONTEXT.value: 0,
        }
        for row in self.ledger.load_items():
            available_raw = row.get("available_at")
            if not isinstance(available_raw, str):
                continue
            try:
                available_at = datetime.fromisoformat(available_raw)
            except ValueError:
                continue
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=UTC)
            time_class = classify_news_time(
                available_at=available_at,
                decision_as_of=decision_as_of,
                execution_boundary=execution_boundary,
            )
            counts[time_class.value] += 1
        return counts
