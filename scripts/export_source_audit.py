from __future__ import annotations

import argparse
from pathlib import Path

from personal_alpha_terminal.core.source_audit import export_source_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a complete, import-validated source audit")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = export_source_audit(root, args.destination)
    print(f"AUDIT_EXPORT={result.destination}")
    print(f"FILES={result.file_count}")
    print(f"PRODUCTION_FILES={result.production_file_count}")
    print(f"MANIFEST_SHA256={result.manifest_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
