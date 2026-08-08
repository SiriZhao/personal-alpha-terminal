from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol


def extraction_cache_key(content_hash: str, model_version: str, prompt_version: str) -> str:
    return sha256(f"{content_hash}|{model_version}|{prompt_version}".encode()).hexdigest()


class ExtractionCache(Protocol):
    def get(self, key: str) -> str | None: ...
    def put(self, key: str, payload: str) -> None: ...


@dataclass(slots=True)
class InMemoryExtractionCache:
    values: dict[str, str]

    def __init__(self) -> None:
        self.values = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def put(self, key: str, payload: str) -> None:
        self.values.setdefault(key, payload)
