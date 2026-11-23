# Android / Termux Guide

Exact steps to run Android Storage Audit on a real phone, what to expect,
and how to troubleshoot. The development and test host for V1 was **Linux
x86_64, not Android** — everything below marked *device step* has not yet
been executed on a physical phone (see `docs/GAP_REGISTER.md`).

## 1. Permission setup

```sh
# In Termux:
pkg update
pkg install python
termux-setup-storage
```

`termux-setup-storage` triggers the Android permission dialog for shared
storage. Tap **Allow**. Then verify:

```sh
ls ~/storage/shared
```

Expected: your shared folders (`DCIM`, `Download`, `Pictures`, …). If you see
`Permission denied`, an empty listing, or `No such file or directory`:

- open **Android Settings → Apps → Termux → Permissions → Files and media**
  (or "Photos and videos" / "Music and audio" on newer Androids) and grant
  access;
- re-run `termux-setup-storage`;
- if still empty, your ROM may restrict shared storage — record this and
  file it via `docs/GAP_REGISTER.md`; **do not** work around it with root.

## 2. Shared root resolution

The tool resolves the scan root in this order:

1. `--root PATH` on the command line;
2. `STORAGE_AUDIT_ROOT` environment variable;
3. `~/storage/shared` (the standard `termux-setup-storage` link).

The **canonical** (realpath) path is recorded in every run row
(`scan_runs.root_path`), along with the requested path. If nothing is
resolvable — the directory does not exist or cannot be listed — the run
aborts with exit code `2` and a message explaining how to fix it. **The tool
never silently falls back to a different directory.**

Label recorded on every run: `accessible shared-storage inventory`. This
means: what Termux can see, not the whole device.

## 3. Commands tested and environment used

**Tested environment:** Linux x86_64 (development container), Python 3.13.18,
`python3 -m unittest discover -s tests` → 201 tests OK (v2.2.0). The pipeline below
(`check`, `scan`, `report`) was executed against synthetic fixtures and a
1 GiB sparse-file fixture on that host.

**Not yet executed:** any of these commands on a physical Android/Termux
installation. The first on-device pass is part of the user's acceptance
flow — see §6.

## 4. Running the audit

```sh
cd ~/android-storage-audit     # or wherever you copied the project

# Preflight: Python version, root existence/listing, writability, volume info
bash run_audit.sh check

# Full read-only scan (default root ~/storage/shared)
bash run_audit.sh scan

# List runs and counters
bash run_audit.sh list-runs
bash run_audit.sh show-run 1

# Rebuild the report from the existing scan (no rescanning)
bash run_audit.sh report --latest
```

Expected output locations (defaults):

```
~/.local/share/android-storage-audit/storage_audit.sqlite3
~/.local/share/android-storage-audit/reports/run_<id>_<timestamp>/index.html
~/.local/share/android-storage-audit/logs/storage_audit.log
```

Override with `--db`, `--output-dir`, or `XDG_DATA_HOME`.

## 5. Opening and copying the report

- **Open directly:** in a file manager or browser on the phone, navigate to
  `reports/run_<id>_<timestamp>/index.html` and open it. All pages
  work offline.
- **Copy to a PC:** `termux-setup-storage` gives Termux access to shared
  storage, so the simplest path is to let the report directory stay inside
  shared storage, or copy it:
  ```sh
  cp -r ~/.local/share/android-storage-audit/reports/run_1_* \
        ~/storage/shared/audit-report/
  ```
  then connect USB and copy `audit-report/` to your computer. (The report
  contains your filenames — treat the copy as private.)
- The HTML is a single self-contained tree of files: CSS and JS are local
  (`report.css`, `report.js`), search data is embedded or chunked under
  `data/`. No network requests are made.

## 6. Battery and process interruption

- Scanning tens of thousands of files can take minutes on flash storage.
  Keep the screen on or acquire a wake-lock: `termux-wake-lock` before,
  `termux-wake-unlock` after.
- If Android kills Termux mid-scan (memory pressure, battery saver,
  swipe-away), the next run of the tool recovers the stale `running` row to
  `interrupted_or_recovered` automatically. The partial run stays in the
  database and is listed as incomplete — it is never reported as complete.
- There is no resume in V1: re-run `scan` for a fresh complete run.
- Use `--batch-size` (50–5000) to trade commit frequency vs. overhead; the
  default 500 is sensible.

