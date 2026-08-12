"""Run historical PIT text/event corpus certification on a local raw corpus."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path

from personal_alpha_terminal.intelligence.schemas import RawInformation, UnifiedEvent
from personal_alpha_terminal.intelligence.text_corpus import (
    TextCorpusSource,
    TextCorpusSourceKind,
    TextCorpusState,
    certify_text_corpus,
    persist_text_corpus_manifest,
)


def _source(path: Path) -> TextCorpusSource:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("text corpus source contract must be a JSON object")
    document["source_kind"] = TextCorpusSourceKind(document["source_kind"])
    return TextCorpusSource(**document)


def _documents(root: Path) -> tuple[RawInformation, ...]:
    output: list[RawInformation] = []
    for path in sorted(root.rglob("*.jsonl")) if root.exists() else ():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                output.append(RawInformation.model_validate_json(line))
    return tuple(output)


def _events(path: Path | None) -> tuple[UnifiedEvent, ...]:
    if path is None or not path.exists():
        return ()
    output: list[UnifiedEvent] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            output.append(UnifiedEvent.model_validate_json(line))
    return tuple(output)


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--events", type=Path, default=None)
    parser.add_argument("--corpus-id", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--provider-version", default="")
    parser.add_argument("--required-start", default=None)
    parser.add_argument("--required-end", default=None)
    parser.add_argument("--output", type=Path, default=Path("var/research-data/text-corpus"))
    args = parser.parse_args()
    cutoff = datetime.fromisoformat(args.cutoff.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise ValueError("corpus cutoff must be timezone-aware")
    manifest = certify_text_corpus(
        _documents(args.root),
        _events(args.events),
        corpus_id=args.corpus_id,
        sources=(_source(args.source),),
        cutoff=cutoff,
        required_start=_optional_date(args.required_start),
        required_end=_optional_date(args.required_end),
        provider_version=args.provider_version,
    )
    path = persist_text_corpus_manifest(manifest, args.output)
    print(f"corpus_id={manifest.corpus_id}")
    print(f"state={manifest.certification_state.value}")
    print(f"documents={manifest.document_count}")
    print(f"raw_content_hash={manifest.raw_content_hash}")
    print(f"manifest_path={path.resolve()}")
    for blocker in manifest.blockers:
        print(f"blocker={blocker}")
    return 0 if manifest.certification_state is TextCorpusState.PIT_TEXT_CERTIFIED else 3


if __name__ == "__main__":
    raise SystemExit(main())
