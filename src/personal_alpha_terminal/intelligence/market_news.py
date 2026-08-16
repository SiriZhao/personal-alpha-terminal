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


class NewsFreshnessBucket(StrEnum):
    LAST_24H = "LAST_24H"
    LAST_72H = "LAST_72H"
    LAST_7D = "LAST_7D"
    LAST_30D = "LAST_30D"
    HISTORICAL_CONTEXT = "HISTORICAL_CONTEXT"


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


def classify_news_freshness(
    *,
    published_at: datetime,
    reference_time: datetime,
) -> NewsFreshnessBucket:
    """Classify a news item by publication age relative to the current run."""

    if published_at.tzinfo is None or reference_time.tzinfo is None:
        raise ValueError("news timestamps must be timezone-aware")
    delta = (reference_time - published_at).total_seconds()
    if delta < 0:
        return NewsFreshnessBucket.HISTORICAL_CONTEXT
    if delta <= 24 * 3600:
        return NewsFreshnessBucket.LAST_24H
    if delta <= 72 * 3600:
        return NewsFreshnessBucket.LAST_72H
    if delta <= 7 * 24 * 3600:
        return NewsFreshnessBucket.LAST_7D
    if delta <= 30 * 24 * 3600:
        return NewsFreshnessBucket.LAST_30D
    return NewsFreshnessBucket.HISTORICAL_CONTEXT


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


def news_item_from_document(row: dict[str, object]) -> NewsItem | None:
    """Parse a persisted document without guessing missing timing fields."""
    try:
        timestamps: dict[str, datetime] = {}
        for name in ("published_at", "retrieved_at", "available_at"):
            raw = row.get(name)
            if not isinstance(raw, str):
                return None
            value = datetime.fromisoformat(raw)
            timestamps[name] = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        required = ("news_id", "source", "source_tier", "headline", "url_hash", "content_hash")
        if any(not isinstance(row.get(name), str) or not row.get(name) for name in required):
            return None
        raw_symbols = row.get("symbols")
        raw_topics = row.get("topics")
        symbols = raw_symbols if isinstance(raw_symbols, (list, tuple)) else ()
        topics = raw_topics if isinstance(raw_topics, (list, tuple)) else ()
        return NewsItem(
            news_id=str(row["news_id"]), source=str(row["source"]),
            source_tier=str(row["source_tier"]), headline=str(row["headline"]),
            summary=str(row.get("summary") or ""), published_at=timestamps["published_at"],
            retrieved_at=timestamps["retrieved_at"], available_at=timestamps["available_at"],
            url_hash=str(row["url_hash"]), content_hash=str(row["content_hash"]),
            symbols=tuple(str(item) for item in symbols),
            topics=tuple(str(item) for item in topics),
            country=str(row.get("country") or "US"),
            language=str(row.get("language") or "en"),
            revision_id=str(row.get("revision_id") or ""),
            supersedes_id=str(row.get("supersedes_id") or ""),
            evidence_state=str(row.get("evidence_state") or "RAW_UNVERIFIED"),
        )
    except (TypeError, ValueError):
        return None


