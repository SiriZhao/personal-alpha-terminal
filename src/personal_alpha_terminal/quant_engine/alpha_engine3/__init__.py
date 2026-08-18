"""ROUND62 cross-sectional expected-return challenger framework."""

from personal_alpha_terminal.quant_engine.alpha_engine3.cross_sectional import (
    DEFAULT_PRICE_FEATURES,
    FUNDAMENTAL_FEATURES,
    AlphaEngine3Config,
    AlphaEngine3Evaluation,
    AlphaEngine3Verdict,
    AlphaModelKind,
    CrossSectionalPrediction,
    FeatureAblation,
    FeaturePanel,
    ModelEvidence,
    WalkForwardFold,
    build_forward_labels,
    build_price_feature_panel,
    build_walk_forward_folds,
    evaluate_alpha_engine3,
    evaluate_feature_ablation,
)

__all__ = [
    "DEFAULT_PRICE_FEATURES",
    "FUNDAMENTAL_FEATURES",
    "AlphaEngine3Config",
    "AlphaEngine3Evaluation",
    "AlphaEngine3Verdict",
    "AlphaModelKind",
    "CrossSectionalPrediction",
    "FeatureAblation",
    "FeaturePanel",
    "ModelEvidence",
    "WalkForwardFold",
    "build_forward_labels",
    "build_price_feature_panel",
    "build_walk_forward_folds",
    "evaluate_alpha_engine3",
    "evaluate_feature_ablation",
]
