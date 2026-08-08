from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from personal_alpha_terminal.agents.llm.providers import LLMProvider
from personal_alpha_terminal.agents.llm.schemas import EvidenceItem, ResearchReportResult
from personal_alpha_terminal.agents.research import ResearchAgent
from personal_alpha_terminal.quant_engine.ai_agent.analyst_agent import (
    AnalystAgentInputBuilder,
    QuantAnalysisSummary,
)

_ACTIONS = {"BUY", "SELL", "HOLD", "WATCH"}
_PROHIBITED_GENERATED_ACTIONS = ("you should buy", "you should sell", "建议买入", "建议卖出")


@dataclass(frozen=True, slots=True)
class QuantDecisionPacket:
    ticker: str
    deterministic_action: str
    as_of_date: date
    factor_score: float
    risk_score: float
    regime_score: float
    evidence_grade: str
    risk_factors: tuple[str, ...]
    source: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.deterministic_action not in _ACTIONS:
            raise ValueError("deterministic action must come from the quant decision engine")
        if not self.source_ids:
            raise ValueError("AI explanation requires traceable quantitative evidence")


@dataclass(frozen=True, slots=True)
class QuantDecisionExplanation:
    ticker: str
    deterministic_action: str
    report: ResearchReportResult
    ai_may_override_action: bool = False


class ExplanationAgent:
    def __init__(self, provider: LLMProvider, *, temperature: float = 0.2) -> None:
        self._research_agent = ResearchAgent(provider, temperature=temperature)
        self._builder = AnalystAgentInputBuilder()

    def explain(self, packet: QuantDecisionPacket) -> QuantDecisionExplanation:
        payload = self._builder.build(
            QuantAnalysisSummary(
                ticker=packet.ticker,
                deterministic_action=packet.deterministic_action,
                factor_score=packet.factor_score,
                risk_score=packet.risk_score,
                regime_score=packet.regime_score,
                evidence_grade=packet.evidence_grade,
                risk_factors=packet.risk_factors,
            )
        )
        payload["source_ids"] = list(packet.source_ids)
        report = self._research_agent.generate(
            report_type="quantitative decision explanation",
            as_of_date=packet.as_of_date,
            evidence=(
                EvidenceItem(packet.source_ids[0], packet.source, packet.as_of_date, payload),
            ),
        )
        _reject_generated_trade_instruction(report)
        return QuantDecisionExplanation(packet.ticker, packet.deterministic_action, report)


def _reject_generated_trade_instruction(report: ResearchReportResult) -> None:
    text = " ".join(
        [report.summary]
        + [str(item.get("text", "")) for item in report.conclusions]
    ).lower()
    if any(phrase in text for phrase in _PROHIBITED_GENERATED_ACTIONS):
        raise ValueError("AI output attempted to create an investment action")
