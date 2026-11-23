# Security & Read-Only Audit

**Audit date:** 2026-11-23 · **Auditor:** development agent (self-audit) ·
**Scope:** complete source tree of Android Storage Audit V1
(`storage_audit/`, `storage_audit.py`, `run_audit.sh`, `tools/benchmark.py`).

**Verdict: PASS (with documented limitations).** The tool performs no
writes to the scanned tree, opens no sockets, and every externally
observable effect is limited to its state/output directories. Two
subprocess/exec calls exist; both are enumerated below, argument lists are
fixed, and neither takes user input.

---

## 1. Method

1. Enumerated every write-capable call site with source grep
   (`open(..., "w"/"a"/"x")`, `os.remove`, `os.makedirs`, `os.replace`,
   `shutil.copy*`, `sqlite3.connect`, `subprocess`, network modules).
2. Traced each into its call chain to classify the destination.
3. Verified path-containment tests in `tests/test_safety.py` and
   `tests/test_scanner.py` (output-under-root excluded; output == root
   refused; root-inside-output refused).
4. Verified export reconciliation and escaping behavior in
   `tests/test_exporters.py`, `tests/test_report.py`.
5. Confirmed there is no code path that opens a path inside the scanned
   tree for writing.

## 2. Write call-site inventory

Every write-capable site in the codebase, classified:

| # | Location | Operation | Destination | Verdict |
|---|---|---|---|---|
| 1 | `storage_audit/environment.py` (~L72) | create + delete `.write_probe` | **state dir** (not the scan root) | OK — preflight writability probe |
| 2 | `storage_audit/scanner.py` (~L76-80) | `makedirs` output/reports/logs dirs | output dir (default outside scan root) | OK — output location validated beforehand |
| 3 | `storage_audit/scanner.py` (~L103) | `makedirs` DB parent dir | DB directory | OK |
| 4 | `storage_audit/database.py` (~L203) | `makedirs` DB parent | DB directory | OK |
| 5 | `storage_audit/exporters.py` (`_write_text_atomic`) | write temp file + `os.replace` | exports dir (inside report dir) | OK — atomic, same dir |
| 6 | `storage_audit/exporters.py` (~L289) | `os.remove(single_path)` | `directory_tree.txt` inside **exports dir** only, when tree exceeds chunk limits | OK — scoped to exports dir; documented |
| 7 | `storage_audit/report_builder.py` (`_write_atomic`, ~L583) | write temp + `os.replace` | report dir | OK — atomic |
| 8 | `storage_audit/report_builder.py` (~L441) | write `data/inventory_NNN.js` | report dir `data/` | OK — escaped per §5 |
| 9 | `storage_audit/report_builder.py` (~L929) | `shutil.copyfile` report.css/js | report dir | OK — copies from package templates only |
| 10 | `storage_audit/logging_config.py` | `makedirs` + log file | state dir `logs/` | OK |
| 11 | SQLite (`sqlite3.connect`) | DML/DDL on the database file | DB file path | OK — see §5 |
| 12 | `tools/benchmark.py` | fixture files | temp dir it creates and deletes | OK — never the scan root |

**No other write-capable calls exist.** In particular:

- No `os.remove`/`os.unlink`/`shutil.rmtree` targets anything inside the
  scanned tree.
- No `open(path, "w"|"a"|"x"|"r+")` has a path derived from a scanned
  entry. Scanned paths flow only into `os.scandir`, `os.stat`/`lstat`,
  `os.readlink`, and the DB.
- The scan itself opens **zero** files for reading or writing. It reads
  metadata only (`DirEntry` attributes, `os.lstat`, `os.statvfs`).

### Output-under-scan-root policy (containment)

- Output == scan root → run aborts with exit code 2.
- Scan root inside output dir → run aborts.
- Output inside scan root → allowed **only** with the output subtree
  excluded from traversal and the exclusion recorded on the run
  (`exclusions_json`), and the database files (+ `-wal`/`-shm`/`-journal`)
  excluded exactly. (`tests/test_scanner.py::TestDatabaseInsideRoot`
  verifies the DB is never self-inventoried.)
- Symlinks are never followed, so a hostile symlink cannot redirect output
  or traversal outside the root.

## 3. Network & execution audit

