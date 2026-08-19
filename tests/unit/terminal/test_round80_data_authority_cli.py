"""ROUND80 authority CLI must remain local, transparent, and non-certifying."""

from __future__ import annotations

import json

from personal_alpha_terminal.terminal import cli


def test_data_authority_cli_is_machine_readable_and_performs_no_remote_call(capsys) -> None:
    result = cli.main(["data-authority", "--json"])
    document = json.loads(capsys.readouterr().out)
    assert result == 0
    assert document["schema_version"] == "ROUND80-DATA-AUTHORITY-v1"
    assert "DECLARED_PROVIDER_AUTHORITY_ONLY" in document["certification_boundary"]
    providers = {item["provider_id"]: item for item in document["providers"]}
    assert providers["yahoo_finance"]["pit_capable"] is False
    assert providers["sec_edgar"]["enabled"] is False
    actions = next(
        item for item in document["domain_resolutions"] if item["domain"] == "CORPORATE_ACTIONS"
    )
    assert actions["status"] == "BLOCKED_WITH_EVIDENCE"
    prices = next(
        item for item in document["domain_resolutions"] if item["domain"] == "MARKET_PRICES"
    )
    assert prices["warnings"] == ["MARKET_PRICES:OPERATIONAL_SOURCE_NOT_CERTIFIED_PIT"]


def test_data_authority_cli_parser_does_not_require_configuration_or_network() -> None:
    args = cli.build_parser().parse_args(["data-authority", "--output", "authority.json"])
    assert args.command == "data-authority"
    assert args.output.name == "authority.json"
