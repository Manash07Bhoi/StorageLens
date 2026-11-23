# Changelog

All notable changes to Android Storage Audit are recorded here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] — 2026-11-23

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

