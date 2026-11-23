# Privacy & Safety

What Android Storage Audit reads, what it never touches, and how to remove
what it generates.

## What the tool reads

- **Metadata only**: filename, relative path, size (bytes), mtime (Unix
  epoch), extension, entry kind, hidden flag, symlink target existence.
  Obtained via `os.scandir`/`os.lstat`. File **contents are never opened**.
- The Android volume statistics via `os.statvfs` (total/free/used bytes of
  the volume holding the root).
- On Android only: `getprop` for build release/SDK strings — a fixed,
  hardcoded property list, read-only.

## What the tool never does

- **Never writes, modifies, moves, renames, deletes, copies or compresses
  any source file.** The scanned tree is treated as read-only, always.
  Verified by tests that snapshot the fixture tree before/after scanning.
- **Never reads file contents** — no hashing, no previews, no indexing,
  no OCR, no "open to guess type". Classification is from the filename.
- **Never follows symlinks** — recorded as entries, targets never touched.
- **No network access** — no sockets, no HTTP, no DNS, no telemetry, no
  update check, no crash reporting. Airplane mode is fine.
- **No root** — never requests, checks for, or uses superuser privileges.
- **No cleanup, no delete, no "junk finder" action buttons.** The report
  is information only; it contains no control that mutates anything.

## Where data goes

Generated artifacts (all under `~/.local/share/android-storage-audit/` by
default, override with `--output-dir` / `--db` / `XDG_DATA_HOME`):

| Artifact | Contains |
|---|---|
| `storage_audit.sqlite3` | All scan runs, every inventoried entry (paths!), issues, stats, report build log |
| `reports/run_<id>_<ts>/index.html` + detail pages | Dashboard and paginated tables of your filenames |
| `…/exports/entries.jsonl`, `files.csv`, `directories.csv`, … | Machine-readable copies of the same |
| `…/exports/manifest.json` | SHA-256 of each export |
| `logs/storage_audit.log` | Operational log (counts; full paths only with `--verbose`) |

**These artifacts are sensitive:** they catalog your filenames, which can
reveal medical documents, financial files, photos, location names, account
names, and personal projects.

## How to remove generated data

The tool has no delete command, by design. Removal is a manual, explicit
user action:

```sh
# Stop any running scan first (Ctrl+C).
cat ~/.local/share/android-storage-audit/storage_audit.sqlite3*   # inspect first, if you wish
rm -rf ~/.local/share/android-storage-audit
```

That command permanently deletes **only** the tool's own state/output.
It never touches your files, and it is the only removal path — there is no
hidden or automatic cleanup. Inspect before deleting if unsure.

## Network behavior

None. The report is fully static; the search page inlines or chunks its
data locally; the manifest uses SHA-256 computed locally. Opening the
report makes zero network requests.

## Sensitive-content advice

- Keep the state directory out of shared storage if you don't want other
  apps/people to read the inventory: the default (`~/.local/share/...`,
  inside the Termux private area) is already private to Termux.
- If you copy a report into shared storage for easier access or to transfer
  to a PC, remember other apps with storage permission can read it, and
  delete the copy when done.
- Do not commit reports/databases to Git; this project's `.gitignore`
  excludes them, and the audit evidence (`docs/SECURITY_READONLY_AUDIT.md`)
  documents that no scan data is included in the repository.

## Consent model

Running `scan` is your explicit consent to inventory the tree it prints in
the startup banner. The scanner prints the canonical root and the exact
inclusions/exclusions before scanning. If you don't recognize the root,
stop (Ctrl+C) — nothing has been written to shared storage.
