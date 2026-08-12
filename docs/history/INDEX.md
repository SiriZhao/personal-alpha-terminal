# History index

This directory holds superseded development/session reports. They are audit
history, not current truth. Current truth lives in `README.md`,
`ARCHITECTURE.md`, `REPOSITORY_GUIDE.md`, and `TECH_DEBT.md`.

## Policy

- New ordinary work is recorded by Git commits; no new FINAL/CLOSURE reports for
  routine changes.
- Superseded session material moves here as `YYYY-MM-DD-<phase>/` and this index
  is updated with the phase name, date, content, and what supersedes it.
- Automated run artifacts stay in `reports/` / `var/` and are governed by
  `maintenance artifacts`; they never enter `docs/`.

## Entries

| Phase | Date | Content | Superseded by |
|---|---|---|---|
| `2026-08-12-session/` | 2026-08-12 | Historical research provider, SEC EDGAR corpus, provisional operational certification session reports | TECH-001 hardening, current architecture docs, run certificates |

The `2026-08-12-session/artifacts/` folder also retains the pre-hardening
`provisional-operational-71031e297db8e1f83b9c.json` approval, which was moved out
of the live validation registry after TECH-001 replaced auto-issued approvals
with the explicit `OperationalPolicy` mechanism.
