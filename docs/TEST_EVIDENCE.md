# Test Evidence

**Executed 2026-11-23 on the development host (Linux x86_64, Python
3.13.18). Never executed on a physical Android/Termux device.** Synthetic
fixtures only; no personal files were scanned.

## Commands and results

| # | Command | Result |
|---|---|---|
| 1 | `python3 -m unittest discover -s tests -v` | **Ran 110 tests in 1.5s — OK** (110 passed, 0 failed, 0 skipped) |
| 2 | `python3 -m unittest discover -s .` (in `tests/`) | Ran 110 tests — OK |
| 3 | `node --check storage_audit/report_templates/report.js` | exits 0 |
| 4 | `python3 tools/benchmark.py --files 10000` | measured; see `docs/PERFORMANCE.md` |
| 5 | Manual CLI smoke (`--help`, `check`, `scan`, `report`, `list-runs`, `show-run`) on fixture | exits 0; output shown in README/§17 handoff |
| 6 | Report builds (fixture runs, cancelled run, older-scan regeneration) | artifacts generated; metrics reconciled against DB (see FINAL_AUDIT) |
| 7 | HTML parse sweep over every generated page (`test_report.py`) | all pages well-formed; no external URLs; links resolve |

Per-module test counts (verbose output, 110 total):

| Module | Tests | Focus |
|---|---|---|
| `tests/test_safety.py` | 9 | canonicalization, containment (prefix-trap), output policy, exclusions, root validation |
| `tests/test_classifier.py` | ~26 | extension split/classify/MIME, tar.gz, dotfiles, ambiguity, version constant |
| `tests/test_database.py` | ~15 | schema, migrations, transitions, immutability, FK, stale-PID recovery, integrity |
| `tests/test_scanner.py` | ~17 | end-to-end fixture scans, symlink loops, hidden, sparse, cancel, mocked permission/vanish, DB-in-root exclusion |
| `tests/test_analytics.py` | ~10 | recursive rollups, grand total once, empty dirs, same-size candidates |
| `tests/test_exporters.py` | ~15 | CSV injection/BOM, JSONL parse+reconcile, manifest reconciliation, tree chunking, cross-export |
| `tests/test_report.py` | ~14 | page set, escaping, offline sweep, pagination, chunk mode, cancelled labelling |
| `tests/test_cli.py` | ~10 | help/version/exit codes, check gating, scan→report→list flow, report-missing-id refusal |

(Approximate split; exact names: run command 1 for the full listing.)

## What the suite covers

- **Fixture fidelity** (`tests/helpers.py`): nested/empty/hidden dirs,
  Unicode/emoji/Devanagari names, newline/tab/comma/quote filenames,
  `<img onerror>` injection filename, 256 MiB sparse file, broken and
  directory symlinks, zero-byte file, duplicate 30-byte pair, dotfiles,
  compound extensions. Source-tree snapshot taken before/after scans to
  prove read-only behavior.
- **Failure branches**: mocked `PermissionError` on directory enumeration →
  run finishes `completed_with_gaps`, siblings inventoried; mocked
  disappearing file → entry kept with `stat_status='failed'` + issue;
  cancel event pre-set → `cancelled`, `coverage_incomplete=1`, report
  labelled INCOMPLETE on every page.
- **Report regeneration**: older `scan_id` rebuilt without rescanning;
  counters unchanged; `report_state` transitions; `report_builds` audit row
  written; run isolation verified.
- **Exports**: manifest SHA-256 verify by hand during development; tests
  assert counts/bytes reconcile DB ↔ CSV ↔ JSONL ↔ manifest.
- **Offline**: regex sweep over all generated HTML/JS/CSS for external
  URLs — none found; `node --check` passes.

## What is NOT tested (explicit)

- On a physical Android phone / real Termux (see `docs/GAP_REGISTER.md`
  G-001).
- Browser automation (viewport rendering, JS execution, focus traversal):
  manual review only (G-007).
- SQLite `database is locked`/disk-full injection (G-005).
- 2 GB+ real files (sparse fixture exercises 256 MiB logical; code paths
  use Python ints/SQLite INTEGER throughout).
- Very large inventories (>100k entries) in CI; 30k inline→chunk switch is
  unit-tested with mocked limits.

## Test-count history (109 → 110) — investigation

The first completion report stated **109** tests; the current suite runs
**110**. The difference is exactly one test:
`tests/test_report.py::TestReportStructure::test_review_candidates_page_renders_neutral_observations`,
added in the same change set that added the `review_candidates.html` page
(master §7.2 item 12). No test was renamed, removed or silently dropped.
A secondary counting artifact made the discrepancy look second-order: one
test line printed a `ResourceWarning` (unclosed file handle in an earlier
version of the chunk-mode test), so a naive `grep -c "… ok$"` reported 109
while unittest reported 110. The warning was fixed and re-verified under
`python3 -W error::ResourceWarning`.

## Honesty note

Earlier in the build, `size_status='ok'` vs `'observed'` mismatch caused a
rescan to report 0 B inventoried. It was caught by inspecting real output,
fixed, and the full scan re-verified (1.00 GiB observed). All test results
above are from the final code, after that fix and after the
`unavailable_size_files` manifest fix (which now reports 0 for full-coverage
runs instead of 27).
