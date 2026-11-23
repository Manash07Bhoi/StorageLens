# V2 Security Model — Organization Engine

**Trust boundary:** the user's device; the user is the approver. StorageLens
never self-authorizes. Network is out of scope entirely.

## Assets
Personal files (content), personal metadata (names/paths), the SQLite DB
(inventory + history), the generated previews/reports.

## Threats → controls
| Threat | Control | Evidence |
|---|---|---|
| Tool deletes/moves files without consent | Approval gate; move needs `--acknowledge-source-removal`; copy-keep default | gating tests; CLI smoke |
| Overwriting an existing file | plan-time reservation + execution-time `lexists` re-check | sentinel test |
| TOCTOU between plan and apply | full re-validation at apply; dest re-check; source existence/type re-check | TOCTOU design (V2_OPERATION_SAFETY.md) |
| Symlink escape / following | refused at plan and apply; `os.path.islink` before any read/copy; `copystat(follow_symlinks=False)` | symlink tests |
| Path traversal in stored paths | segment sanitizer drops `..`; dest realpath containment invariant | hostile-path test |
| Silent corruption | size verification always; SHA-256 optional (`--hash-verify`); fsync before verify | corruption test |
| Disk full mid-run | pre-check (payload + 64 MiB) refuses early; write errors → op failed, source intact | mocked space test |
| Interrupted operation treated as done | in_progress → interrupted reconciliation; undo refuses non-completed ops | reconcile test; undo gates |
| Private data leaked via repo | .gitignore + publication audit (PUBLICATION_PRIVACY_AUDIT.md); fixtures synthetic | pre-push scans |
| Injection via preview HTML | full escaping + JSON `\uXXXX`; 0 external refs | preview audit |
| Executor bugs deleting wrong file | source path = DB-recorded absolute path; never derived from dest | code review |

## Permissions
No new Android permissions. V2 runs wherever V1 runs. Moves within shared
storage require the same `~/storage/shared` access. Root never required.

## Explicitly not defended (documented)
- A user approving a malicious plan they did not read. The preview is the
  control; approval is explicit and logged with timestamp.
- Files modified by other apps during apply: detected only via size/mtime
  comparison when provided (V2 re-checks destination non-existence; content
  races during copy are detected by size/hash verification after fsync).
- Physical theft/unlocked device: OS responsibility.
- Git-history exposure incident from 2026-11-23 — see PUBLICATION_PRIVACY_AUDIT.md.
