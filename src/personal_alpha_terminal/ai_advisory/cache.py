"""ROUND24 AI brief cache (B8).

One LLM call per (run identity + artifact hashes + model + prompt version).
Reopening the terminal reads the cache instead of spending API cost.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

DEFAULT_CACHE_ROOT = Path("var/ai-brief-cache")


@dataclass(frozen=True, slots=True)
class BriefCacheKey:
    run_id: str
    data_hash: str
    factor_hash: str
    portfolio_hash: str
    risk_hash: str
    intelligence_hash: str
    model: str
    prompt_version: str

    def digest(self) -> str:
        payload = {
            "run_id": self.run_id,
            "data_hash": self.data_hash,
            "factor_hash": self.factor_hash,
            "portfolio_hash": self.portfolio_hash,
            "risk_hash": self.risk_hash,
            "intelligence_hash": self.intelligence_hash,
            "model": self.model,
            "prompt_version": self.prompt_version,
        }
        return sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()


class BriefCache:
    """Filesystem cache of validated AI briefs keyed by immutable identity."""

    def __init__(self, root: Path = DEFAULT_CACHE_ROOT) -> None:
        self.root = root

    def _path(self, key: BriefCacheKey) -> Path:
        return self.root / f"{key.digest()}.json"

    def read(self, key: BriefCacheKey) -> dict[str, object] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def write(self, key: BriefCacheKey, document: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "cache_key": key.digest(),
            "cached_at": datetime.now(UTC).isoformat(),
            **document,
        }
        self._path(key).write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )

    def quarantine(
        self, key: BriefCacheKey, *, reason: str, raw: str | None
    ) -> Path:
        quarantine_dir = self.root / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        path = quarantine_dir / f"{key.digest()}.json"
        path.write_text(
            json.dumps(
                {
                    "status": "AI_BRIEF_QUARANTINED",
                    "reason": reason,
                    "raw_payload": raw,
                    "quarantined_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        return path
