from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BacktestAvailability:
    available: bool
    status: str
    reason: str


class BacktestService:
    """Console boundary for existing backtests; never bypasses PIT authorization."""

    def availability(self, *, gate_approved: bool) -> BacktestAvailability:
        if not gate_approved:
            return BacktestAvailability(
                False,
                "BLOCKED",
                "PIT 股票池、公司行动和总回报序列尚未完成严格认证。",
            )
        return BacktestAvailability(True, "READY", "可运行已注册的统一回测引擎。")

    def run_backtest(self, **_parameters: object) -> None:
        raise RuntimeError("Console backtest execution requires an APPROVED PIT authorization")
