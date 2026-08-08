from pathlib import Path


def test_us_adaptive_alpha_page_uses_non_promissory_explainable_language() -> None:
    root = Path(__file__).parents[2]
    page = root / "src" / "personal_alpha_terminal" / "dashboard" / "pages" / "us_adaptive_alpha.py"
    content = page.read_text(encoding="utf-8")

    assert "Probability Lift" in content
    assert "暂不进入组合" in content
    assert "不是本金保证" in content
    assert "不保证跑赢" in content
    assert "必涨" not in content
    assert "稳赚" not in content
    assert "自动下单" in content

    app = root / "src" / "personal_alpha_terminal" / "dashboard" / "app.py"
    assert "pages/us_adaptive_alpha.py" in app.read_text(encoding="utf-8")
