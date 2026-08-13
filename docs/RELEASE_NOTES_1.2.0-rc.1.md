# Personal Alpha Terminal 1.2.0-rc.1 Release Notes

Status: RELEASE CANDIDATE, not final release.

- Version: 1.2.0-rc.1
- Build ID: pat-1.2.0-rc.1-81a34b294d4a-20260813180525
- Git commit: 81a34b294d4a83820753b6f3ee39dc0da40d5803
- Windows ZIP: release/PersonalAlphaTerminal-v1.2.0-rc.1-win64.zip
- Dependency manifest: release/PersonalAlphaTerminal-v1.2.0-rc.1-win64/DEPENDENCY_MANIFEST.txt
- Build manifest: release/PersonalAlphaTerminal-v1.2.0-rc.1-win64/BUILD_MANIFEST.json
- Checksums: release/SHA256SUMS.txt

## Highlights

- Chinese terminal overview and complete Chinese user guide.
- ROUND14 PIT feature/outcome research dataset and alpha protocol.
- ROUND15 conditional probability research with fallback.
- Frozen package operational identity fix.
- Fresh install dependency fix: networkx is now a core dependency.
- Repository cleanup inventory and safe deletion manifest.

## Research status

- LLM production influence: NONE.
- Probability production weight: 0.
- ROUND14 verdict: ROUND14_LLM_ALPHA_NOT_PROVED.
- ROUND15 verdict: PROBABILITY_FALLBACK_CLASSICAL.

## Install

```powershell
python -m venv .venv314
.\.venv314\Scripts\python.exe -m pip install -e ".[dev,ai]"
```

User guide: docs/USER_GUIDE_zh-CN.md