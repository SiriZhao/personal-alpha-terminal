"""Small, fail-closed terminal fast-start helpers.

This module deliberately uses only the standard library.  The normal terminal
can therefore render an operator-safe local frame before importing the
application orchestrator, market providers, PIT builders, or factor engines.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter

from personal_alpha_terminal.core.runtime_bootstrap import (
    application_data_dir,
    process_is_running,
)

ACTIVE_REFRESH_STATES = frozenset({"SCHEDULED", "REFRESHING"})
TERMINAL_REFRESH_STATE_FILE = "terminal-refresh.json"


def _state_json_default(value: object) -> str:
    """Serialize timestamp-like status values without weakening state writes."""

    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"refresh state cannot serialize {type(value).__name__}")


def refresh_state_path(report_dir: Path) -> Path:
    """Return the writable per-user worker state path.

    Runtime state is not market evidence and therefore belongs under the
    application-owned run directory, not beside the production database or a
    potentially read-only checkout.
    """

    override = os.environ.get("PAT_TERMINAL_RUNTIME_DIR", "").strip()
    if override:
        return Path(override) / TERMINAL_REFRESH_STATE_FILE
    del report_dir
    return application_data_dir() / "run" / TERMINAL_REFRESH_STATE_FILE


def read_refresh_state(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def refresh_is_active(state: dict[str, object] | None) -> bool:
    if state is None or str(state.get("state")) not in ACTIVE_REFRESH_STATES:
        return False
    pid_value = state.get("pid", 0)
    if not isinstance(pid_value, (int, str)):
        return False
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return False
    return pid > 0 and process_is_running(pid)


def write_refresh_state(path: Path, payload: dict[str, object]) -> None:
    """Atomically publish worker progress without touching production data."""

    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        **payload,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_state_json_default,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_fast_start_snapshot(
    *,
    database_url: str,
    report_dir: Path,
    refresh_state: dict[str, object] | None,
) -> dict[str, object]:
    """Read bounded local state for the first terminal frame.

    A persisted recommendation is intentionally never considered actionable at
    this point.  Only the current refresh/decision chain may grant that state.
    """

    started = perf_counter()
    timings: dict[str, float] = {}
    snapshot: dict[str, object] = {
        "state": "BLOCKED",
        "database": "UNAVAILABLE",
        "portfolio": "UNAVAILABLE",
        "data_as_of": None,
        "data_snapshot": None,
        "last_decision_at": None,
        "last_run_id": None,
        "last_run_finished_at": None,
        "previous_recommendation_count": 0,
        "recommendation_actionable": False,
        "actionability_reason": "Current refresh and decision gates have not completed.",
        "refresh": refresh_state or {"state": "NOT_SCHEDULED"},
        "timings_seconds": timings,
    }

    database_started = perf_counter()
    if database_url.startswith("sqlite:///"):
        database = Path(database_url.removeprefix("sqlite:///"))
        try:
            connection = sqlite3.connect(str(database), timeout=1)
            try:
                connection.execute("SELECT 1").fetchone()
                snapshot["database"] = "READY"
                manifest = connection.execute(
                    "select snapshot_id, completed_at, end_date, certification_result "
                    "from data_snapshot_manifests order by completed_at desc limit 1"
                ).fetchone()
                if manifest is not None:
                    snapshot["data_snapshot"] = str(manifest[0])
                    snapshot["data_as_of"] = str(manifest[2]) if manifest[2] else None
                    snapshot["data_certification"] = str(manifest[3])
                portfolio = connection.execute("select count(*) from portfolios").fetchone()
                snapshot["portfolio"] = (
                    "READY" if portfolio is not None and int(portfolio[0]) > 0 else "MISSING"
                )
                decision = connection.execute(
                    "select as_of_time, status, gate_status from quant_decision_runs "
                    "order by as_of_time desc limit 1"
                ).fetchone()
                if decision is not None:
                    snapshot["last_decision_at"] = str(decision[0])
                    snapshot["last_decision_status"] = str(decision[1])
                    snapshot["last_decision_gate"] = str(decision[2])
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError) as error:
            snapshot["database"] = "ERROR"
            snapshot["database_error"] = f"{type(error).__name__}: {error}"
    timings["database_local_read"] = round(perf_counter() - database_started, 4)

    persisted_started = perf_counter()
    try:
        candidates = sorted(
            report_dir.glob("daily-runs/*/run_certificate.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            certificate = json.loads(candidates[0].read_text(encoding="utf-8"))
            if isinstance(certificate, dict):
                snapshot["last_run_id"] = certificate.get("run_id")
                snapshot["last_run_finished_at"] = certificate.get("finished_at")
                recommendations = certificate.get("decision_recommendations")
                snapshot["previous_recommendation_count"] = (
                    len(recommendations) if isinstance(recommendations, list) else 0
                )
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    timings["persisted_run_read"] = round(perf_counter() - persisted_started, 4)

    if str(snapshot["database"]) != "READY":
        snapshot["state"] = "DEGRADED"
        snapshot["actionability_reason"] = (
            "Local database cannot be read; no recommendation is actionable."
        )
    elif refresh_is_active(refresh_state):
        snapshot["state"] = "REFRESHING"
        snapshot["actionability_reason"] = (
            "Refresh is in progress; prior recommendations are informational only."
        )
    elif snapshot["data_snapshot"] is None:
        snapshot["state"] = "BLOCKED"
        snapshot["actionability_reason"] = "No immutable market-data snapshot is available."
    else:
        # Even a locally current market snapshot cannot make yesterday's
        # decision actionable.  The decision is bound to the worker's present
        # certified data/PIT/portfolio/risk result.
        snapshot["state"] = "READY_STALE"
        snapshot["actionability_reason"] = (
            "Cached output is informational only until the current decision gates pass."
        )
    timings["fast_start_total"] = round(perf_counter() - started, 4)
    return snapshot


def scheduling_lock_path(state_path: Path) -> Path:
    return state_path.with_suffix(".schedule.lock")


def claim_refresh_schedule(state_path: Path) -> bool:
    """Claim a short-lived schedule lock, recovering only a confirmed stale lock."""

    lock = scheduling_lock_path(state_path)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        with lock.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid()}, handle)
        return True
    except FileExistsError:
        try:
            payload = json.loads(lock.read_text(encoding="utf-8"))
            pid = int(payload.get("pid", 0)) if isinstance(payload, dict) else 0
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            pid = 0
        if pid > 0 and process_is_running(pid):
            return False
        try:
            lock.unlink()
        except OSError:
            return False
        return claim_refresh_schedule(state_path)


def release_refresh_schedule(state_path: Path) -> None:
    try:
        scheduling_lock_path(state_path).unlink()
    except OSError:
        pass
