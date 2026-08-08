from datetime import date

from personal_alpha_terminal.agents.llm.providers import LLMProvider
from personal_alpha_terminal.agents.llm.schemas import EvidenceItem, ResearchReportResult
from personal_alpha_terminal.agents.research import ResearchAgent


class QuantReportAgent:
    """Grounded narrative report facade; deterministic model results remain authoritative."""

    def __init__(self, provider: LLMProvider, *, temperature: float = 0.2) -> None:
        self._agent = ResearchAgent(provider, temperature=temperature)

    def generate(
        self,
        *,
        report_date: date,
        evidence: tuple[EvidenceItem, ...],
    ) -> ResearchReportResult:
        return self._agent.generate(
            report_type="daily quantitative research summary",
            as_of_date=report_date,
            evidence=evidence,
        )
