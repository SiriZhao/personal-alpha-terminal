# ROUND18 - Version Upgrade and Release Candidate

Date: 2026-08-14

Verdict: `ROUND18_RELEASE_CANDIDATE_READY`

## Version decision

Canonical current version was found to be `1.1.0`, not `2.1.0`. Following the
semantic-version instruction for this case, the selected release candidate is:

`1.2.0-rc.1`

This is not a final release. ROUND19 remains the formal examination round.

## Version consistency updated

- pyproject.toml
- package __version__ and __build_version__
- CLI version command
- packaging version_info.txt
- packaging build script
- docs/CURRENT_STATUS.json
- docs/CURRENT_STATUS.md
- docs/CLI_REFERENCE_ZH_CN.md
- version assertion tests

## Build evidence

- Version: 1.2.0-rc.1
- Build ID: pat-1.2.0-rc.1-81a34b294d4a-20260813180525
- Git commit: 81a34b294d4a83820753b6f3ee39dc0da40d5803
- Windows ZIP: release/PersonalAlphaTerminal-v1.2.0-rc.1-win64.zip
- ZIP SHA256: 04203e9bf254148add0100fb944df89dc1a50d5664cd1abb03c3978cdfc58222
- Manifest file count: 1961
- Build manifest: release/PersonalAlphaTerminal-v1.2.0-rc.1-win64/BUILD_MANIFEST.json
- Dependency manifest: release/PersonalAlphaTerminal-v1.2.0-rc.1-win64/DEPENDENCY_MANIFEST.txt
- Checksums: release/SHA256SUMS.txt
- Release notes: docs/RELEASE_NOTES_1.2.0-rc.1.md
- Migration guide: docs/MIGRATION_GUIDE_1.2.0-rc.1.md

## Fresh install and package smoke

A fresh temporary venv was created and installed successfully with:

```powershell
python -m venv .tmp/rc-fresh-venv
.tmp/rc-fresh-venv/Scripts/python.exe -m pip install -e ".[dev,ai]"
```

Fresh install initially exposed a missing core dependency, `networkx`, which
was added to core dependencies and verified again. Fresh venv smoke passed:

- version: Personal Alpha Terminal 1.2.0-rc.1
- CLI help: PASS
- intelligence status: PASS

Packaged Windows exe smoke passed:

- version: PASS
- help: PASS
- doctor: reaches expected `IDENTITY_MISMATCH`; no frozen startup failure

## Migration behavior

- Existing config: compatible.
- Existing database and ledgers: protected and intact.
- Existing OperationalPolicy: reports `IDENTITY_MISMATCH` and `Effective: false`.
- No policy is renewed automatically.
- Re-authorization remains an explicit user action.

## Platform honesty

- Windows package build and packaged exe smoke: PASS on this Windows host.
- macOS/Linux native runtime: NOT tested on real hosts.
- Static Python source compatibility is retained; no native macOS/Linux runtime
  PASS is claimed.

## Gates

- Full pytest: 963 passed
- quant_critical: 31 passed
- Ruff: All checks passed
- Strict mypy: 420 source files, no issues
- Secret scan: SECRET_SCAN_PASS

## Final disposition

`ROUND18_RELEASE_CANDIDATE_READY`

ROUND19 scope is not defined in this prompt, so no further autonomous round
was started.