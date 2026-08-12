"""Run a real provisional operational daily decision with manual-only output."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from personal_alpha_terminal.application.app_service import ApplicationService
from personal_alpha_terminal.application.daily_result import (
    DailyQuantResult,
    canonical_input_hash,
    canonical_result_hash,
)
from personal_alpha_terminal.application.operational_readiness import (
    OperationalPolicyStore,
    build_operational_identity,
)
from personal_alpha_terminal.core.effective_config import (
    resolve_effective_runtime_config,
)
from personal_alpha_terminal.data.database import get_session_factory
from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
    USAdaptiveAlphaCoreV1,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--decision-time", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/latest/provisional_daily_run.json"),
    )
    parser.add_argument("--refresh", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args()

    config = resolve_effective_runtime_config(args.config)
    if config.portfolio_id is None:
        raise ValueError("config.yaml must set portfolio_id for a provisional daily run")

    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    identity = build_operational_identity(config, strategy)
    decision_time = (
        datetime.fromisoformat(args.decision_time)
        if args.decision_time
        else datetime.now(UTC)
    )
    if decision_time.tzinfo is None:
        decision_time = decision_time.replace(tzinfo=UTC)

    policy = OperationalPolicyStore(config.operational_policy_path).load()
    if policy is None:
        raise ValueError(
            "no explicit operational policy exists; run `operational-policy set "
            "--decision ALLOW_PROVISIONAL --reason ...` before a provisional run"
        )
    allowed, reason = policy.allows(identity, "NOT_CERTIFIABLE", now=decision_time)
    if not allowed:
        raise ValueError(f"operational policy denies provisional run: {reason}")

    service = ApplicationService(
        get_session_factory(),
        effective_config=config,
    )
    result = service.run_daily_quant_report(
        portfolio_id=config.portfolio_id,
        decision_time=decision_time,
        refresh=args.refresh,
    )
    _write_result(result, args.output)
    print(f"run_id={result.run_id}")
    print(f"analysis_date={result.analysis_date.isoformat()}")
    print(f"trade_date={result.trade_date.isoformat()}")
    print(f"data_cutoff={result.data_cutoff.isoformat() if result.data_cutoff else 'UNAVAILABLE'}")
    print(f"decision_readiness={result.decision_readiness.value}")
    print(f"run_classification={result.run_classification}")
    print(f"operational_readiness={result.operational_readiness}")
    print(f"operational_approval_artifact_id={result.operational_approval_artifact_id}")
    print(f"operational_policy_id={result.operational_policy_id}")
    print(f"operationally_allowed={result.operationally_allowed}")
    print(f"research_certification_state={result.research_certification_state}")
    print(f"recommendations={len(result.final_decisions)}")
    print(f"actions={len(result.execution_plan.legs)}")
    print(f"canonical_input_hash={canonical_input_hash(result)}")
    print(f"canonical_result_hash={canonical_result_hash(result)}")
    print(f"output={args.output.resolve()}")
    if result.blockers:
        for blocker in result.blockers:
            print(f"blocker={blocker}")
    return 0 if result.actionable else 3


def _write_result(result: DailyQuantResult, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output)


if __name__ == "__main__":
    raise SystemExit(main())
