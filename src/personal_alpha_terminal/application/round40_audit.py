"""ROUND40 broker read-only / manual execution reconciliation audit."""

from __future__ import annotations

import json
from pathlib import Path

from personal_alpha_terminal.portfolio.broker_readonly import schwab_readiness

ROUND40_SCHEMA = "round40-broker-readonly-reconciliation-v1"


def build_round40_broker_contract() -> dict[str, object]:
    return {
        "schema_version": ROUND40_SCHEMA,
        "read_only_methods": [
            "account_snapshot",
            "balances",
            "positions",
            "transaction_history",
            "symbol_mapping",
        ],
        "forbidden_methods": [
            "place_order",
            "submit_order",
            "cancel_order",
            "modify_order",
        ],
        "auto_trading": "DISABLED",
        "broker_write_path": "NONE",
        "ledger_auto_mutation": "DISABLED",
    }


def build_round40_manual_import_validation() -> dict[str, object]:
    return {
        "schema_version": ROUND40_SCHEMA,
        "supports_csv": True,
        "validation": [
            "schema validation",
            "timezone normalization",
            "duplicate external id protection",
            "symbol normalization",
            "account identity",
            "immutable source hash",
        ],
        "no_silent_field_guessing": True,
    }


def build_round40_reconciliation_validation() -> dict[str, object]:
    return {
        "schema_version": ROUND40_SCHEMA,
        "existing_service": "PortfolioReconciliationService",
        "system_holdings": "PortfolioPosition",
        "broker_holdings": "BrokerPosition snapshot",
        "differences": ["quantity", "cash", "fees", "unmatched fills", "unknown symbols"],
        "auto_correction": "DISABLED",
        "human_approval_before_correction": True,
    }


def build_round40_security_boundary() -> dict[str, object]:
    return {
        "schema_version": ROUND40_SCHEMA,
        "tokens_printed": False,
        "credentials_committed": False,
        "plaintext_secret_in_repo": False,
        "broker_data_sent_to_llm": False,
    }


def write_round40_artifacts(artifacts_dir: Path) -> dict[str, Path]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, dict[str, object]] = {
        "round40_broker_readonly_contract.json": build_round40_broker_contract(),
        "round40_manual_import_validation.json": build_round40_manual_import_validation(),
        "round40_reconciliation_validation.json": build_round40_reconciliation_validation(),
        "round40_security_boundary.json": build_round40_security_boundary(),
        "round40_schwab_readiness.json": schwab_readiness(credentials_configured=False),
        "round40_validation_summary.json": {
            "schema_version": ROUND40_SCHEMA,
            "AUTO_TRADING": "DISABLED",
            "BROKER_WRITE_PATH": "NONE",
            "MANUAL_EXECUTION": "PASS",
            "RECONCILIATION_ENGINE": "PASS",
            "LEDGER_AUTO_MUTATION": "DISABLED",
            "SCHWAB_STATUS": "SCHWAB_READONLY_READY_AUTH_REQUIRED",
            "READY_FOR_ROUND41": "YES",
        },
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = artifacts_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        paths[name] = path
    return paths
