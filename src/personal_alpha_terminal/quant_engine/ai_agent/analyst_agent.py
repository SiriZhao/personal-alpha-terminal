from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuantAnalysisSummary:
    ticker: str
    deterministic_action: str
    factor_score: float
    risk_score: float
    regime_score: float
    evidence_grade: str
    risk_factors: tuple[str, ...]


class AnalystAgentInputBuilder:
    """Builds an explanation payload from model outputs; it performs no inference."""

    def build(self, summary: QuantAnalysisSummary) -> dict[str, object]:
        return {
            "ticker": summary.ticker,
            "deterministic_action": summary.deterministic_action,
            "factor_score": summary.factor_score,
            "risk_score": summary.risk_score,
            "regime_score": summary.regime_score,
            "evidence_grade": summary.evidence_grade,
            "risk_factors": list(summary.risk_factors),
            "instruction": "Explain only. Do not alter, rank, or create an action.",
        }
