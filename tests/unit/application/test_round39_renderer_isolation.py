from __future__ import annotations

from personal_alpha_terminal.application.round39_audit import (
    build_round39_renderer_parity,
)


def test_renderer_is_read_only_and_llm_is_advisory() -> None:
    parity = build_round39_renderer_parity()
    assert parity["renderer_recomputes_alpha"] is False
    assert parity["renderer_recomputes_weights"] is False
    assert parity["renderer_generates_buy_sell"] is False
