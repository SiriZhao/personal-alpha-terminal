# Migration Guide to 1.2.0-rc.1

## Scope

This is a release candidate. It does not represent final production release.

## Existing config

Existing config.yaml remains compatible. Run:

```powershell
python main.py doctor
python main.py settings
```

## Existing database and ledgers

The database and ledgers are protected and remain in place. Run doctor to verify migration head and database connection.

## OperationalPolicy

Code/config identity changed with this release, so any existing OperationalPolicy will report:

```text
IDENTITY_MISMATCH
Effective: false
```

This is expected fail-closed behavior. Check:

```powershell
python main.py operational-policy status
```

Do not auto-renew. Re-authorize explicitly only after review:

```powershell
python main.py operational-policy create --decision ALLOW_PROVISIONAL
```

## Fresh install

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ai]"
.\.venv\Scripts\python.exe main.py doctor
```

## Rollback

Keep the previous source checkout or release package. No runtime data is deleted by this release.
