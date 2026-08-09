# Model Governance

Model states are RESEARCH, VALIDATING, TESTED, PRODUCTION_APPROVED, or DISABLED.
A status label alone cannot approve a model. Production approval requires a matching immutable
approval record for data version and parameter fingerprint, locked chronological OOS evidence,
PIT certification, survivorship control, and costs.

Portfolio production authorization is separate from Alpha model status. A
`PortfolioValidationArtifact` must bind a Locked-OOS evidence ID, Alpha model and data
versions, strategy parameter hash, portfolio constraint hash, risk model hash, transaction
cost hash, effective runtime-config hash, benchmark definition, validation window,
embargo/walk-forward settings, and source commit. The producer writes an immutable artifact;
runtime injection occurs only after an exact fingerprint match. There is currently no real
Locked-OOS portfolio artifact, so this capability is `BLOCKED_BY_DATA`, not approved.

Factor/evidence coverage is descriptive completeness, not a calibrated probability.
Probability output can be labelled calibrated only when a separate immutable calibration
artifact supplies chronological train/calibration/OOS windows, method/version, Brier score,
log loss, ECE, reliability bins, sample count, and matching model/data/parameter identity.
No calibration artifact is inferred from model approval.

Experiments are append-only. Opening LOCKED_TEST requires an experiment lock. A different result
or parameter set must create a new experiment version. Purged/embargoed walk-forward splits,
parameter perturbations, and deflated Sharpe probability are available. Fixture tests never
constitute OOS Alpha validation.
