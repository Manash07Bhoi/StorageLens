# Changelog

All notable changes to Android Storage Audit are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] — 2026-11-23

### Added (mandatory organization scope policy — org-scope-1)

- **The organization engine may now act only inside ONE explicitly selected,
  user-owned folder.** V2.0.0 planned candidates from the whole scanned
  shared-storage tree — this was unsafe by policy (it could plan operations
  on Android/media and any other accessible content) and is removed.
- `organizer/scope.py` — `validate_scope()` (default-deny target validation:
  exists · is dir · no symlink escapes anywhere in the path · not Android/ nor
  any `Android` component anywhere · no hidden components · not reserved
  (`LOST.DIR`, `.Trash-*`, `.thumbnails`) · not protected system prefixes
  (`/system`, `/vendor`, `/product`, `/apex`, `/odm`, `/data`, …) · not
  Termux-private (`PREFIX`) · not the filesystem root/home/entire shared
  storage · no cross-boundary mount), `walk_eligible()` (recursive default-deny
  exclusion at every level; never follows symlinks; exclusions are recorded),
  `op_path_check()` (per-operation source+destination validation).
- **Android/ is completely prohibited** — all of it, all nesting, all depth,
  with no user-facing override, for planning, execution and undo.
- **Full revalidation before execution and before undo.** Approving a plan
  never widens its scope; apply re-validates the scope from scratch (refusal
  is journalled as `scope_revalidation_failed`) and checks every operation
  individually (source and destination). Recovery never escapes the scope.
- **Schema v3** (additive): `organization_plans` gains `eligible_files`,
  `excluded_entries`, `scope_policy_version`, `scope_canonical`,
  `scope_allowed_json`, `scope_excluded_json`, `scope_validation_json`.
  forward-only migration; v2 → v3 preserves plans and scan history
  (idempotent, tested).
- Preview now renders an **organization-scope panel**: selected folder,
  canonical path, policy version, eligible/excluded counts, reason breakdown,
  per-check validation table, and an explicit hard-boundary notice.
- CLI: `organize-plan --scope FOLDER` (`--target` kept as a compatibility
  alias); refusal prints
  "Organization unavailable: this location is protected or outside the
  permitted user-data scope." plus per-reason lines.
- `docs/ORGANIZATION_SCOPE_SECURITY_TESTS.md` — the mandatory twenty cases;
  all automated in `tests/test_scope_security.py` (21 tests).

### Changed

- Plan rule version → `1.1.0`; candidates come from a fresh lstat walk of the
  approved scope, never from scan rows (V1 scan is provenance-only and
  read-only visibility never grants organization permission).
- Test suite: 136 → **157 tests**; all green.

### Notes

- Copy-keep, move double-consent, no-overwrite, verify-before-source-removal,
  journal, undo semantics: unchanged (V1/V2 safety contract preserved).
- On-device validation remains NOT TESTED; host-validated only, as with v2.0.0.

## [2.0.0] — 2026-11-23

### Added (V2 — planning-first organization engine, M1)

- **Schema v2** (additive, forward-only migration; `user_version=2`):
  `organization_plans`, `organization_operations`, `organization_events`.
- **Organization planner** — builds a DRAFT plan mapping every inventoried
  file into `<target>/<Category>/<original relative path>`. Refuses symlinks;
  flags conflicts (`existing_destination` / `duplicate_destination`) without
  ever overwriting; target root must be inside the scanned root.
- **Offline HTML preview** (`organize-preview`) — one self-contained dark
  page: every operation, live search, pagination, fully escaped data.
- **Explicit approval gate** (`organize-approve`) — execution is refused from
  the `draft` state in code.
- **Copy-keep apply engine** (`organize-apply`) — copy → fsync → verify
  (size+mtime, or SHA-256 with `--hash-verify`) → journal per operation.
  Move mode additionally requires `--acknowledge-source-removal` and removes a
  source only after its destination verifies. `--stop-on-error` marks the plan
  `recovery_required` and halts safely.
- **Undo** (`organize-undo`) — restores moves (copy-verify-remove, with
  same-filesystem fast path); copy-keep undo deletes the created copy only
  with `--approve-delete`. Refuses when the file changed since execution.
- **Interrupted apply** — `in_progress` operations reconciled to
  `interrupted` on next command; nothing is ever assumed complete.
- `organize-history`, `organize-show`, `organize-cancel`.

### Fixed

- Destination free-space pre-check over-reserved (~1 MiB per file): a 15 MB
  copy-keep apply over 1,500 small files was refused with a projected
  1.5 GB requirement. Now `payload + fixed 64 MiB headroom`.

### Security

- Destinations must remain inside the approved target root (realpath check at
  plan time and apply time). No overwrites, ever — verified at plan time and
  again immediately before each write.

### Notes

- **Not on-device validated** — all V2 evidence is from the Linux x86_64 dev
  host with synthetic fixtures. The V1 report from the owner's Android 15
  phone remains a PRIVATE artifact and is not in this repository.
- v1 scans remain fully compatible; `report` and V1 pages are unchanged.

## [1.0.1] — 2026-11-23

### Fixed

- **Mount-boundary issues are no longer reported as "containment".**
  Real-device scan analysis (Android 15, Termux) showed the two skipped
  entries — the scoped-storage FUSE mounts `Android/data` and
  `Android/obb` — were classified by operation `containment`, producing
  the misleading coverage note "Issues: 2 containment". The scanner now
  records `operation=mount_boundary`, and coverage notes group issues by
  operation *and* error code, e.g. "Issues: 2 mount_boundary", plus a
  precise skipped-entries note naming the mount-boundary policy.
  `containment` is now reserved for genuine root-containment rejections
  (`path_outside_root`).
