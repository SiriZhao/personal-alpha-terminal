# Provisional Operational Certification

Date: 2026-08-12

## 1. Decision

Research certification and operational daily readiness are now separate states.

```text
RESEARCH_CERTIFICATION = NOT_CERTIFIABLE
OPERATIONAL_READINESS = PROVISIONAL_ACTIONABLE
```

`PROVISIONAL_ACTIONABLE` means the terminal may generate current-day manual
recommendations from real market data, deterministic Quant factors, portfolio
construction and risk controls. It does not mean long-horizon after-cost Alpha
has been certified.

## 2. State Model

Operational readiness supports:

- `BLOCKED`: current data, PIT, factors, portfolio, or risk cannot safely
  support a recommendation.
- `PROVISIONAL_ACTIONABLE`: current-day Quant pipeline can run while research
  certification remains incomplete.
- `FULLY_CERTIFIED_ACTIONABLE`: full research certification and production
  approval are both complete.

## 3. Provisional Operational Approval

The immutable artifact is `ProvisionalOperationalApproval`.

Location:

```text
reports/validation-artifacts/provisional-operational/
```

It binds:

- strategy name
- strategy version
- factor config hash
- operational universe policy
- required factor lookbacks
- portfolio config hash
- risk config hash
- cost model hash
- created at
- approval reason
- research certification state
- `full_research_certified = false`

The artifact is immutable. A config change produces a non-matching identity, so
the old approval is automatically unused.

## 4. Research vs Operational

Research certification still requires:

- survivorship-safe historical universe
- permanent security identity
- delisting lifecycle and return
- historical membership
- PIT corporate actions
- 2037 sessions
- walk-forward
- validation
- embargo
- locked OOS
- after-cost benchmark
- Champion/Challenger

None of these requirements was lowered.

The current daily operational mode requires:

- current real provider data
- freshness and cutoff validation
- no duplicate or future rows
- current calendar validity
- `available_at <= decision_as_of`
- sufficient per-factor lookback
- no fabricated or NaN factor values
- deterministic strategy signal
- formal portfolio engine
- formal risk engine as the final hard gate

## 5. Safety Gates

Risk remains a hard blocker. Provisional mode never bypasses:

- position limits
- sector/cluster concentration
- gross exposure
- turnover
- volatility
- cash constraint
- drawdown/risk state
- stress thresholds

Optional components may be unavailable:

- probability overlay: `RESEARCH_ONLY` / `PROBABILITY_NOT_ACTIVE`
- DeepSeek: `SHADOW` / `OPTIONAL_UNAVAILABLE`

Optional unavailability does not block classical Quant.

## 6. Explicit Degradation

When current `market_cap` is unavailable, factor size neutralization is
explicitly recorded as:

```text
size_neutralization:degraded
```

This is not an invented value and not a production certification. Research
mode still treats missing size neutralization as `NOT_VALIDATED`.

## 7. Limitations

- No long-horizon Alpha certification.
- No locked OOS.
- No survivorship-safe historical universe.
- No CRSP/Norgate research package.
- Current universe is a current-day eligible subset, not historical membership.
- Recommendations are manual execution only.
- No broker API, no automatic trading.

## 8. Approval Lifecycle

Approval is invalid for operational use when any bound identity changes:

- strategy version
- factor configuration
- universe policy
- portfolio configuration
- risk configuration
- cost model configuration

The daily runner issues or reuses a matching immutable approval before running.
