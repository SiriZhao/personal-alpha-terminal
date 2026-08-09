"""Compatibility exports for the canonical effective runtime configuration."""

from personal_alpha_terminal.core.effective_config import (
    EffectiveRuntimeConfig,
    default_config_text,
    resolve_effective_runtime_config,
    user_config_text,
)

TerminalConfig = EffectiveRuntimeConfig
load_config = resolve_effective_runtime_config

__all__ = [
    "EffectiveRuntimeConfig",
    "TerminalConfig",
    "default_config_text",
    "load_config",
    "user_config_text",
]
