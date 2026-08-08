# Model Governance

Model states are RESEARCH, VALIDATING, TESTED, PRODUCTION_APPROVED, or DISABLED.
A status label alone cannot approve a model. Production approval requires a matching immutable
approval record for data version and parameter fingerprint, locked chronological OOS evidence,
PIT certification, survivorship control, and costs.

Experiments are append-only. Opening LOCKED_TEST requires an experiment lock. A different result
or parameter set must create a new experiment version. Purged/embargoed walk-forward splits,
parameter perturbations, and deflated Sharpe probability are available. Fixture tests never
constitute OOS Alpha validation.