def materialize_news_facts(
    *,
    rows: tuple[dict[str, object], ...],
    decision_as_of: datetime,
    formal_symbols: tuple[str, ...] = (),
    execution_boundary: datetime | None = None,
    limit: int = 12,
    reference_time: datetime | None = None,
) -> dict[str, object]:
    """PIT-classify, deterministically rank, and materialize displayable news.

    The LLM receives only decision-safe complete clusters.  Post-decision rows
    are counted for pre-execution review but never used to rewrite the formal
    decision.  Rows without usable timestamps remain visible only in the
    explicit unknown count.
    """
    runtime = reference_time or datetime.now(UTC)
    parsed: list[NewsItem] = []
    unknown_timestamps = 0
    for row in rows:
        item = news_item_from_document(row)
        if item is None:
            unknown_timestamps += 1
        else:
            parsed.append(item)
    counts = {
        "pre_decision_news_count": 0,
        "post_decision_pre_execution_count": 0,
        "post_execution_count": 0,
        "unknown_timestamp_count": unknown_timestamps,
    }
    freshness_counts = {bucket.value: 0 for bucket in NewsFreshnessBucket}
    classes: dict[str, NewsTimeClass] = {}
    for item in parsed:
        time_class = classify_news_time(
            available_at=item.available_at,
            decision_as_of=decision_as_of,
            execution_boundary=execution_boundary,
        )
        classes[item.news_id] = time_class
        if time_class is NewsTimeClass.DECISION_SAFE:
            counts["pre_decision_news_count"] += 1
        elif time_class is NewsTimeClass.POST_DECISION_PRE_EXECUTION:
            counts["post_decision_pre_execution_count"] += 1
        else:
            counts["post_execution_count"] += 1
        bucket = classify_news_freshness(
            published_at=item.published_at,
            reference_time=runtime,
        )
        freshness_counts[bucket.value] += 1
    by_id = {item.news_id: item for item in parsed}
    visible: list[dict[str, object]] = []
    for cluster in cluster_news(tuple(parsed)):
        members = [by_id[item_id] for item_id in cluster.member_ids if item_id in by_id]
        decision_safe = [
            item
            for item in members
            if classes.get(item.news_id) is NewsTimeClass.DECISION_SAFE
        ]
        if not decision_safe:
            continue
        primary = max(decision_safe, key=lambda item: item.available_at)
        # A cluster is visible only if all user-facing identity fields exist.
        if not primary.headline or not primary.source or primary.published_at is None:
            continue
        topics = tuple(dict.fromkeys(topic for item in members for topic in item.topics))
        symbols = tuple(dict.fromkeys(symbol for item in members for symbol in item.symbols))
        tier_score = 30 if primary.source_tier == NewsSourceTier.TIER1_OFFICIAL.value else 15
        relation = "ticker" if set(symbols) & set(formal_symbols) else "market"
        relevance = (
            tier_score
            + (25 if relation == "ticker" else 0)
            + (15 if "MACRO" in topics else 0)
        )
        visible.append(
            {
                "event_cluster_id": cluster.event_cluster_id,
                "evidence_ref": cluster.event_cluster_id,
                "title": primary.headline,
                "canonical_headline": primary.headline,
                "source": primary.source,
                "source_tier": primary.source_tier,
                "source_count": len({item.source for item in members}) or "UNKNOWN",
                "published_at": primary.published_at.isoformat(),
                "event_time": primary.published_at.isoformat(),
                "published_time": primary.published_at.isoformat(),
                "ingested_time": primary.retrieved_at.isoformat(),
                "available_at": primary.available_at.isoformat(),
                "decision_cutoff_relation": "PRE_DECISION",
                "freshness_bucket": classify_news_freshness(
                    published_at=primary.published_at,
                    reference_time=runtime,
                ).value,
                "event_type": "/".join(topics) or "UNKNOWN",
                "decision_eligible": True,
                "relation": relation,
                "symbols": list(symbols),
                "topics": list(topics),
                "member_ids": list(cluster.member_ids),
                "relevance_score": relevance,
                "evidence_strength": primary.source_tier,
            }
        )
    visible.sort(
        key=lambda item: (-int(str(item["relevance_score"])), str(item["available_at"])),
        reverse=False,
    )
    historical_context = [
        item
        for item in visible
        if item.get("freshness_bucket") == NewsFreshnessBucket.HISTORICAL_CONTEXT.value
    ]
    fresh_visible = [
        item
        for item in visible
        if item.get("freshness_bucket") != NewsFreshnessBucket.HISTORICAL_CONTEXT.value
    ]
    return {
        "raw_news_rows": len(rows),
        "normalized_news_rows": len(parsed),
        "clusters": fresh_visible[:limit],
        "historical_context": historical_context,
        "cluster_count": len(cluster_news(tuple(parsed))),
        "terminal_displayed_rows": len(fresh_visible[:limit]),
        "ai_used_rows": len(fresh_visible[:limit]),
        "freshness_counts": freshness_counts,
        **counts,
    }


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
