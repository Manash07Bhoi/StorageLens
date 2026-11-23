# Gap Register — Android Storage Audit V1

Severity: **critical** (blocks V1 claim) · **high** (blocks a formal
acceptance gate) · **medium** (functional gap or verification debt) ·
**low** (polish/documentation).

Register maintained per Supplement §13.15. "Resolved" items list their fix
and verification. No item below is hidden: if the tool cannot do something,
it is listed here.

## Summary

| Severity | Open | Resolved |
|---|---|---|
| Critical | 0 | 1 |
| High | 1* | 3 |
| Medium | 3 | 3 |
| Low | 5 | 6 |

\* G-001 is a **blocked validation**, not a code defect: V1 was built in a
remote Linux workspace and has not been executed on the user's phone. The
supplement (§13.16) explicitly permits the wording "V1 implementation
complete; on-device validation pending" in this case, and Gate A/Gate G
remain *blocked with precise reason*, never *passed*.

**No unresolved critical defects. No unresolved high-severity code defects.**
G-001 is a blocked environmental validation (the V1 code is tested on the
dev host; the phone run does not exist yet), not a defect in the shipped
code.

---

## Open gaps

### G-001 — No on-device Android/Termux validation
- **Severity:** high (environmental) — gates A and G partially blocked.
- **Impact:** Root resolution, scoped-storage behavior, battery-kill
  recovery, and real-flash performance on the user's device are unknown.
  The report may surface permission misses that only appear on-device
  (e.g. `Android/data` restrictions).
- **Mitigation:** Exact handoff in `README.md` §5–§6 and
  `docs/ANDROID_TERMUX_GUIDE.md`; `check` preflight on the device reports
  what it sees and refuses to proceed when the root is unavailable;
  `show-run` and `scan_issues.html` expose what could not be read.
- **Resolution:** user's first on-device run + feedback; fold results into
  `docs/PERFORMANCE.md` and this register.

### G-005 — SQLite locked/busy and disk-full not fault-injected
- **Severity:** medium.
- **Impact:** A scan racing a hostile process holding the DB, or a
  near-full volume mid-transaction, is handled by WAL + 30 s busy timeout +
  `synchronous=FULL` + the integrity gate, but not by an automated test.
  Behavior on disk-full is "run marked `failed`, data preserved" by code
  path, unproven by injection.
- **Resolution path (V1.0.x):** temp-dir-fixture + `sqlite3` busy handler
  test; ulimit-wrapped disk-full test on Linux.

### G-006 — Performance numbers are dev-host only
- **Severity:** medium.
- **Impact:** `docs/PERFORMANCE.md` figures (18k entries/s, 0.65 s, 69.6
  MiB) describe Linux x86_64 with warm cache. They are meaningless as a
  guarantee for a mid-range phone over flash storage.
- **Mitigation:** methodology documented; on-device measurement procedure
  included; numbers explicitly not extrapolated.
- **Resolution:** after G-001, record device results in PERFORMANCE.md.

### G-007 — No browser automation for the report
- **Severity:** medium.
- **Impact:** Mobile layout, focus order, JS-disabled behavior and reduced
  motion were verified by markup/CSS review and `node --check`, not by a
  headless browser across viewports. A rendering defect visible only in a
  specific Android WebView could slip through.
- **Mitigation:** noscript fallback linking static pages; all critical
  content reachable without JS; tests assert every page parses and every
  link resolves.
- **Resolution path (V1.0.x):** Playwright/WebKit smoke script kept out of
  the runtime dependency set (dev-only tool).

### G-002 — (RESOLVED) Per-entry timestamp provenance
`entries.timestamp_status` and `birthtime_status` (observed/unavailable/failed/
not_applicable) are in the v1 schema and populated by the traversal; birth time
is `unavailable` on platforms without btime, never fabricated.

### G-003 — (RESOLVED) Device identity stored; inode deliberately omitted
`entries.device_id` (st_dev) is stored per entry and drives the mount-boundary
guard. `st_ino` is deliberately NOT stored — it is not stable across runs and
adds no V1 value; hard-link physical-block overcounting is documented in
LIMITATIONS.md.

### G-004 — No interrupted-scan resume
- **Severity:** low (explicit design decision).
- **Impact:** After force-kill, the user reruns `scan` from scratch.
  Documented plainly in LIMITATIONS.md; no silent partial-append behavior
  exists anywhere.
- **Resolution path (V1.1, if user wants it):** idempotent directory-checkpoint
  resume, tested for duplicate prevention.

### G-007a — Client-side result count has no automated browser assertion
- **Severity:** low.
- **Impact:** `#inv-count` rendering logic is vanilla JS verified only by
  syntax check; the integer it shows is computed correctly as written, but
  not executed in a browser in CI.
- **Resolution path:** fold into G-007.