- Coverage-note wording no longer hedges with "(e.g. mount boundary)" —
  it states exactly what was skipped and why, and points to the scan
  issues for the exact paths.

### Notes

- No change to scanning semantics: the mount-boundary rule is unchanged —
  entries on a different filesystem device are still recorded, never
  crossed, and never counted as covered.
- Completed historical runs keep their original recorded wording; the
  fix applies to scans and reports generated from this version onward.
  Re-running `report --latest` does NOT retroactively relabel an
  immutable run's stored issue rows.
- `current_schema` / `SCHEMA_VERSION` unchanged (1); no migration needed.

## [1.0.0] — 2026-11-23

### Release notes

Published as **StorageLens** (public, MIT): https://github.com/Manash07Bhoi/StorageLens — docs-only release hygiene pass (canonical MIT text; host-specific paths scrubbed from recon/performance docs; README gained repository and status sections; SECURITY.md added). No scanner/report behavior changed.


Initial V1 implementation of the Android Storage Audit, developed against
the master specification (`uploads/Android_Storage_Audit_Arena_Master_Prompt.md`)
and the validation supplement (`uploads/Android_Storage_Audit_V1_Gap_Analysis_Validation_Supplement.md`).

### Added

- Read-only shared-storage scanner (`storage_audit/filesystem.py`,
  `scanner.py`): iterative `scandir` traversal, symlinks recorded but never
  followed, per-entry stat-status accounting, batched SQLite commits,
  graceful Ctrl+C cancellation (partial runs marked `cancelled`, never
  `completed`).
- Versioned SQLite schema with forward-only migrations
  (`schema_migrations`), tables `scan_runs`, `entries`, `scan_issues`,
  `directory_stats`, `report_builds`; WAL mode, `synchronous=FULL`, foreign
  keys enforced, parameterized queries throughout.
- Scan status model: `running | completed | completed_with_gaps | cancelled |
  failed | interrupted_or_recovered`. `completed` requires full traversal,
  reconciled counters, and an `integrity_check` pass. Stale `running` rows
  from dead processes are recovered to `interrupted_or_recovered` at startup.
- Environment gate: refuses to scan when no listable root is resolvable;
  non-Termux hosts run in an explicitly labelled development mode; never
  falls back to a different root silently.
- Containment: lexical canonicalization, realpath checks, output-under-scan-root
  exclusion, no mount-boundary crossing, database files under the scan root
  excluded exactly.
- Recursive directory analytics (counts and logical bytes, counted once from
  regular files; directory `st_size` never used).
- Filename-derived classification: documented extension table,
  case-insensitive, dotfiles without extension, compound `.tar.gz`-style
  suffixes, trailing-dot determinism, unknown extensions stay unknown
  (classification version 1.0.0).
- Offline HTML report (`index.html` + paginated detail pages, 500 rows per
  page): dark-first premium theme, inline SVG, no CDN/fonts/trackers,
  accessible (skip links, labels, roles, keyboard-navigable), responsive.
- Full-inventory search page: inline `window.__INVENTORY` up to 30,000
  entries, otherwise `data/inventory_NNN.js` chunks; filters compose with
  AND; sort options; reset restores the full set; noscript fallback links to
  static paginated tables.
- Exports: `files.csv`, `directories.csv`, `entries.jsonl` (JSONL schema v1,
  carries `scan_id`), `scan_issues.csv`, `file_types.csv`,
  `directory_tree.txt` (deterministic chunking > 8 MiB with index),
  `summary.md`, `README.md`, `manifest.json` (SHA-256 of every export).
- CSV formula-injection neutralization (`=`, `+`, `-`, `@` prefixing with a
  literal apostrophe), UTF-8 with BOM for spreadsheet compatibility, HTML
  entity escaping everywhere, script-safe JSON (`<`, `>`, `&`, U+2028/2029),
  terminal-output sanitization.
- Report (re)generation from any existing scan run without rescanning
  (`report --latest | --scan-id N`); `report_state` tracked separately from
  scan success.
- CLI: `check`, `scan`, `report`, `list-runs`, `show-run`; exit codes
  0/1/2/3/4; `--output-dir`, `--db`, `--root`, `STORAGE_AUDIT_ROOT`.
- "Review Candidates" report page: neutral observations only (very large
  files, large files unmodified for 5+ years, same-size candidate groups),
  explicitly labelled as not-junk and not-duplicates; no action controls.
- Test suite: 110 `unittest` tests with synthetic fixtures (Unicode/emoji/
  newline filenames, `<script>` injection names, sparse files, broken
  symlinks, self-referential symlink loops, permission-denied branches,
  cancelled runs, interrupted-run recovery, CSV/JSONL/manifest/tree/report
  reconciliation, offline-report URL scan).
- Specification traceability matrices (`docs/TRACEABILITY_*.md`), security
  read-only audit, measured performance report, severity-tagged gap
  register, and final self-audit.

### Fixed (during development)

- `size_status` literal mismatch caused inventoried bytes to read as 0.
- Recursive directory byte/count accumulation double-counted directories.
- Embedded inventory JSON could break out of its `<script>` block with
  hostile filenames — now fully `\uXXXX`-escaped for HTML-significant
  characters.
- Manifest counter for unavailable sizes counted all rows instead of
  unavailable/failed ones.
- Raw C0 control characters in filenames corrupted HTML output — now
  escaped as entities.
- Misleading "% of OS-reported used bytes" figure for sparse files — now
  explicitly labelled with an explanatory note.
- JSONL export dropped the `scan_id` field required for cross-export
  reconciliation.

### Known limitations

See `docs/GAP_REGISTER.md` — notably: no on-device Android validation yet
(implementation host is Linux x86_64), no V1 resume of interrupted scans,
no hashing-based deduplication, shared storage only.