| Check | Result |
|---|---|
| `import socket/urllib/http/requests/ftplib/smtplib` | **None** |
| `urlopen`, `.connect(` on sockets, `httplib` | **None** (only `sqlite3.connect`, local file) |
| Subprocess / exec | ONE: `filesystem.py::_try_getprop` invokes Android's `getprop` with a **fixed, hardcoded** property list (`ro.build.version.release`, `ro.build.version.sdk`), `timeout=2`, best-effort, read-only, failures tolerated (`unavailable`). Arguments are never derived from user input. Runs only where `getprop` exists (Android). |
| Shell string execution (`os.system`, `os.popen`, `shell=True`) | **None** |
| Environment variables honored | `STORAGE_AUDIT_ROOT`, `XDG_DATA_HOME` only |
| Telemetry / analytics / crash upload | **None** — there is no such code |

## 4. Output-content safety (injection resistance)

| Output | Control | Test |
|---|---|---|
| HTML pages | All dynamic text through `html.escape`-based `esc()`; C0/C1 control chars rendered as entities; template structure fixed | `tests/test_report.py` (escaping, `<script>` filenames on every page) |
| Embedded inventory JSON | `<`, `>`, `&`, U+2028, U+2029 all `\uXXXX`-escaped — cannot terminate the `<script>` block or form entities | `storage_audit/report_builder.py::_script_safe_json`; report tests |
| `report.js` | Placeholder-free literals; verified by `node --check` in tests | `tests/test_report.py` |
| CSV exports | Formula-injection neutralization: cells starting with `=`, `+`, `-`, `@` (and tab/CR variants) are `'`-prefixed; numeric values pass through untouched; UTF-8 **BOM** for Excel compatibility | `tests/test_exporters.py` |
| JSONL | `scan_id` retained; one JSON object per line; raw filenames stay raw **inside** JSON strings (valid), never interpreted | `tests/test_exporters.py` |
| Tree text | Control chars escaped; deterministic chunking with an index file and total-line check | `tests/test_exporters.py` |
| Terminal output | Filenames printed after control-char sanitization | `scanner.py` progress rendering |
| Markdown (`summary.md`) | Newlines/backticks in paths kept literal; no inline HTML interpretation beyond documented markers | `tests/test_exporters.py` |
| SQLite | **100% parameterized queries.** The only interpolated SQL fragments are: (a) `update_counters`/`transition_run` column lists — now bound to the `_TRANSITION_COLUMNS`/`allowed` whitelists (hardened 2026-11-23); (b) `latest_run` IN-list placeholders (count only, values bound). No user data is ever interpolated. | `tests/test_database.py` |

## 5. Database integrity controls

- WAL journaling, `synchronous=FULL`, `foreign_keys=ON`, busy timeout 30 s.
- Forward-only migrations (`schema_migrations`); newer-than-supported schema
  versions are refused, never downgraded.
- Status transitions validated (`_ALLOWED_TRANSITIONS`); terminal runs are
  immutable (cannot move to any other status); completed runs cannot be
  rewritten to a different terminal status.
- `integrity_check` runs at scan finalization; failure downgrades the run
  to `failed`, never to `completed`.
- Stale `running` rows from dead PIDs are recovered to
  `interrupted_or_recovered` (never shown as complete); alive PIDs are
  untouched; undeterminable liveness leaves the row and logs a warning.
- `entries.relative_path` is `UNIQUE(scan_id, relative_path)`; FK from
  every child table to `scan_runs(id)` with `ON DELETE RESTRICT`.

## 6. Privacy posture

- The report/exports contain **user filenames** — expected for an
  inventory, and the tool says so on the report footer and in the README.
- No filename is ever transmitted anywhere; there is no network code.
- Reports are written with default umask permissions under the user's own
  state directory; the user is instructed to keep them private.
- `--verbose` logs full paths to the local log file (documented);
  non-verbose logging uses counts and basenames.

## 7. Known limitations of this audit

1. Static (source) audit + dynamic test evidence; no formal fuzzing, no
   penetration testing of the report in a hostile browser, no sandbox
   escape analysis of Android itself.
2. Self-audit by the same agent that wrote the code; independent review is
   still valuable before wide distribution.
3. `getprop` invocation is exercised only on Android; on Linux it is never
   called (tool absent) and the code path is otherwise identical.
4. File-locking behavior on contended SQLite files (hostile third-party
   processes holding locks) is handled with a bounded timeout and clear
   errors, not proven deadlock-free.

## 8. Evidence

- `tests/test_safety.py` — containment, exclusion checker, root validation.
- `tests/test_scanner.py` — read-only source-tree snapshot before/after
  scans; output-inside-root exclusion; DB-inside-root exclusion.
- `tests/test_exporters.py`, `tests/test_report.py` — escaping, offline
  (no external URL), injection resistance.
- `tests/test_database.py` — immutability, transitions, integrity,
  migration policy, stale-PID recovery.
- Full suite: `python3 -m unittest discover -s tests -v` → **157 tests OK**
  (2026-11-23).