## 7. Permission limitations (why some things are invisible)

- **App-private sandboxes** (`/data/data/<pkg>`) are never visible without
  root — by Android design (sandboxing), not by tool limitation you can fix.
- **Other apps' shared media** is visible if your Android version grants it;
  on Android 11+ with scoped storage, photo/media access prompts are
  per-category.
- **Restricted directories** (e.g. `Android/data/…` on Android 11+) are not
  listable by normal apps, including Termux. They will appear as
  permission-denied issues, or not at all, depending on ROM.
- **`.thumbnails`, caches and app-specific dirs** created by other apps may
  be unreadable; the scanner records failures as issues, never guesses.
- **OS-reported "used storage"** in Android Settings includes system and
  reserved areas this tool cannot see; inventoried bytes will not match it.

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `check` exits 2: root missing | `termux-setup-storage` not run / permission denied | Run it, grant permission, re-run `check` |
| `check` exits 2: root not listable | Empty shared storage grant | Grant "Files and media" fully in Android Settings |
| `scan` exits 2 | Broad root refused (`/` or `~`) | Use the default root; don't point at `/` |
| Report pages show "INCOMPLETE" | Scan was cancelled/interrupted or had issues | Check `show-run <id>` and `scan_issues.html` |
| Search page empty | JS disabled | Use "Static paginated tables" linked in the noscript banner |
| "0 entries" after scan | Wrong root resolved (e.g. non-Termux dev host) | `show-run` shows the canonical root; set `--root ~/storage/shared` |
| Database locked | Another instance still running | Let it finish; don't run two scans on the same DB |
| Report stale | Built before a new scan | `report --latest` rebuilds from the newest terminal run |

## 9. What this guide does NOT claim

One V1 run has been executed on an Android 15 / Termux device (by the owner,
not by the development agent): 8,584 files + 165 dirs, 42.36 GiB,
`completed_with_gaps` (two FUSE mounts not crossed). The resulting report was
generated on-device. **The v1.0.1 correctness fix has not been re-verified on
that phone, and no V2 command has been run on it.** Any other claim about your
specific ROM, Android version, and Termux build is true only after you run
the handoff steps on the device. If you have a phone clone of this repository
from before 2026-11-23, delete it and re-clone — the earlier history contained
a private artifact (see `docs/PUBLICATION_PRIVACY_AUDIT.md`).

## 10. v2.2.0 device trial — read-only checks first, then a disposable folder

**Nothing in Phase A modifies anything.** Phase B creates and later removes
ONLY a brand-new, synthetic folder you name yourself — it never touches your
personal files. Do not run Phase B, and do not run any `organize-apply`
against your real folders (`Download`, `DCIM`, `Pictures`, …), until you have
reviewed Phase A output and explicitly approve the trial.

### Phase A — read-only checks (paste into Termux, top to bottom)

```sh
# A1. One-time setup (skip if already done)
pkg update && pkg install -y python git
termux-setup-storage          # grant the Android permission when prompted

# A2. What does ~/storage really look like? (read-only)
ls -la ~/storage
#    Expect: symlinks shared -> /storage/emulated/0 (or similar),
#    plus documents/dcim/downloads/music/... aliases
readlink ~/storage/shared
readlink ~/storage/dcim ~/storage/downloads

# A3. The tool, from the public repo, at the release commit
cd ~
rm -rf android-storage-audit-check && git clone https://github.com/Manash07Bhoi/StorageLens.git android-storage-audit-check
cd android-storage-audit-check
git rev-parse --short HEAD     # v2.2.0 release commit
python3 storage_audit.py --version
#    Expect: Android Storage Audit 2.2.0 (schema 3)

# A4. Full test suite ON the phone (uses synthetic fixtures only)
python3 -m unittest discover -s tests
#    Expect: Ran 201 tests — OK

# A5. Environment + shared-storage preflight (read-only)
python3 storage_audit.py check --root ~/storage/shared

# A6. The documented alias MUST validate now (v2.2.0 fix).
#     This builds a DRAFT plan ONLY — nothing is moved, copied or deleted.
python3 storage_audit.py organize-plan --scope ~/storage/shared
#    Expect: exit 2, "refusing to organize the entire shared-storage root"
python3 storage_audit.py organize-plan --scope ~/storage/shared/Android
#    Expect: exit 2, protected_android reason, NO plan created
python3 storage_audit.py organize-plan --scope ~/storage/shared/Download
#    Expect on success: "Organization plan #N created (DRAFT" and
#    "Eligible files" printed. DRAFT plans change nothing.
#    Inspect it safely:
python3 storage_audit.py organize-show --plan-id <N>
#    Delete the draft without anything happening:
python3 storage_audit.py organize-cancel --plan-id <N>

# A7. If you have a custom folder of YOUR OWN that you would one day want to
#     organize, see what the tool says today (read-only):
python3 storage_audit.py organize-plan --scope "$HOME/storage/shared/Some custom folder"
#    Expect: exit 2, "not a recognized personal folder" — visibility is
#    not ownership. (Then stop. Do not register anything yet.)

# A8. Read-only inventory scan + report of shared storage (no writes outside
#     Termux-private storage; safe to run)
python3 storage_audit.py scan --root ~/storage/shared
python3 storage_audit.py report --latest
```

