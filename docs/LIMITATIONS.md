# Limitations

Honest boundaries of Android Storage Audit V1. Read this before acting on
any result.

## Android permission model

- Termux sees **shared internal storage** only (via `termux-setup-storage`).
  App-private sandboxes (`/data/data/<package>`), other apps' internal
  databases, and system partitions are invisible without root.
- Android 11+ **scoped storage** restricts cross-app file access. Some
  directories (notably `Android/data/…` and `Android/obb/…`) are not
  listable even with "All files access" in some ROMs; the scanner will
  record what it can and log the rest as issues.
- **Root is never used** and its absence is a design constraint, not a bug.
- Manufacturer ROMs (Samsung, Xiaomi, …) vary; what is unreadable on one
  device may be readable on another.

## What "shared storage" covers — and doesn't

- **Covers:** files in the shared volumes Termux can enumerate — typically
  the user-visible media/document tree (`DCIM`, `Pictures`, `Download`,
  `Documents`, `Music`, `Movies`, `Recordings`, …).
- **Does not cover:** SD cards mounted as adoptable storage in other
  sandboxes, network volumes, cloud provider storage (Drive/OneDrive/
  Dropbox — V2 roadmap, not implemented), other users' profiles, and
  removed/unmounted volumes.
- Inventoried bytes ≠ Android Settings "used storage". The OS figure
  includes system, reserved and app areas; the tool reports logical bytes
  of visible regular files only.

## Measurement caveats

- **Size = logical bytes** (`st_size`). Sparse files measure larger than
  they occupy on disk; compression (e.g. on some filesystems/ROMs) makes
  physical usage smaller still. The report labels OS-comparison figures.
- **mtime is modification time**, not creation time. Android exposes no
  reliable per-file creation time through `os.stat`. `ctime` (where shown
  elsewhere) is inode-change time, never "date created".
- **MIME/extension classification is a filename guess.** A `.jpg` that is
  actually a text file is classified as an image; `archive.tar.gz` is
  treated as a compound archive; unknown extensions stay `unknown` —
  explicitly, not silently mapped to a category.
- **Same-size files are candidates, not duplicates.** V1 performs no
  hashing; nothing in the report proves two files are identical.

## Symlinks

Recorded, never followed. Consequences:

- no traversal loops, no escaping the root;
- symlinked directories appear as `symlink` entries, not as subtrees;
- broken symlinks are recorded as issues;
- a file reached only through symlinks is absent from the inventory.

## Consolidation caveats

- **No content inspection** — the tool cannot detect corruption, duplicates,
  wrong extensions, or mislabeled files; it inventories names and sizes.
- **No resume in V1** — an interrupted scan is discarded as usable data
  (kept as an incomplete record); re-running starts fresh.
- **Concurrent modification during scan** — files created/deleted while
  scanning are reflected as observed; deleted-before-stat files are logged
  as issues. There is no snapshot isolation on the filesystem.
- **Counting caveat** — hard links are counted once per path (they share
  an inode, but each directory entry is an entry). Physical disk usage from
  hard links is therefore overstated relative to unique blocks.

## Tooling caveats

- Classification tables are versioned (`CLASSIFICATION_VERSION = 1.0.0`);
  changing the table changes categories — reclassified history is not
  retroactive across runs.
- Report regeneration is from the database only; the report never re-stats
  the tree, so it can disagree with the *current* filesystem (by design —
  it is a snapshot view).
- SQLite on a flaky/full filesystem: WAL commits can fail with clear
  errors; the run is marked `failed`, never silently corrupted.

## Device-specific behavior

- `termux-setup-storage` behavior, default root layout, and permission
  prompts vary by Android version (11/12/13/14/15) and OEM skin.
- Battery optimization can kill Termux during long scans; use
  `termux-wake-lock` (see `docs/ANDROID_TERMUX_GUIDE.md` §6).
- On very large trees (millions of entries), the single-file inline search
  payload switches to chunked `data/inventory_NNN.js`; some very old
  browsers in Android WebView may be slow — static paginated tables remain
  available.

## What is NOT verified

**No on-device run has been performed yet.** All results in this repository
come from the Linux x86_64 development host. The first physical scan is the
user's acceptance step; discrepancies found there should be logged in
`docs/GAP_REGISTER.md`.
