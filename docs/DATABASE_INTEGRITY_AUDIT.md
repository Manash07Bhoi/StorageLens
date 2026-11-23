# Database Integrity Audit

Engine: SQLite (WAL, synchronous=FULL, busy_timeout=30s, foreign_keys=ON).
Versions: schema 1 (V1) → schema 2 (V2 additive). `user_version=2` after migrate.

## Schema guarantees
- `scan_runs(id)` PK; `entries(scan_id → scan_runs.id RESTRICT, RESTRICT)`;
  UNIQUE none needed for entries (autoincrement PK); `scan_issues` similar;
  v2: `organization_operations UNIQUE(plan_id, seq)`, FKs CASCADE/RESTRICT as
  appropriate.
- Indexes: (scan_id, parent, name, extension, category, size, kind) for V1;
  v2: (plan_id), (status), (plan_id), (operation_id) as declared.
- Integrity: `PRAGMA integrity_check` executed on completed runs; runs never
  reach `completed` with a failed check.
- Transactions: batched inserts (250–2000 rows) commit per batch; report build
  bookkeeping separate; org engine uses one transaction per operation +
  plan-level transitions.

## Migration testing (executed)
1. Fresh DB → migrate → `user_version=2`; tables scan_runs/entries/scan_issues/
   report_builds/organization_plans/organization_operations/organization_events
   all present. (test: fresh_db_has_v2_tables)
2. Hand-built v1 database (user_version=1, schema_migrations [1]) with a
   pre-existing scan row → migrate → version=2, scan_runs row preserved, v2
   tables created. (test: v1_database_migrates_and_preserves_data)
3. Idempotent double migrate — safe. (test_migration_is_idempotent)
4. `user_version=99` → explicit refusal, no silent downgrade. (test_newer_schema_refused)

## Failure handling tested
- Disk full: pre-flight `disk_usage` refusal mocked to 1 byte → zero writes made.
- Busy/locked: WAL + busy_timeout; scan holds no long read tx during traversal.
- Interrupted apply: manual `in_progress` → `reconcile_interrupted` →
  `interrupted`, original rows preserved.
- Cancelled scan: partial batches committed; run = `cancelled`; report labelled
  INCOMPLETE on every page.

## Recovery verification (dev host)
Cancelled-run fixture → report build OK, INCOMPLETE markers present. Stale
`running` rows → recovered at next launch → `interrupted_or_recovered`.
`PRAGMA integrity_check` on existing phone DB: **not executed — no phone DB
access; recommended on-device:**
`sqlite3 ~/.local/share/android-storage-audit/storage_audit.sqlite3 "PRAGMA integrity_check;"`
(Termux: `pkg install sqlite` — optional, not required by the tool.)

## Known limits
- No multi-writer concurrency beyond busy_timeout.
- Backup strategy: user-managed copies of the sqlite file; the tool never
  copies it (no live-backup hazard).
- No encryption at rest (Android sandbox + file-based encryption of the device
  apply; documented in PRIVACY_AND_SAFETY).
