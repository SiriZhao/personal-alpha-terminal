from dataclasses import asdict

from personal_alpha_terminal.quant_engine.backtest.performance import BacktestPerformance


def strategy_report_payload(
    *,
    strategy_name: str,
    performance: BacktestPerformance,
    data_version: str,
    limitations: tuple[str, ...],
) -> dict[str, object]:
    if not strategy_name.strip() or not data_version.strip():
        raise ValueError("strategy report requires strategy and immutable data version")
    return {
        "strategy": strategy_name,
        "performance": asdict(performance),
        "data_version": data_version,
        "limitations": list(limitations),
        "disclaimer": "Historical results do not guarantee future performance.",
    }
