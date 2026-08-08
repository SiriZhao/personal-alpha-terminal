from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntelligenceBudgetConfig:
    max_requests_per_run: int = 100
    max_tokens_per_run: int = 100_000
    max_cost_per_run: float = 10.0
    max_retries: int = 2
    timeout_seconds: float = 60.0
    estimated_cost_per_1k_tokens: float = 0.01

    def __post_init__(self) -> None:
        if min(self.max_requests_per_run, self.max_tokens_per_run) < 1:
            raise ValueError("AI request and token budgets must be positive")
        if self.max_cost_per_run < 0 or self.max_retries < 0 or self.timeout_seconds <= 0:
            raise ValueError("AI budget limits are invalid")


@dataclass(slots=True)
class IntelligenceBudget:
    config: IntelligenceBudgetConfig
    requests: int = 0
    tokens: int = 0
    estimated_cost: float = 0.0

    def reserve(self, estimated_tokens: int) -> bool:
        if estimated_tokens < 0:
            raise ValueError("estimated tokens cannot be negative")
        projected_requests = self.requests + 1
        projected_tokens = self.tokens + estimated_tokens
        projected_cost = self.estimated_cost + (
            estimated_tokens / 1000 * self.config.estimated_cost_per_1k_tokens
        )
        if (
            projected_requests > self.config.max_requests_per_run
            or projected_tokens > self.config.max_tokens_per_run
            or projected_cost > self.config.max_cost_per_run
        ):
            return False
        self.requests = projected_requests
        self.tokens = projected_tokens
        self.estimated_cost = projected_cost
        return True


def estimate_tokens(text: str) -> int:
    # Conservative offline estimate used only for enforcing a ceiling; provider
    # usage metadata may be persisted separately when available.
    return max(1, (len(text.encode("utf-8")) + 2) // 3)
