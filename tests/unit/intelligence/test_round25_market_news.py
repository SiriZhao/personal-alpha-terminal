"""ROUND25 PHASE 5: news PIT cutoff, dedup, unavailable-status tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from personal_alpha_terminal.intelligence.market_news import (
    NEWS_PROVIDER_UNAVAILABLE,
    NewsIntelligenceService,
    NewsItem,
    NewsLedger,
    NewsSourceTier,
    NewsTimeClass,
    classify_news_time,
    cluster_news,
    headline_similarity,
)

AS_OF = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def _item(
    news_id: str,
    headline: str,
    *,
    available_at: datetime,
    source: str = "test-source",
) -> NewsItem:
    return NewsItem(
        news_id=news_id,
        source=source,
        source_tier=NewsSourceTier.TIER2_PROFESSIONAL_API.value,
        headline=headline,
        summary=headline,
        published_at=available_at,
        retrieved_at=available_at,
        available_at=available_at,
        url_hash=f"u{news_id}",
        content_hash=f"c{news_id}",
    )


def test_pre_decision_news_is_decision_safe() -> None:
    assert (
        classify_news_time(available_at=AS_OF - timedelta(hours=2), decision_as_of=AS_OF)
        is NewsTimeClass.DECISION_SAFE
    )


def test_post_decision_news_is_pre_execution_class() -> None:
    assert (
        classify_news_time(available_at=AS_OF + timedelta(hours=2), decision_as_of=AS_OF)
        is NewsTimeClass.POST_DECISION_PRE_EXECUTION
    )


def test_after_execution_boundary_is_post_execution_context() -> None:
    boundary = AS_OF + timedelta(hours=6)
    assert (
        classify_news_time(
            available_at=boundary + timedelta(minutes=1),
            decision_as_of=AS_OF,
            execution_boundary=boundary,
        )
        is NewsTimeClass.POST_EXECUTION_CONTEXT
    )


def test_naive_datetimes_rejected() -> None:
    try:
        classify_news_time(
            available_at=datetime(2026, 8, 14, 8, 0),
            decision_as_of=AS_OF,
        )
    except ValueError:
        return
    raise AssertionError("expected ValueError for naive datetimes")


def test_same_event_across_outlets_is_one_cluster() -> None:
    base = AS_OF
    items = (
        _item("n1", "Federal Reserve keeps interest rates unchanged", available_at=base),
        _item(
            "n2",
            "Federal Reserve keeps interest rates steady",
            available_at=base + timedelta(hours=1),
            source="other-source",
        ),
        _item(
            "n3",
            "BLS reports lower unemployment",
            available_at=base + timedelta(hours=2),
        ),
    )
    clusters = cluster_news(items)
    assert len(clusters) == 2
    fed_cluster = next(
        cluster for cluster in clusters if "Federal Reserve" in cluster.canonical_headline
    )
    assert fed_cluster.source_count == 2
    assert set(fed_cluster.member_ids) == {"n1", "n2"}


def test_headline_similarity_is_token_based() -> None:
    assert headline_similarity("Fed holds rates", "Fed holds rates steady") > 0.5
    assert headline_similarity("Fed holds rates", "Apple launches new phone") < 0.5


def test_no_provider_config_yields_unavailable_not_fake_news(tmp_path) -> None:
    service = NewsIntelligenceService(NewsLedger(tmp_path / "news"))
    result = service.acquire(decision_as_of=AS_OF, providers={})
    assert result.status == NEWS_PROVIDER_UNAVAILABLE
    assert result.document()["news_rows"] == 0


class _FakeFetcher:
    def __init__(self, items: tuple[NewsItem, ...]) -> None:
        self.items = items

    def __call__(self, *, after, before):  # noqa: ANN001
        return self.items


def test_acquire_persists_and_classifies(tmp_path) -> None:
    from personal_alpha_terminal.intelligence.market_news import (
        GeneralMarketNewsProvider,
    )

    ledger = NewsLedger(tmp_path / "news")
    provider = GeneralMarketNewsProvider(
        _FakeFetcher(
            (
                _item("p1", "Pre-decision news", available_at=AS_OF - timedelta(hours=1)),
                _item("p2", "Overnight news", available_at=AS_OF + timedelta(hours=3)),
            )
        )
    )
    service = NewsIntelligenceService(ledger)
    result = service.acquire(
        decision_as_of=AS_OF,
        providers={"general-market": provider},
        execution_boundary=AS_OF + timedelta(hours=6),
    )
    assert result.status == "MARKET_NEWS_OK"
    by_id = {item.news_id: item for item in result.items}
    assert by_id["p1"].evidence_state == "DECISION_SAFE"
    assert by_id["p2"].evidence_state == "POST_DECISION_PRE_EXECUTION"
    rows = ledger.load_items()
    assert len(rows) == 2


def test_time_class_report_counts_are_honest(tmp_path) -> None:
    from personal_alpha_terminal.intelligence.market_news import (
        GeneralMarketNewsProvider,
    )

    ledger = NewsLedger(tmp_path / "news")
    provider = GeneralMarketNewsProvider(
        _FakeFetcher(
            (
                _item("a", "A", available_at=AS_OF - timedelta(days=1)),
                _item("b", "B", available_at=AS_OF + timedelta(hours=1)),
                _item("c", "C", available_at=AS_OF + timedelta(days=2)),
            )
        )
    )
    service = NewsIntelligenceService(ledger)
    service.acquire(
        decision_as_of=AS_OF,
        providers={"general-market": provider},
        execution_boundary=AS_OF + timedelta(days=1),
    )
    counts = service.time_class_report(
        decision_as_of=AS_OF, execution_boundary=AS_OF + timedelta(days=1)
    )
    assert counts["DECISION_SAFE"] == 1
    assert counts["POST_DECISION_PRE_EXECUTION"] == 1
    assert counts["POST_EXECUTION_CONTEXT"] == 1
