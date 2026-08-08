from __future__ import annotations

import argparse
import json
from importlib import metadata
from pathlib import Path

from personal_alpha_terminal import __version__


def build_documents() -> tuple[dict[str, object], list[dict[str, str]]]:
    components: list[dict[str, object]] = []
    licenses: list[dict[str, str]] = []
    distributions = sorted(
        metadata.distributions(),
        key=lambda item: item.metadata["Name"].lower(),
    )
    for distribution in distributions:
        name = distribution.metadata["Name"]
        version = distribution.version
        license_name = distribution.metadata.get("License") or "UNKNOWN"
        components.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name.lower().replace('_', '-')}@{version}",
                "licenses": [{"license": {"name": license_name}}],
            }
        )
        licenses.append({"name": name, "version": version, "license": license_name})
    sbom: dict[str, object] = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "Personal Alpha Terminal",
                "version": __version__,
            },
            "properties": [
                {
                    "name": "pat:scope",
                    "value": "Python packages visible in the isolated build environment",
                }
            ],
        },
        "components": components,
    }
    return sbom, licenses


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sbom", type=Path, required=True)
    parser.add_argument("--licenses", type=Path, required=True)
    args = parser.parse_args()
    sbom, licenses = build_documents()
    for destination, payload in ((args.sbom, sbom), (args.licenses, licenses)):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