Paste the full terminal output of A2–A8 into the conversation for review.
Especially useful: the exact `readlink` results and the A5/A6 outputs.

### Phase B — disposable end-to-end trial (ONLY after you approve)

Creates `~/storage/shared/StorageLens_Disposable_Test` with synthetic files,
runs the whole plan→preview→approve→apply→undo cycle on THAT FOLDER ONLY,
then leaves cleanup to you:

```sh
# B1. Synthetic corpus (only new files; your existing data untouched)
T=~/storage/shared/StorageLens_Disposable_Test
mkdir -p "$T/Documents" "$T/Pictures"
printf 'hello'  > "$T/Documents/notes.txt"
printf 'a,b\n1,2\n' > "$T/Documents/data.csv"
printf 'img'    > "$T/Pictures/photo1.jpg"
printf 'img'    > "$T/Pictures/photo2.jpg"
printf 'secret' > "$T/Android/data/nested_should_not_exist" 2>/dev/null || \
  { mkdir -p "$T/Android/data" && printf 'secret' > "$T/Android/data/nested_should_not_exist"; }
#    (The Android/child above must NEVER appear in the plan — verify in B3.)

# B2. Register the custom folder explicitly (interactive confirmation)
python3 storage_audit.py organize-register-scope --scope "$T" --note "device trial"
#    (re-type the canonical path when prompted; this writes ONLY to
#     Termux-private storage: $XDG_DATA_HOME/android-storage-audit/scope_registry.json)

# B3. Plan + preview; CONFIRM the Android/ child is excluded and eligible>0
python3 storage_audit.py organize-plan --scope "$T" --action copy-keep
#    Expect: eligible 4, excluded >=1 (Android/nested_should_not_exist),
#    operations 4, policy org-scope-2
python3 storage_audit.py organize-preview --plan-id <N>

# B4. Approve + apply (copy-keep — NOTHING is deleted anywhere)
python3 storage_audit.py organize-approve --plan-id <N>     # type APPROVE
python3 storage_audit.py organize-apply --plan-id <N>

# B5. Verify: copies exist under <T>/<Category>/…; originals still present
ls -R "$T"

# B6. Undo one operation (optional; needs --approve-delete)
python3 storage_audit.py organize-undo --operation-id <OP_ID> --approve-delete

# B7. Revoke the registration; the folder is unselectable again
python3 storage_audit.py organize-unregister-scope --scope "$T"
python3 storage_audit.py organize-plan --scope "$T"
#    Expect: exit 2 (not registered anymore)
```

Cleanup, when you are fully satisfied and have your own copy of the evidence:

```sh
rm -rf ~/storage/shared/StorageLens_Disposable_Test   # YOUR explicit call
```

### What this trial does NOT authorize

- No `--action move` on anything you care about.
- No `organize-apply` on `Download`, `DCIM`, `Pictures`, `Documents` or any
  real folder — not until you have reviewed Phase A **and** said so explicitly.
- No organizing `Android/`, no registering system/app-private/Termux-private
  locations (the tool refuses them; do not try to work around it).
- The on-device behaviour of the FUSE-backed `Android/data` and the real
  `~/storage` alias targets remains **NOT TESTED** until YOU run these steps.
