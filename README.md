# StorageLens — Android Storage Audit

**Read-only, local inventory and audit of accessible shared internal storage
for Termux on Android, plus an opt-in, approval-gated organization engine (V2).**

Android Storage Audit walks the part of your phone's internal storage that
Termux (and apps granted shared-storage access) can see, records metadata
about every file and folder it can enumerate, and produces:

- a searchable **offline HTML report** (dark-first, no network, no JavaScript
  frameworks, fully accessible);
- **machine-readable exports** (CSV, JSON Lines, a chunked text tree,
  Markdown summary, and a SHA-256 manifest);
- a **SQLite database** of scan runs that survives interruptions and can be
  queried later without rescanning.

The **scan** never modifies, moves, renames, deletes, copies, compresses,
deduplicates, uploads, or "cleans" anything. It never reads file contents.
It never uses the network. It never requires root.

The optional **V2 organization engine** (`organize-*` commands) is the only
part of the tool that can change files, and only after explicit approval:
it builds a plan, shows an offline preview, requires `organize-approve`, and
never overwrites an existing file. **copy-keep** (the default) never deletes
anything. See [V2 organization engine](#v2-organization-engine-opt-in).

> **Honest scope statement.** This tool reports on *accessible* shared
> storage — the tree Termux can enumerate through the Android storage layer,
> normally `~/storage/shared` after `termux-setup-storage`. It does **not**
> see app-private sandboxes, other apps' internal data, or anything Android
> does not expose to shared storage. It is not a whole-device forensic image
> and it makes no claim of 100% device coverage. See
> [Limitations](#limitations--important) below.

---

## Requirements

- **Android phone** with **Termux** installed (from F-Droid or the Termux
  GitHub releases — do not use the outdated Play Store build).
- **Python 3.8+** in Termux (`pkg install python`).
- Storage permission granted to Termux (see first-run steps below).
- No root. No network. No other packages — the tool is **Python standard
  library only**.

The development machine used to build this tool was **Linux x86_64, not
Android/Termux**. Everything you see here has been verified on that Linux
host; see [Validation status](#validation-status) for exactly what that
means and what has *not* been verified.

---

## First run on your phone (exact steps)

### 1. Install Termux and Python

```sh
# In Termux:
pkg update
pkg install python
python --version   # must print 3.8 or newer
```

### 2. Grant shared-storage access

```sh
termux-setup-storage
```

A system dialog asks for storage permission. Tap **Allow**. Afterwards:

```sh
ls ~/storage/shared
```

This must list your shared storage (e.g. `DCIM`, `Download`, `Pictures`,
`Documents`, `Music`, …). If it prints an error or an empty listing:

- the tool will **stop with a clear error** rather than pretend it scanned
  something;
- run `termux-setup-storage` again and grant permission, or check
  Android **Settings → Apps → Termux → Permissions → Files and media**.

### 3. Get the tool onto the phone

Copy the project folder to the phone, for example into
`~/storage/shared/android-storage-audit` or anywhere in your Termux home.
There is no internet install path and no package repository for it — copying
the folder (via USB, Syncthing, or `scp` from your computer) is the intended
distribution. Do **not** download random copies from mirrors.

### 4. Check the environment

```sh
cd ~/android-storage-audit   # wherever you copied it
bash run_audit.sh check
```

This verifies: Python version, that `~/storage/shared` exists and is
listable, free disk space, output location writability, and whether you are
actually running under Termux. If the root is missing or unlistable, it
tells you exactly how to fix it and exits with code `2`.

### 5. Run the scan

```sh
bash run_audit.sh scan
```

What you will see:

- a startup banner saying the scan is **read-only** and that it makes **no
  changes** to your files;
- a progress line (files/directories/bytes seen, issues) that updates without
  spamming one line per file;
- at the end, the **scan run id** (e.g. `#1`), status, counters, and the path
  to the report.

The default scan root is `~/storage/shared`. The output goes to

```
${XDG_DATA_HOME:-~/.local/share}/android-storage-audit/
    storage_audit.sqlite3          # database (all runs)
    reports/run_<id>_<timestamp>/          # HTML report + exports
```

Pressing **Ctrl+C** during a scan stops it gracefully: the partial run is
marked `cancelled`, and the report is labelled **INCOMPLETE** everywhere.
A cancelled run is never shown as complete, and a partial report never
claims full coverage.

### 6. Open the report

```sh
# Print the exact path of the latest report:
bash run_audit.sh list-runs
bash run_audit.sh show-run <id>
```

The report directory contains `index.html` — open it with any Android
browser. All pages work fully offline: no CDN, no external fonts, no
trackers, no telemetry. The complete machine-readable data is alongside it
under `exports/`:

| File | Contents |
|---|---|
| `entries.jsonl` | One JSON object per inventoried entry (all fields, `schema_version: 1`, keeps `scan_id`) |
| `files.csv` | Every regular file, full metadata (UTF-8 BOM, formula-injection-safe) |
| `directories.csv` | Every directory + direct/recursive counts and recursive bytes |
| `file_types.csv` | Category and extension rollups (counts and bytes) |
| `scan_issues.csv` | Every issue: path, operation, error category, message, timestamp |
| `directory_tree.txt` | Complete hierarchy; split into deterministic chunks (with `directory_tree_index.txt`) above 8 MiB |
| `summary.md` | Human-readable summary, counters, methodology, coverage notes |
| `README.md` | Generated per-report column/field legend and units |
| `manifest.json` | exact `scan.id` + status, tool/schema/classification versions, counters, and SHA-256 + byte size of every other export |

All exports of one report describe the same `scan_id`; tests reconcile
counts and bytes across them.

To rebuild the report later **without rescanning**:

```sh
bash run_audit.sh report --latest
# or a specific run:
bash run_audit.sh report --scan-id 1
```

### 7. Run the test suite (optional, recommended)

```sh
python3 -m unittest discover -s tests -v
```

Tests build their own synthetic fixture tree in a temporary directory. They
never touch your phone's storage.

---

## V2 organization engine (opt-in)

V2 turns an understanding of your storage into an **approved, reversible,
verified reorganization** — nothing happens silently:

```
scan → organize-plan → organize-preview → organize-approve → organize-apply → organize-undo
```

Commands (all local, offline, no network):

| Command | What it does |
|---|---|
| `organize-plan --target DIR [--action copy-keep\|move] [--hash-verify] [--scan-id N]` | Build a DRAFT plan from a completed scan: maps every inventoried file to `<target>/<Category>/<original relative path>`. Conflicts are flagged, never silently overwritten. |
| `organize-preview --plan-id N` | Write a fully offline, premium dark HTML preview of the plan (every operation listed, filterable/paginated). Review it before approving. |
| `organize-approve --plan-id N` | Explicit approval. Moves require double consent (`--action move` at plan time AND `--acknowledge-source-removal` at apply time). |
| `organize-apply --plan-id N [--acknowledge-source-removal]` | Execute approved operations: copy → fsync → verify (size+mtime, or SHA-256 with `--hash-verify`) → journal every step. Copy-keep never deletes; move removes a source only after its destination verifies. |
| `organize-history` / `organize-show --plan-id N` | Plan history and counters from the audit journal. |
| `organize-undo --operation-id N [--approve-delete]` | Move: copy the destination back to (now-free) source path. Copy-keep: delete the created copy, only with `--approve-delete`. Refuses if the file changed since execution. |
| `organize-cancel --plan-id N` | Cancel a draft/approved plan. |

**Safety properties, enforced in code and tests:** no approval → no execution ·
no overwrite of any existing file (plan-time and apply-time checks) · no
source removal before destination verification · symlinks are never followed ·
destinations must stay inside the approved target root · interrupted
operations are marked, never assumed complete · full journal in
`organization_events` · failed runs never hide partial work.

**Scope of V2 today (v2.0.0, honest):** one rule (`by-category`), local
moves/copies only, offline HTML preview, no recommendation engine, no native
app. On-device execution has **not** been validated (only the Linux host) —
see [Validation status](#validation-status). Roadmap: `docs/V2_ROADMAP.md`.

---

## Command reference

Actual `python3 storage_audit.py --help` output (v2.0.0):

```
usage: storage_audit.py [-h] [--version] [--db DB] [--output-dir OUTPUT_DIR]
                        [--verbose] [--quiet]
                        COMMAND ...

Android Storage Audit — read-only inventory of accessible shared internal
storage (Termux), plus an OPT-IN V2 organization engine. The scan never
modifies, moves, renames or deletes source files. V2 'organize-*' commands
change files ONLY after an explicit, logged approval, and never overwrite
existing files. No network access either way.

positional arguments:
  COMMAND
    check               Verify environment and permissions
    scan                Run the read-only inventory scan
    report              (Re)build the HTML report from an existing scan — no
                        rescanning
    list-runs           List past scan runs
    show-run            Show counters for one run id
    organize-plan       V2: build a DRAFT organization plan from a scan
    organize-preview    V2: write an offline HTML preview of a plan
    organize-approve    V2: approve a draft plan (required before apply)
    organize-apply      V2: execute an APPROVED plan
    organize-history    V2: list organization plans
    organize-show       V2: show one organization plan
    organize-undo       V2: undo one completed operation
    organize-cancel     V2: cancel a draft/approved plan

options:
  -h, --help            show this help message and exit
  --version             show program's version number and exit
  --db DB               SQLite database path (default: XDG_DATA_HOME/android-
                        storage-audit/storage_audit.sqlite3 or
                        ~/.local/share/android-storage-
                        audit/storage_audit.sqlite3)
  --output-dir OUTPUT_DIR
                        Output directory for reports (default: state dir)
  --verbose             Debug logging (includes full paths in the log file)
  --quiet               Only errors on the console

Environment variables: STORAGE_AUDIT_ROOT (default scan root), XDG_DATA_HOME
(state directory base).
```

(`bash run_audit.sh …` passes its arguments through to this exact CLI.)


| Command | What it does |
|---|---|
| `check` | Environment and permission preflight; exits non-zero with guidance if the tool cannot scan. |
| `scan [--root DIR] [--batch-size N]` | Run the read-only inventory. `--root` overrides the default root (rarely needed). `--i-know-this-is-broad` is required for `/` or your home directory. |
| `report [--latest \| --scan-id N]` | (Re)build the HTML report from an existing run. Never rescans. |
| `list-runs` | List all scan runs and their statuses. |
| `show-run N` | Print counters for one run. |
| `organize-plan/preview/approve/apply/history/show/undo/cancel` | V2 organization engine — see above and `--help` per command. |
| `storage-audit …` | Same CLI when installed with `pip install .` |

Exit codes: `0` success · `1` internal error (e.g. report build failed) ·
`2` usage/preflight error · `3` scan incomplete (gaps or cancellation; data
is still recorded) · `4` `check` found interrupted runs needing recovery
(scan remains usable).

Output-location override: `--output-dir DIR`. Database override:
`--db PATH`. Default root override: `--root` or `STORAGE_AUDIT_ROOT`.

---

## What gets collected

For **every entry** the scanner can see (files, directories, symlinks, and
other special files):

- full path, relative path, name, normalized name (Unicode NFKC + casefold);
- entry kind; size in bytes (files only); modification time;
- extension, compound extension (`.tar.gz`), filename-derived category and
  MIME type;
- hidden flag; symlink flag (symlinks are recorded, **never followed**);
- per-entry stat status (observed / failed) — a failure is recorded, never
  silently skipped.

Directory aggregates are computed recursively (file bytes and counts per
directory subtree). Aggregates are never used to "correct" file-level
counts — they are derived from them.

The scan **does not read file contents**. Classification is from filenames
only. No hashing, no indexing, no OCR, no previews.

---

## Limitations — important

Read these before drawing conclusions from a report:

1. **Shared storage only.** App-private data, other apps' sandboxes, and
   root-only areas are invisible to this tool. Absence of a file from the
   inventory means "not visible to the scan", not "does not exist".
2. **Coverage is reported as counters, not percentages-of-device.** The
   report shows what was enumerated, what failed, and why — never a claim of
   100% device coverage.
3. **Symlinks are recorded, not followed.** Looping or escaping paths are
   therefore impossible; broken links are reported as issues.
4. **Modified time ≠ creation time.** `ctime` is Unix inode-change time,
   never "date created on Android". Android does not expose a reliable
   per-file creation time through this API.
5. **Sparse files** occupy more logical size than disk space. The report
   labels this explicitly instead of comparing raw bytes to "used space".
6. **Android 11+ scoped storage** restricts what other apps can see; Termux
   sees what Termux's grant covers. Some directories may be unreadable even
   with permission — those appear under Scan Issues, never silently.
7. **Filesystems report size in logical bytes.** What Android counts as
   "used storage" includes reserved areas and other volumes this tool
   cannot see; ratios against OS-reported usage are therefore labelled, not
   presented as exact.
8. **Same-size files are flagged as candidates, not proof of duplicates.**
   No hashing is performed in V1.
9. **Permission-denied directories** count as issues and do not fail the
   scan — the rest of the tree is still inventoried and the run is marked
   `completed_with_gaps`, not `completed`.

---

## Privacy

- **The report contains your filenames.** That is the point of an inventory.
  Keep the report directory private; do not email it, upload it, or commit
  it to a public repository.
- No network access is used or needed — the tool performs none. There is no
  telemetry, no analytics, no update check, no crash reporting.
- Exports and the database are written with owner-only readability where the
  platform allows; they are never written inside your scanned tree (the tool
  refuses and excludes output paths located under the scan root).
- Filenames are escaped everywhere they are rendered (HTML, CSV, JSON,
  terminal, JS). A hostile filename cannot inject markup or escape the
  sandboxed report.

---

## Validation status

**V1 implementation complete and device-exercised once; V2 host-validated; on-device validation pending.**

The development host ran the full suite: **136 tests pass**. On 2026-11-23 the
author ran V1 **on a physical Android 15 / Termux device**: 8,584 files +
165 directories inventoried in 6.5 s (42.36 GiB logical, status
`completed_with_gaps`); the report was generated on-device; two
`Android/data` and `Android/obb` directories (scoped-storage FUSE mounts) were
not crossed — by the mount-boundary policy. The v1.0.1 taxonomy fix from that
finding has **not yet been re-validated on the phone**. **No V2 organization
command has been executed on the phone** — only on the Linux dev host with
synthetic fixtures. In particular, the following are *expected but not device-verified*:

- `termux-setup-storage` flow and the exact default root layout on your
  Android version;
- real-world permission behavior (scoped storage) on your ROM;
- performance on phone flash storage vs. the Linux dev host
  (see `docs/PERFORMANCE.md` — numbers are from the dev host and are **not**
  extrapolated to phones);
- the Termux context gate on a real Termux installation
  (`check` detects Termux via environment hints; on Linux it runs in an
  explicitly-labelled development mode).

Please treat the first run on your phone as the device acceptance pass:
run `check`, scan, open the report, and confirm the counters look sane for
known folders (e.g. `DCIM`).

---

## Documentation

- [`docs/RECONNAISSANCE.md`](docs/RECONNAISSANCE.md) — environment and API
  reconnaissance that shaped the design.
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — 22 recorded design decisions
  (containment, symlink policy, status model, metrics definitions, …).
- [`docs/TRACEABILITY_MASTER.md`](docs/TRACEABILITY_MASTER.md) — requirement
  traceability for the master specification.
- [`docs/TRACEABILITY_SUPPLEMENT.md`](docs/TRACEABILITY_SUPPLEMENT.md) —
  requirement traceability for the validation supplement.
- [`docs/SECURITY_READONLY_AUDIT.md`](docs/SECURITY_READONLY_AUDIT.md) —
  read-only audit of every file-write call site and safety control.
- [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md) — measured performance on the
  development host (never extrapolated to phones).
- [`docs/GAP_REGISTER.md`](docs/GAP_REGISTER.md) — severity-tagged register
  of known limitations and open gaps.
- [`docs/FINAL_AUDIT.md`](docs/FINAL_AUDIT.md) — the final self-audit
  against both specifications.
- [`docs/TEST_EVIDENCE.md`](docs/TEST_EVIDENCE.md) — test commands and
  counts. [`CHANGELOG.md`](CHANGELOG.md) — version history.

V2 engineering documentation:

- [`docs/V2_PRD.md`](docs/V2_PRD.md) — v2 product requirements (scope,
  safety contract, non-goals). [`docs/V2_ROADMAP.md`](docs/V2_ROADMAP.md) —
  milestone roadmap. [`docs/V2_ARCHITECTURE.md`](docs/V2_ARCHITECTURE.md) —
  subsystem design. [`docs/V2_DATA_MODEL.md`](docs/V2_DATA_MODEL.md) —
  schema v2. [`docs/V2_SECURITY_MODEL.md`](docs/V2_SECURITY_MODEL.md) +
  [`docs/V2_OPERATION_SAFETY.md`](docs/V2_OPERATION_SAFETY.md) — security
  invariants. [`docs/V2_ORGANIZATION_STATE_MACHINE.md`](docs/V2_ORGANIZATION_STATE_MACHINE.md)
  — plan/operation state machines. [`docs/V2_FILE_OPERATION_FAILURE_MATRIX.md`](docs/V2_FILE_OPERATION_FAILURE_MATRIX.md)
  — every failure mode and its handling. [`docs/V2_ACCEPTANCE_CRITERIA.md`](docs/V2_ACCEPTANCE_CRITERIA.md)
  — release gates. [`docs/V2_DESIGN_SYSTEM.md`](docs/V2_DESIGN_SYSTEM.md) —
  preview visual design. [`docs/V2_TEST_STRATEGY.md`](docs/V2_TEST_STRATEGY.md)
  — test strategy. [`docs/V2_UI_VALIDATION.md`](docs/V2_UI_VALIDATION.md) +
  [`docs/V2_PERFORMANCE_VALIDATION.md`](docs/V2_PERFORMANCE_VALIDATION.md) +
  [`docs/V2_RECOMMENDATION_VALIDATION.md`](docs/V2_RECOMMENDATION_VALIDATION.md)
  — validation evidence and limits. [`docs/V2_ROADMAP.md`](docs/V2_ROADMAP.md).
- Cross-cutting: [`docs/COMPREHENSIVE_GAP_REGISTER.md`](docs/COMPREHENSIVE_GAP_REGISTER.md),
  [`docs/FINAL_ACCEPTANCE_MATRIX.md`](docs/FINAL_ACCEPTANCE_MATRIX.md),
  [`docs/PUBLICATION_PRIVACY_AUDIT.md`](docs/PUBLICATION_PRIVACY_AUDIT.md),
  [`docs/DATABASE_INTEGRITY_AUDIT.md`](docs/DATABASE_INTEGRITY_AUDIT.md),
  [`docs/PATH_SECURITY_VALIDATION.md`](docs/PATH_SECURITY_VALIDATION.md),
  [`docs/REPORT_EXPORT_RECONCILIATION.md`](docs/REPORT_EXPORT_RECONCILIATION.md),
  [`docs/SCAN_STATE_MACHINE.md`](docs/SCAN_STATE_MACHINE.md),
  [`docs/V1_ANDROID_FORENSIC_AUDIT.md`](docs/V1_ANDROID_FORENSIC_AUDIT.md).

## Repository

Public source, distributed under the MIT license:
**[github.com/Manash07Bhoi/StorageLens](https://github.com/Manash07Bhoi/StorageLens)**

Clone and use directly:

```sh
git clone https://github.com/Manash07Bhoi/StorageLens.git
cd StorageLens
bash run_audit.sh check
```

## Status & validation

**V2.0.0 source released (public), host-validated; on-device acceptance is
the user's next step.** The code is fully tested on the development host
(Linux x86_64, 136 tests). One V1 run was executed on the owner's Android 15
phone — by the owner, not by the development agent; its artifacts are private
user data and are not in this repository. The first V2 on-device run is the
owner's acceptance step — see
[Validation status](#validation-status) and
[docs/FINAL_AUDIT.md](docs/FINAL_AUDIT.md).

## What this tool is NOT

- Not a phone cleaner, not a duplicate remover, not a backup tool.
- Not a forensic image and not "100% of device storage" — it inventories
  the *accessible shared-storage tree* only.
- Not a background service — it runs when you run it.
- Not a cloud uploader — there is no network code anywhere in the project.
- V2.0.0 is not a cleaner and not "smart": it organizes by category only,
  with explicit approval, and never deletes (copy-keep default).

## Roadmap

Shipped: **v1.0.1** (V1 correctness fixes) · **v2.0.0** (V2 planning-first
organization engine, M1) — see [CHANGELOG.md](CHANGELOG.md).

- **M2:** on-device acceptance run + device benchmarks; compare scan runs;
  richer rule plugins.
- **M3:** smarter previews (grouping/sort), AT audit, saved rule sets.
- Future: cloud provider adapters with separate consent and credentials —
  NOT started.

See `docs/V2_ROADMAP.md` and `docs/` for the full audit trail.

## Reporting issues

Open a regular issue for bugs and documentation errors. For anything
security-sensitive, do **not** attach scan reports or databases (they
contain personal filenames) — describe the class of problem instead.

## License

MIT — see [LICENSE](LICENSE). The license covers the tool's source code only. It does **not** apply to any report, export or database generated by the tool: those contain your personal filesystem inventory and belong to you.

MIT (see `LICENSE` semantics if present in your distribution copy; the
packaging metadata states MIT).
