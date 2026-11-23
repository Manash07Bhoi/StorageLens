# V1 Android 15 — Forensic Audit of the First Real-Device Scan

**Evidence source:** user-provided screenshots (2026-11-23 11:07–11:08 IST) and the
report archive uploaded by the user and secured by the agent (SHA-256 recorded
privately; the archive is private user data and is not reproduced here).
**Redaction:** no personal filenames or paths appear in this document. Only the
two root-level system directories involved in the issues are named (they are
public Android system paths, not user data).

## Device environment (as reported by the tool itself)
| Field | Value |
|---|---|
| Android release / SDK | 15 / 35 |
| Termux | 0.119.0-beta.3 |
| Python | 3.14.10 (min 3.8 OK) |
| Platform | Linux 4.19.236+ aarch64 |
| SQLite | 3.54.1 |
| Shared root | `/storage/emulated/0` (resolved from `~/storage/shared`) |
| Volume | 106.01 GiB total · 64.21 GiB used · 41.80 GiB free |
| `termux-setup-storage` | "already exists" prompt → answered yes; storage link OK |

## The scan, exactly as recorded
Started 2026-11-23 11:07:22+05:30 · duration 6.48 s ·
**status `completed_with_gaps`** · files 8,584 · directories 165 · symlinks 0 ·
hidden 92 · zero-byte 135 · inventoried bytes **45,482,162,920 (42.36 GiB)** ·
issues 2 · skipped 2 · coverage complete: **no**.
Report build: success for run #1; 8,749 inventory rows; 18 static pages; exports
written beside it; report labelled `completed_with_gaps` / incomplete on every
page; 0 external references in any generated asset.

## Root-cause of the two issues — definitive
`exports/scan_issues.csv` contains exactly two rows (row ids 1 and 2), one per
skipped directory, and nothing else:

| Path | Detection | What it means on Android 15 |
|---|---|---|
| `Android/data` | `st_dev` differs from scan root | separate FUSE mount; scoped storage masks other apps' private data |
| `Android/obb` | `st_dev` differs from scan root | separate FUSE mount; APK expansion payloads |

- **The two issues and the two skipped entries are the same two objects** — not
  two groups, no arithmetic inflation, nothing hidden.
- These are the **expected, documented Android 11+ scoped-storage boundaries**.
  Termux cannot enumerate other apps' `Android/data` contents regardless of the
  tool; opting out is the correct, safe behavior.
- The scanner recorded both as directory entries with
  `skip_reason='mount_boundary'`, counted them in `directories` and
  `total_entries`, did NOT descend, and surfaced them under Scan Issues.
- **Defect found and fixed (wording):** the issue's `operation` was
  `containment`, producing the coverage note "Issues: 2 containment", which
  reads like a security rejection of root-escaping paths. The behavior was
  deliberately safe but the taxonomy was wrong. v1.0.1 emits
  `operation=mount_boundary` and reserves `containment` for
  `path_outside_root`. Wording of coverage notes was made precise
  (operation/code grouped). **Fix not yet validated on-device (NOT TESTED).**
- **No evidence of omitted readable user files.** The skipped subtrees are
  app-private/expansion areas that scoped storage hides from Termux anyway.
  This statement is bounded by what the scan recorded; it cannot prove a
  negative about hidden storage, and does not claim full coverage (no scan can).

## Reconciliation of every counter (independent, from the extracted archive)
| Check | Result |
|---|---|
| manifest.json SHA-256 + byte size of all 8 exports | PASS (8/8) |
| files.csv rows = 8,584 = manifest `files_inventoried` | PASS |
| directories.csv rows = 165 = manifest `directories` | PASS |
| entries.jsonl rows = 8,749 = manifest `total_entries`; scan_id set = {1} | PASS |
| Σ files.csv `size_bytes` = 45,482,162,920 = manifest `inventoried_file_bytes` | PASS |
| file_types.csv category rows: 11 rows, Σ files = 8,584, Σ bytes = 45,482,162,920 | PASS |
| extension rows: 36, Σ files = 8,584 | PASS |
| directory_tree.txt lines = 8,749; hidden dirs present; skipped subtrees absent (correct) | PASS |
| 18 static pages: 17×501 + 85 `<tr>` − 18 header rows = 8,584 files | PASS |
| `index.html`: INCOMPLETE banner present; status token present; **0 external URLs in any of 31 pages** | PASS |
| hidden.html top-25 caps are labelled ("Largest hidden directories/files (top 25)") | PASS |
| exports README present; manifest legend accurate; UTF-8 BOM + formula-injection note | PASS |
| Abort/crash markers | none |

**Verdict:** the artifact is internally consistent. The scan honestly reports
`completed_with_gaps`; exports, report and DB-derived counters agree; the only
defect found was the issue-category wording, fixed in v1.0.1, pending
re-validation on the phone (`git pull && python storage_audit.py scan`).

## Impact statement
Coverage of the *accessible shared-storage tree* is 8,749 inventoried entries
(100% of what the tool could see). Two directories (`Android/data`,
`Android/obb`) were intentionally not crossed — a policy boundary, not a bug
and not a data-loss event. Volume figures (64.21 GiB used) exceed inventoried
bytes (42.36 GiB logical) — expected: app-private data, filesystem overhead,
and sparse allocation are outside the inventory by design.

## Remaining on-device actions (user-run; agent cannot do these)
1. `git -C ~/StorageLens pull` then `python storage_audit.py scan` — new run
   records precise `mount_boundary` issues (v1.0.1 wording).
2. `python storage_audit.py report --latest` — fresh report from the new run.
3. Optional V2 dry-run on a small target folder: see ANDROID_TERMUX_GUIDE.