### G-008 — No standalone `REPORT_GUIDE.md`
- **Severity:** low (master §15 lists it under docs; content delivered
  elsewhere).
- **Where the content lives:** `README.md` (open/copy/privacy),
  `exports/README.md` (generated per report), `summary.md`,
  `methodology.html` (definitions), `docs/ARCHITECTURE.md` (pagination/tree
  strategy).
- **Resolution (V1.0.x):** split into `docs/REPORT_GUIDE.md` if desired —
  pure documentation move.

### G-011 — Extension-vs-platform MIME disagreement channel undefined
- **Severity:** low.
- **Impact:** The supplement requires representing MIME disagreement rather
  than overwriting. V1 never reads platform MIME (it would require opening
  files or extra OS calls), so there is nothing to disagree with; all MIME
  values are filename-derived and labelled as such. Documented in
  LIMITATIONS.md and methodology.
- **Resolution:** none planned; behavior is intentional.

### G-012 — `size_status` tri-state hygiene
- **Severity:** low.
- **Impact:** Filesystem writer emits `'observed' | 'failed' |
  'not_applicable'`; analytics queries include `'unavailable'` as a
  defensive value never produced by the writer. Harmless, slightly untidy.
- **Resolution (V1.0.x):** align to one enum via migration.

---

## Resolved during this build (with evidence)

### R-001 — `size_status='ok'` vs `'observed'` literal mismatch → 0 B inventoried (critical, fixed)
Caught by scanning the 1 GiB sparse fixture and reading actual counters.
Fix: all comparisons use `'observed'`. Verified: rescan reports 256.00 MiB
(sparse logical) and full-suite green.

### R-002 — Recursive directory count double-counting (high, fixed)
`recursive_dirs` was seeded with `direct_dirs` and then children were
added on top. Fix: seed 0. Verified: `test_analytics.py` recursive
expectations.

### R-003 — Embedded JSON breakout via hostile filename (high, fixed)
`</script>`/`<script>` sequences in names could terminate the inline
script block. Fix: `<`, `>`, `&`, U+2028/2029 all `\uXXXX`-escaped in
`_script_safe_json`. Verified: `test_report.py::test_script_in_filename_escaped_everywhere`.

### R-004 — Raw C0 control characters in filenames corrupted HTML (high, fixed)
Newline/tab names produced broken pages. Fix: `_ctrl_escape` in the HTML
escaper; control chars also escaped in tree/summary exports. Verified:
report suite green; manual render inspection.

### R-005 — Misleading "% of OS-reported used bytes" share (medium, fixed)
Sparse files made the ratio look absurd (242,726%). Fix: `share_note`
branches explain sparse files; OS-vs-inventoried distinction labelled in
Methodology.

### R-006 — JSONL dropped `scan_id` (medium, fixed)
Broke cross-export reconciliation. Fix: rows carry `scan_id`; `id` no
longer needed for that contract. Verified: reconciliation tests.

### R-007 — `unavailable_size_files` counted every row (medium, fixed)
Manifest showed 27 instead of 0. Fix: `IN ('unavailable','failed')`.
Verified: fresh fixture manifest reports 0.

### R-008 — `recursive_dirs`-like misreport in counters + `directory_stats` staleness (low, fixed)
`directory_stats` now fully recomputed per export/report
(`compute_directory_stats`), so stale rows cannot persist.

### R-009 — `transition_run` SQL column interpolation hardened (low→hardened)
Not exploitable (internal literals only); added `_TRANSITION_COLUMNS`
whitelist anyway (defense in depth). Suite green.

### R-010 — Markdown path display escaping broke inline code (low, fixed)
`/tmp/metric\_audit/phone` rendered raw backslashes. Fix: `md_code` used
inside code spans. Suite green.

### G-009 / R-011 — LICENSE holder provisional (low, resolved-with-note)
MIT license written with holder "Android Storage Audit contributors"
(matches pyproject `authors`). User may amend the copyright line; no legal
review was performed.

---

## Acceptance-gate status (Supplement §8)

| Gate | Status |
|---|---|
| A — Scope & environment | **PARTIAL** — device steps blocked (G-001); everything else tested |
| B — Read-only guarantee | **PASS (dev host)** — see `docs/SECURITY_READONLY_AUDIT.md` |
| C — Inventory correctness | **PASS (dev host)** |
| D — Persistence & recovery | **PASS (dev host)** |
| E — Analytics & exports | **PASS (dev host)** |
| F — Report quality | **PASS (dev host)**, mobile/a11y manual (G-007) |
| G — Documentation & handoff | **PASS (dev host)**; on-device instructions delivered, execution pending |

**Final wording (Supplement §13.16): "V1 implementation complete; on-device
validation pending."** Not declared production-ready for the phone until
the user completes Gate A/B on-device.
