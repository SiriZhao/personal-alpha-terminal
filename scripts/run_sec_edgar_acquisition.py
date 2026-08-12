"""Run official SEC EDGAR acquisition into an immutable PIT text corpus."""

from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime
from pathlib import Path

from personal_alpha_terminal.intelligence.schemas import RawInformation
from personal_alpha_terminal.intelligence.sec_edgar_acquisition import (
    SecEdgarAcquisitionConfig,
    SecEdgarClient,
    SecEdgarRateLimiter,
    acquire_company_corpus,
    load_cik_mapping_manifest,
    verify_sec_edgar_landing_zone,
)
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
    path = root / "documents.jsonl"
    if not path.exists():
        return ()

    output: list[RawInformation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            output.append(RawInformation.model_validate_json(line))
    return tuple(output)


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cik", type=int, required=True)
    parser.add_argument("--mapping", type=Path, default=None)
    parser.add_argument("--allow-unmapped", action="store_true")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--acquisition-id", required=True)
    parser.add_argument("--provider-version", default="sec-edgar-v1")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("var/research-data/text-corpus/raw/sec"),
    )
    parser.add_argument("--required-start", required=True)
    parser.add_argument("--required-end", required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--max-documents", type=int, default=1_000)
    parser.add_argument("--rate-limit", type=float, default=1.0)
    parser.add_argument("--corpus-output", type=Path, default=Path("var/research-data/text-corpus"))
    args = parser.parse_args()

    user_agent = os.getenv("SEC_USER_AGENT")
    if not user_agent or "@" not in user_agent:
        print("SEC_USER_AGENT_REQUIRED")
        print("Set SEC_USER_AGENT to a declared contact, e.g. 'Company Name admin@example.com'.")
        return 3

    source = _source(args.source)
    mapping = None
    if args.mapping is not None:
        mappings = load_cik_mapping_manifest(args.mapping)
        mapping = next((item for item in mappings if item.cik == args.cik), None)
    if mapping is None and not args.allow_unmapped:
        print("SEC_CIK_MAPPING_MISSING")
        return 3

    config = SecEdgarAcquisitionConfig(user_agent=user_agent)
    rate_limiter = SecEdgarRateLimiter(max_requests_per_second=args.rate_limit)
    client = SecEdgarClient(config, rate_limiter=rate_limiter)
    required_start = date.fromisoformat(args.required_start)
    required_end = date.fromisoformat(args.required_end)
    cutoff = datetime.fromisoformat(args.cutoff.replace("Z", "+00:00"))
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")

    report = acquire_company_corpus(
        cik=args.cik,
        mapping=mapping,
        config=config,
        client=client,
        source=source,
        output=args.output / args.acquisition_id,
        acquisition_id=args.acquisition_id,
        required_start=required_start,
        required_end=required_end,
        max_documents=args.max_documents,
        provider_version=args.provider_version,
    )
    print(f"acquisition_id={report.acquisition_id}")
    print(f"status={report.status}")
    print(f"documents={report.acquired_document_count}")
    print(f"mapped={report.mapped_document_count}")
    print(f"unmapped={report.unmapped_document_count}")
    print(f"amendments={report.amendment_count}")
    print(f"issuers={report.issuer_count}")
    print(f"raw_content_hash={report.raw_content_hash}")
    print(f"manifest_path={report.manifest_path}")
    for blocker in report.blockers:
        print(f"acquisition_blocker={blocker}")

    acquisition_root = args.output / args.acquisition_id
    verification = verify_sec_edgar_landing_zone(acquisition_root)
    if not verification.ok:
        print("SEC_LANDING_ZONE_FAIL")
        for blocker in verification.blockers:
            print(f"landing_blocker={blocker}")
        return 3
    documents = _documents(acquisition_root)
    manifest = certify_text_corpus(
        tuple(documents),
        (),
        corpus_id=f"sec-edgar-{args.cik}-{args.acquisition_id}",
        sources=(source,),
        cutoff=cutoff,
        required_start=required_start,
        required_end=required_end,
        provider_version=args.provider_version,
    )
    path = persist_text_corpus_manifest(manifest, args.corpus_output)
    print(f"corpus_state={manifest.certification_state.value}")
    print(f"corpus_manifest={path.resolve()}")
    for blocker in manifest.blockers:
        print(f"corpus_blocker={blocker}")
    return 0 if manifest.certification_state is TextCorpusState.PIT_TEXT_CERTIFIED else 3


if __name__ == "__main__":
    raise SystemExit(main())
