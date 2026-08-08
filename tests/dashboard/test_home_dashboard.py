from datetime import date, timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from personal_alpha_terminal.dashboard.home import HomeDashboardRepository
from personal_alpha_terminal.models import ResearchReport


def test_market_overview_uses_neutral_evidence_labels() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "personal_alpha_terminal"
        / "dashboard"
        / "pages"
        / "market_overview.py"
    )
    content = source.read_text(encoding="utf-8")

    assert "#### 事件历史证据" in content
    assert "#### 条件概率证据" in content
    assert "#### 概率机会" not in content
    assert "不按最高历史胜率挑选" in content
    assert "未做统一多重比较校正" in content
    assert "regime_distribution_chart" in content
    assert "regime_probability_chart" not in content

    repository_source = source.parent.parent.joinpath("home.py").read_text(encoding="utf-8")
    assert "EventStudyStatistic.positive_probability.desc()" not in repository_source
    assert "ConditionalProbabilityResult.probability.desc()" not in repository_source


def test_home_digest_is_empty_without_completed_analysis(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        digest = HomeDashboardRepository(session).load()

    assert digest.events == ()
    assert digest.probabilities == ()
    assert digest.relationships == ()
    assert digest.portfolio is None
    assert digest.reports == ()
    assert digest.factor is None
    assert digest.backtest is None
    assert digest.refreshed_at is None


def test_home_digest_returns_only_four_latest_source_backed_reports(
    session_factory: sessionmaker[Session],
) -> None:
    start = date(2026, 7, 20)
    reports = [
        ResearchReport(
            report_type="daily_alpha",
            as_of_date=start + timedelta(days=index),
            subject_key=None,
            title=f"Research {index}",
            content_markdown="# Data-backed report",
            data_sources=["prices", "market_regime"] if index == 4 else ["prices"],
            methodology=["database snapshot"],
            risk_factors=["historical evidence is not a forecast"],
            generated_by="openai" if index == 4 else "deterministic",
        )
        for index in range(5)
    ]
    with session_factory() as session:
        session.add_all(reports)
        session.commit()

        digest = HomeDashboardRepository(session).load()

    assert [report.title for report in digest.reports] == [
        "Research 4",
        "Research 3",
        "Research 2",
        "Research 1",
    ]
    assert digest.reports[0].generated_by == "openai"
    assert digest.reports[0].source_count == 2
    assert digest.refreshed_at is not None
