# SocialPilotAI database revisions

Revision chain:

```text
<base>
  -> 0001_pre_x2_runtime
  -> 0002_x2_presentation_snapshots (head)
```

`0001_pre_x2_runtime` owns the thirteen tables that existed before X2.
`0002_x2_presentation_snapshots` adds the immutable snapshot table.

Use the guarded local command instead of invoking online Alembic directly:

```powershell
python -m app.cli.database_migrations upgrade `
  --database C:\path\to\socialpilot.db `
  --backup-dir C:\path\to\backups
```

The Stage 1A CLI is **offline-only**. Stop every process that can access the
database before either `upgrade` or `restore`; a journal, WAL/SHM sidecar, an
active SQLite connection, or an existing migration lock causes a safe refusal.

Each operation atomically owns `<database>.migration.lock` for its complete
upgrade or restore lifetime. A second operation is rejected immediately. The
lock is removed only when the process can verify its own random ownership
token and file identity; an unverified or externally replaced lock is retained
for manual investigation.

The command creates and verifies an offline byte-exact SQLite backup before
touching an existing database. It hashes the source before copying, hashes the
backup, then hashes the source again before migration. Any change removes the
unfinished backup/manifest and stops safely. Unversioned databases are stamped
only after their complete structural fingerprint matches a known revision. A
failed migration automatically restores the verified backup when the target
still satisfies the same offline protections.

Startup integration intentionally remains deferred to Stage 1B. The Stage 1B
launcher must stop and verify the application services before migration and
must use this same per-database lock rather than introducing a separate lock.
