from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

streamlit = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from personal_alpha_terminal import __version__  # noqa: E402
from personal_alpha_terminal.core.config import Settings, get_settings  # noqa: E402
from personal_alpha_terminal.core.product import (  # noqa: E402
    UserPreferences,
    save_preferences,
)
from personal_alpha_terminal.data.database import (  # noqa: E402
    configure_database,
    init_database,
)
from personal_alpha_terminal.models import (  # noqa: E402
    Portfolio,
    PortfolioPosition,
    Price,
    QuantDecisionRecommendation,
    QuantDecisionRun,
    Stock,
)


def seed_dashboard(session: Session) -> None:
    index = Stock(
        canonical_code="US:INDEX:^GSPC",
        symbol="^GSPC",
        name="S&P 500",
        market="US",
        exchange="INDEX",
        asset_type="index",
        currency="USD",
        timezone="America/New_York",
    )
    stock = Stock(
        canonical_code="US:XNAS:AAPL",
        symbol="AAPL",
        name="Apple",
        market="US",
        exchange="XNAS",
        currency="USD",
        timezone="America/New_York",
    )
    session.add_all([index, stock])
    for day, index_close, stock_close in (
        (20, "6000", "200"),
        (21, "6020", "202"),
        (22, "6010", "201"),
        (23, "6040", "205"),
        (24, "6060", "208"),
    ):
        for instrument, close in ((index, index_close), (stock, stock_close)):
            value = Decimal(close)
            session.add(
                Price(
                    stock=instrument,
                    trade_date=date(2026, 7, day),
                    open=value,
                    high=value + 1,
                    low=value - 1,
                    close=value,
                    adjusted_close=value,
                    volume=1_000_000,
                    source="yahoo_finance",
                )
            )
    portfolio = Portfolio(
        name="Core",
        base_currency="USD",
        cash_balance=Decimal("1000"),
    )
    session.add(portfolio)
    session.flush()
    session.add(
        PortfolioPosition(
            portfolio=portfolio,
            stock=stock,
            as_of_date=date(2026, 7, 24),
            quantity=Decimal("10"),
            average_cost=Decimal("190"),
        )
    )
    decision_time = datetime(2026, 7, 24, 21, tzinfo=UTC)
    decision_run = QuantDecisionRun(
        portfolio_id=portfolio.id,
        as_of_time=decision_time,
        status="generated",
        gate_status="APPROVED",
        authorization_id="dashboard-test-auth",
        data_version="dashboard-test-data",
        model_version="deterministic-decision-v1",
        input_fingerprint="d" * 64,
        source_ids=["factor:test", "risk:test"],
        blockers=[],
    )
    decision_run.recommendations.append(
        QuantDecisionRecommendation(
            recommendation_id="QD-dashboard-test",
            stock_id=stock.id,
            action="BUY",
            current_weight=Decimal("0.05"),
            target_weight=Decimal("0.08"),
            quant_score=Decimal("72"),
            confidence_score=Decimal("80"),
            component_scores={"factor": 20.0, "risk": -5.0},
            rationale=["fixture-backed quant evidence"],
            risk_factors=["equity loss remains possible"],
            evidence_grade="OOS_CALIBRATED",
            sample_size=100,
            source_ids=["factor:test", "risk:test"],
            reference_price=Decimal("208"),
            suggested_shares=1,
            earliest_execution_time=decision_time + timedelta(hours=14),
            expires_at=decision_time + timedelta(days=30),
            review_status="pending",
        )
    )
    session.add(decision_run)
    session.commit()


def test_all_streamlit_pages_render_without_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("PAT_DATABASE_URL", "sqlite://")
    monkeypatch.setenv("PAT_LOG_DIR", "var/logs")
    monkeypatch.setattr(
        "personal_alpha_terminal.core.logging.configure_logging",
        lambda _settings: None,
    )
    get_settings.cache_clear()
    settings = Settings(_env_file=None)
    save_preferences(
        UserPreferences(
            onboarding_completed=True,
            accepted_notice_version=__version__,
        )
    )
    engine, session_factory = configure_database(settings)
    init_database(engine)
    with session_factory() as session:
        seed_dashboard(session)

    dashboard_root = Path(__file__).parents[2] / "src" / "personal_alpha_terminal" / "dashboard"
    page_paths = [
        dashboard_root / "app.py",
        dashboard_root / "pages" / "daily_dashboard.py",
        dashboard_root / "pages" / "action_center.py",
        dashboard_root / "pages" / "research_center.py",
        dashboard_root / "pages" / "backtest_center.py",
        dashboard_root / "pages" / "market_overview.py",
        dashboard_root / "pages" / "stock_detail.py",
        dashboard_root / "pages" / "portfolio.py",
        dashboard_root / "pages" / "risk.py",
        dashboard_root / "pages" / "relationships.py",
        dashboard_root / "pages" / "event_study.py",
        dashboard_root / "pages" / "conditional_probability.py",
        dashboard_root / "pages" / "market_graph.py",
        dashboard_root / "pages" / "lead_lag.py",
        dashboard_root / "pages" / "market_regime.py",
        dashboard_root / "pages" / "factor_research.py",
        dashboard_root / "pages" / "scenario_simulator.py",
        dashboard_root / "pages" / "us_adaptive_alpha.py",
        dashboard_root / "pages" / "settings.py",
        dashboard_root / "pages" / "diagnostics.py",
        dashboard_root / "pages" / "about.py",
        dashboard_root / "pages" / "data_sources.py",
    ]

    try:
        for page_path in page_paths:
            app = AppTest.from_file(page_path, default_timeout=30).run()
            assert not app.exception, page_path.name
            if page_path.name == "daily_dashboard.py":
                rendered_markdown = "\n".join(
                    [
                        *(item.value for item in app.title),
                        *(item.value for item in app.subheader),
                        *(item.value for item in app.markdown),
                        *(item.value for item in app.caption),
                    ]
                )
                rendered_info = "\n".join(item.value for item in app.info)
                assert "Quant Dashboard" in rendered_markdown
                assert "AAPL" in rendered_markdown
                assert "证据可信度" in rendered_markdown + rendered_info
                assert "AI 研究助手" in rendered_markdown
            if page_path.name == "market_overview.py":
                rendered_markdown = "\n".join(item.value for item in app.markdown)
                assert "Alpha Center" in rendered_markdown
                assert "Portfolio" in rendered_markdown
                assert "Research" in rendered_markdown
    finally:
        get_settings.cache_clear()
