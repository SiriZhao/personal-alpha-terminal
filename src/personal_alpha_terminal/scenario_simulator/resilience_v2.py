"""ROUND24 resilience scenarios for Stress Exam 2.0 (D3 operational part).

Each scenario is a bounded fault-injection check against a component
boundary.  The exam asserts fail-closed behavior: a fault may degrade the
affected layer but must never fabricate actions or leak future data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

RESILIENCE_SCENARIOS: tuple[str, ...] = (
    "PROVIDER_OUTAGE",
    "PARTIAL_PROVIDER_RESPONSE",
    "MISSING_BARS",
    "STALE_BARS",
    "DUPLICATE_BARS",
    "FUTURE_ROW_INJECTION",
    "DB_READ_ONLY",
    "DB_LOCK",
    "REPORT_DIRECTORY_UNAVAILABLE",
    "DEEPSEEK_TIMEOUT",
    "DEEPSEEK_MALFORMED_RESPONSE",
    "PROBABILITY_UNAVAILABLE",
)


@dataclass(frozen=True, slots=True)
class ResilienceResult:
    scenario: str
    status: str  # PASS / FAIL
    component: str
    expected: str
    observed: str
    evidence: dict[str, Any]

    def document(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "status": self.status,
            "component": self.component,
            "expected": self.expected,
            "observed": self.observed,
            "evidence": self.evidence,
        }


class ResilienceHarness:
    """Runs fault-injection checks and records PASS/FAIL evidence."""

    def __init__(self) -> None:
        self._results: list[ResilienceResult] = []

    def check(
        self,
        scenario: str,
        *,
        component: str,
        expected: str,
        probe: Callable[[], dict[str, Any]],
        passes: Callable[[dict[str, Any]], bool],
    ) -> None:
        evidence: dict[str, Any] = {}
        observed = "UNKNOWN"
        status = "FAIL"
        try:
            evidence = probe()
            observed = str(evidence.get("observed", evidence))
            status = "PASS" if passes(evidence) else "FAIL"
        except Exception as exc:  # noqa: BLE001 - harness boundary
            observed = f"{type(exc).__name__}: {exc}"
            status = "FAIL"
        self._results.append(
            ResilienceResult(
                scenario=scenario,
                status=status,
                component=component,
                expected=expected,
                observed=observed,
                evidence=evidence,
            )
        )

    def results(self) -> tuple[ResilienceResult, ...]:
        return tuple(self._results)

    def all_pass(self) -> bool:
        return bool(self._results) and all(item.status == "PASS" for item in self._results)


def run_resilience_exam(
    *,
    provider_probe: Callable[[], dict[str, Any]] | None = None,
    partial_provider_probe: Callable[[], dict[str, Any]] | None = None,
    bars_probe: Callable[[str], dict[str, Any]] | None = None,
    future_rows_probe: Callable[[], dict[str, Any]] | None = None,
    db_probe: Callable[[str], dict[str, Any]] | None = None,
    report_probe: Callable[[], dict[str, Any]] | None = None,
    llm_timeout_probe: Callable[[], dict[str, Any]] | None = None,
    llm_malformed_probe: Callable[[], dict[str, Any]] | None = None,
    probability_probe: Callable[[], dict[str, Any]] | None = None,
) -> tuple[ResilienceResult, ...]:
    """Execute every resilience scenario with injected probes.

    Probes are component-boundary checks supplied by the caller (tests inject
    deterministic fakes; the CLI injects real service boundaries).  A probe
    returns evidence with an ``observed`` string; ``passes`` decides PASS.
    """

    harness = ResilienceHarness()

    def not_injected(name: str, component: str) -> None:
        harness._results.append(
            ResilienceResult(
                scenario=name,
                status="NOT_INJECTED",
                component=component,
                expected="covered by the unit test suite",
                observed="no live probe injected",
                evidence={},
            )
        )

    if provider_probe is not None:
        harness.check(
            "PROVIDER_OUTAGE",
            component="market_data_provider",
            expected="fail-closed partial status; no fabricated bars",
            probe=provider_probe,
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if partial_provider_probe is not None:
        harness.check(
            "PARTIAL_PROVIDER_RESPONSE",
            component="market_data_provider",
            expected="partial response recorded with coverage accounting",
            probe=partial_provider_probe,
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if bars_probe is not None:
        harness.check(
            "MISSING_BARS",
            component="bar_quality",
            expected="missing sessions detected and reported",
            probe=lambda: bars_probe("missing"),
            passes=lambda evidence: bool(evidence.get("pass")),
        )
        harness.check(
            "STALE_BARS",
            component="bar_quality",
            expected="stale latest bar rejected from certification",
            probe=lambda: bars_probe("stale"),
            passes=lambda evidence: bool(evidence.get("pass")),
        )
        harness.check(
            "DUPLICATE_BARS",
            component="bar_quality",
            expected="duplicate trade_date rows deduplicated deterministically",
            probe=lambda: bars_probe("duplicate"),
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if future_rows_probe is not None:
        harness.check(
            "FUTURE_ROW_INJECTION",
            component="pit_filter",
            expected="rows after the information cutoff are dropped",
            probe=future_rows_probe,
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if db_probe is not None:
        harness.check(
            "DB_READ_ONLY",
            component="persistence",
            expected="write failure persists diagnosis, never actions",
            probe=lambda: db_probe("read_only"),
            passes=lambda evidence: bool(evidence.get("pass")),
        )
        harness.check(
            "DB_LOCK",
            component="persistence",
            expected="locked database fails closed without partial actions",
            probe=lambda: db_probe("lock"),
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if report_probe is not None:
        harness.check(
            "REPORT_DIRECTORY_UNAVAILABLE",
            component="reporting",
            expected="report write failure degrades reporting only",
            probe=report_probe,
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if llm_timeout_probe is not None:
        harness.check(
            "DEEPSEEK_TIMEOUT",
            component="ai_brief",
            expected="LLM PASS_DEGRADED; Classical pipeline unchanged",
            probe=llm_timeout_probe,
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if llm_malformed_probe is not None:
        harness.check(
            "DEEPSEEK_MALFORMED_RESPONSE",
            component="ai_brief",
            expected="AI_BRIEF_QUARANTINED; no pipeline pollution",
            probe=llm_malformed_probe,
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if probability_probe is not None:
        harness.check(
            "PROBABILITY_UNAVAILABLE",
            component="probability",
            expected="PROBABILITY_FALLBACK_CLASSICAL; weight stays 0",
            probe=probability_probe,
            passes=lambda evidence: bool(evidence.get("pass")),
        )
    if provider_probe is None:
        not_injected("PROVIDER_OUTAGE", "market_data_provider")
    if partial_provider_probe is None:
        not_injected("PARTIAL_PROVIDER_RESPONSE", "market_data_provider")
    if bars_probe is None:
        for name in ("MISSING_BARS", "STALE_BARS", "DUPLICATE_BARS"):
            not_injected(name, "bar_quality")
    if future_rows_probe is None:
        not_injected("FUTURE_ROW_INJECTION", "pit_filter")
    if db_probe is None:
        for name in ("DB_READ_ONLY", "DB_LOCK"):
            not_injected(name, "persistence")
    if report_probe is None:
        not_injected("REPORT_DIRECTORY_UNAVAILABLE", "reporting")
    if llm_timeout_probe is None:
        not_injected("DEEPSEEK_TIMEOUT", "ai_brief")
    if llm_malformed_probe is None:
        not_injected("DEEPSEEK_MALFORMED_RESPONSE", "ai_brief")
    if probability_probe is None:
        not_injected("PROBABILITY_UNAVAILABLE", "probability")
    return harness.results()
