"""ROUND 5 acceptance: provisional path with an ISOLATED test policy.

The user's real operational policy at var/operational/operational_policy.json is
never touched.  This script resolves config.yaml, points the policy store at a
temporary file, issues an ALLOW_PROVISIONAL policy bound to the NEW broad-universe
identity, and runs the real daily path so the recommendation count can be
measured.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from dataclasses import replace

    from personal_alpha_terminal.application.app_service import ApplicationService
    from personal_alpha_terminal.application.daily_result import (
        canonical_input_hash,
        canonical_result_hash,
    )
    from personal_alpha_terminal.application.operational_readiness import (
        DEFAULT_ALLOWED_RESEARCH_STATES,
        OperationalPolicyDecision,
        OperationalPolicyStore,
        build_operational_identity,
        issue_operational_policy,
    )
    from personal_alpha_terminal.core.effective_config import (
        resolve_effective_runtime_config,
    )
    from personal_alpha_terminal.data.database import get_session_factory
    from personal_alpha_terminal.quant_engine.strategies.us_adaptive_alpha_core import (
        USAdaptiveAlphaCoreV1,
    )

    work = Path(".codex-temp/round5-isolated-policy")
    work.mkdir(parents=True, exist_ok=True)
    policy_path = work / "operational_policy.json"
    config = resolve_effective_runtime_config(Path("config.yaml"))
    config = replace(config, operational_policy_path=policy_path)
    strategy = USAdaptiveAlphaCoreV1(config.strategy)
    identity = build_operational_identity(config, strategy)
    now = datetime.now(UTC)
    policy = issue_operational_policy(
        identity=identity,
        decision=OperationalPolicyDecision.ALLOW_PROVISIONAL,
        research_states_allowed=DEFAULT_ALLOWED_RESEARCH_STATES,
        issued_by="USER:cli:round5-isolated-acceptance",
        reason="ROUND 5 isolated provisional recommendation path acceptance; "
        "does not overwrite the user policy",
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=7),
    )
    # Isolated temporary file only; the user policy is never touched.
    OperationalPolicyStore(policy_path).save(policy, force=True)
    if config.portfolio_id is None:
        raise ValueError("config.yaml must set portfolio_id")

    service = ApplicationService(
        get_session_factory(),
        effective_config=config,
    )
    result = service.run_daily_quant_report(
        portfolio_id=config.portfolio_id,
        decision_time=now,
        refresh=False,
    )
    output = work / "provisional_result.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    evidence = result.provenance.get("universe_evidence", {})
    print(f"run_id={result.run_id}")
    print(f"run_classification={result.run_classification}")
    print(f"operationally_allowed={result.operationally_allowed}")
    print(f"operational_policy_id={result.operational_policy_id}")
    print(f"qualification={evidence.get('qualification')}")
    print(f"factor_eligible={evidence.get('funnel', {}).get('factor_eligible')}")
    print(f"candidate_count={evidence.get('candidate_count')}")
    print(f"recommendations={len(result.final_decisions)}")
    print(f"actions={len(result.execution_plan.legs)}")
    print(f"canonical_input_hash={canonical_input_hash(result)}")
    print(f"canonical_result_hash={canonical_result_hash(result)}")
    print(f"output={output.resolve()}")
    for blocker in result.blockers:
        print(f"blocker={blocker}")
    return 0 if result.actionable else 3


if __name__ == "__main__":
    raise SystemExit(main())
