# Test Evidence

**Executed 2026-11-23 on the development host (Linux x86_64, Python
3.13.18). Never executed on a physical Android/Termux device.** Synthetic
fixtures only; no personal files were scanned.

## Commands and results

| # | Command | Result |
|---|---|---|
| 1 | `python3 -m unittest discover -s tests -v` | **Ran 157 tests — OK** (see V2 addenda at bottom) |
| 2 | `python3 -m unittest discover -s .` (in `tests/`) | Ran 157 tests — OK |
| 3 | `node --check storage_audit/report_templates/report.js` | exits 0 |
| 4 | `python3 tools/benchmark.py --files 10000` | measured; see `docs/PERFORMANCE.md` |
| 5 | Manual CLI smoke (`--help`, `check`, `scan`, `report`, `list-runs`, `show-run`) on fixture | exits 0; output shown in README/§17 handoff |
| 6 | Report builds (fixture runs, cancelled run, older-scan regeneration) | artifacts generated; metrics reconciled against DB (see FINAL_AUDIT) |
| 7 | HTML parse sweep over every generated page (`test_report.py`) | all pages well-formed; no external URLs; links resolve |

Per-module test counts (verbose output, 113 V1 + 23 V2 = 136 total; approximate split):

| Module | Tests | Focus |
|---|---|---|
| `tests/test_safety.py` | 9 | canonicalization, containment (prefix-trap), output policy, exclusions, root validation |
| `tests/test_classifier.py` | ~26 | extension split/classify/MIME, tar.gz, dotfiles, ambiguity, version constant |
| `tests/test_database.py` | ~15 | schema, migrations, transitions, immutability, FK, stale-PID recovery, integrity |
| `tests/test_scanner.py` | ~17 | end-to-end fixture scans, symlink loops, hidden, sparse, cancel, mocked permission/vanish, DB-in-root exclusion |
| `tests/test_analytics.py` | ~10 | recursive rollups, grand total once, empty dirs, same-size candidates |
| `tests/test_exporters.py` | ~15 | CSV injection/BOM, JSONL parse+reconcile, manifest reconciliation, tree chunking, cross-export |
| `tests/test_report.py` | ~15 | page set, escaping, offline sweep, pagination, chunk mode, cancelled labelling |
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

## V2 addendum (2026-11-23, executed on dev host)

| # | Command | Result |
|---|---|---|
| v1 | `python3 -m unittest discover -s tests` | **Ran 136 tests in 4.4s — OK** |
| v2 | `python3 -m unittest discover -s tests -v` | 136 verbose lines, all `ok` |
| v3 | `node --check storage_audit/report_templates/report.js` | exits 0 |
| v4 | `python3 -m compileall -q storage_audit tests` | clean |
| v5 | Fresh-HOME e2e organize loop (scan→plan→preview→approve→apply→undo) | completed on fixture tree |
| v6 | Synthetic perf fixture (1,500 files): scan 0.23 s, plan 0.14 s, apply 0.67 s, peak RSS 24,212 KiB | see V2_PERFORMANCE_VALIDATION.md |
| v7 | `git ls-files | grep -E '\.(db|sqlite3|jsonl|csv)$'` before pushes | empty (no artifacts tracked) |

V2 test modules: `tests/test_organizer.py` (23 tests — planner conflict/symlink/containment, gating, apply, undo, reconcile, hash-verify corruption detection, insufficient-space refusal, destination-appearing sentinel), plus V1 modules updated for schema v2 (`test_database.py` expects `SCHEMA_VERSION`/user_version=2/migrations [1,2]) and CLI help (`test_cli.py` expects 2.0.0).

Per-module counts updated: V1 suite 113 tests + V2 23 = **136**.

**Never executed:** any test on a physical Android device. V2 on-device performance, executor behavior across FUSE/scoped-storage, and Termux permission interactions are all **NOT TESTED** (see V2_ACCEPTANCE_CRITERIA.md gates J and V2 device items).

## V2.1.0 addendum (2026-11-23, executed on dev host)

| # | Command | Result |
|---|---|---|
| w1 | `python3 -m unittest discover -s tests` | **Ran 157 tests — OK** |
| w2 | `python3 -m unittest tests.test_scope_security -v` | 21/21 PASS — all 20 mandatory cases + one symlink-escape variant |
| w3 | `python3 -m compileall -q storage_audit tests` | clean |
| w4 | Fresh-HOME e2e (scan→plan --scope→preview→approve→apply) on synthetic tree with Android/ + hidden children | plan eligible=2 excluded=2; refusal path for Android target exits 2 with the policy message |
| w5 | Preview HTML re-rendered with scope panel | scope panel present; 0 external refs |

v2.1.0 test modules: adds `tests/test_scope_security.py` (21 tests implementing
the mandatory ORGANIZATION_SCOPE_SECURITY_TESTS.md mapping); V1 suite
(113) + V2 engine suite (23) + scope security (21) = **157**.

**Never executed on a device.** org-scope-1 path rules hold regardless of FUSE
behaviour; no claim of on-device verification is made.

## V2.2.0 addendum (2026-11-23, executed on dev host; corrective release)

Context: independent review of public v2.1.0 found three defects (canonical
path propagation, Termux alias resolution, unknown-directory policy not
enforced) and demanded re-verification. All commands below executed on the
development host (Linux x86_64).

| # | Command | Result |
|---|---|---|
| x1 | `python3 -m unittest discover -s tests` | **Ran 201 tests — OK** |
| x2 | `python3 -m unittest tests.test_scope_security -v` | 21/21 PASS |
| x3 | `python3 -m unittest tests.test_scope_hardening -v` | 41/41 PASS (28 initial + 13 branch-audit cases) |
| x4 | `python3 -m unittest tests.test_cli -v` | 13/13 PASS (3 new: registration flow, prohibited registration, recognized folder) |
| x5 | `python3 -m unittest tests.test_organizer -v` | 23/23 PASS (fixture now a CUSTOM folder name requiring explicit registration — exercises the real flow) |
| x6 | `python3 -m compileall -q storage_audit tests` | clean |

New coverage (tests/test_scope_hardening.py, 41 tests): canonical-path
propagation (H01–H06), trusted Termux storage aliases (H07–H13), recognition
vs. explicit registration (H14–H22), boundary/apply/undo branch audit
(H23–H31), input fuzzing of the empty-path class (H32), CLI end-to-end
registration flow in tests/test_cli.py (H33–H35).

v2.2.0 test modules: V1 suite (113) + V2 engine (23) + scope security (21)
+ scope hardening (41) + CLI registration (3 of the 13 CLI tests) = **201**.

Fresh PUBLIC clone verification (executed 2026-11-23, after push): fresh
`git clone` of Manash07Bhoi/StorageLens at HEAD `af91af8` → `--version` ⇒
"Android Storage Audit 2.2.0 (schema 3)"; `python3 -m unittest discover -s
tests` ⇒ **Ran 201 tests — OK**; fresh-clone smoke of the public artifact
(Android/ refusal exit 2; recognized-folder DRAFT plan; custom-folder
registration → plan → unregister → refused again; registry mode 0600);
`pip wheel` ⇒ `android_storage_audit-2.2.0-py3-none-any.whl` (contains
`organizer/scope.py`, no forbidden artifacts); authenticated GitHub API tree
query: 86 entries, no forbidden artifacts. Evidence recorded in
FINAL_AUDIT.md v2.2.0 addendum. **Never executed on a device.** The Termux
alias tests use a synthetic fixture reproducing `~/storage/<alias>`; the real
FUSE layout on the user's phone is NOT tested. No claim of on-device
verification is made.
