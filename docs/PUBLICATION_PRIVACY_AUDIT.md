# Publication & Privacy Audit — 2026-11-23 Incident and Current State

**Scope:** the public GitHub repository `Manash07Bhoi/StorageLens` and the agent
workspace. This document records what happened, what was done, and what remains
unknown. It is written to be safe to publish (no inventory contents reproduced).

## Timeline (UTC)
- 2026-11-23 05:29 — v1.0.0 published publicly (48 files, all reviewed).
- ~05:54 — repository owner uploaded `StorageLens_Report.zip` via the GitHub web
  UI ("Add files via upload", commit `f608258…`). **Private storage inventory,
  publicly visible from that moment.**
- Same day — owner noticed `completed_with_gaps` report status, requested audit.
- Agent detected the file in the remote tree during pre-audit inspection.
- Removal from tree: commit `3376300` ("security: remove private
  StorageLens_Report.zip from tree"). Raw URL at `main` then returned 404.
- **Residual:** commit-scoped URLs (`raw.../f608258…/StorageLens_Report.zip`,
  codeload archive) still returned HTTP 200 (GitHub-side caching/object store).
- Owner then explicitly authorized history rewrite. Agent created a recoverable
  backup (private mirror), rewrote history with `git filter-branch`
  (`--index-filter` dropping the ZIP, `--prune-empty`), expired reflogs,
  aggressive gc, deleted `refs/original/*`. Result: the repository history is
  again exactly `061d242 → f8d76a4 → 55089b1` (3 legitimate commits), force-
  pushed. The upload commit and the removal-only commit are gone from all refs.
- Verified after push: remote `main` = `55089b1`; tree has 54 files; zero ZIP
  references in any reachable object (`git rev-list --objects --all`); GitHub
  `/contents` returns 404 for the ZIP; repo remained PUBLIC throughout.
- **Cache caveat (honest):** `raw.githubusercontent.com` and codeload still
  returned HTTP 200 for the old commit SHA immediately after the rewrite. The
  agent cannot purge GitHub's CDN/cache. GitHub Support can invalidate cached
  copies; the owner has been given the exact report steps. Copies downloaded
  by any third party before removal cannot be recalled. **Treat the contents of
  that ZIP as exposed.**
- 06:xx — agent verified no other private artifacts anywhere in history
  (all refs inventoried: no other ZIPs/DBs/reports/exports).

## Agent-side privacy controls
- The ZIP was retrieved **only** into `/home/user/private_storagelens_report/`
  (mode 700), never into the repository, never committed, never pushed.
- Audit tooling read it programmatically; printed output was counts, hashes and
  statuses only. **No filenames from the inventory were printed to logs,
  docs, commit messages, code, or any public artifact** (two generic system
  directory names — `Android/data`, `Android/obb` — are named because they are
  public Android system paths, and the fix depended on them).
- The report evidence (ZIP, extracted tree, manifest, CSVs) remains on the
  agent host under `/home/user/private_storagelens_report/` solely so the
  owner's audit can proceed; owner may delete it at any time. A full mirror
  backup (containing the ZIP) also resides there as the recoverable backup
  created before the authorized rewrite — flagged to the owner; both can be
  wiped on the owner's instruction.
- No data was uploaded to external services beyond github.com itself.

## Repository hygiene verification (post-incident)
Checks run after the rewrite and after every subsequent push:
- No `StorageLens_Report.zip` in tree, refs, or reachable objects. ✓
- No tokens/secrets in tree (pattern scan: ghp_/github_pat_/AKIA/xox/…). ✓
- `.gitignore` narrows `output/` to `output/README.md`. ✓
- No `.sqlite3`, exports, screenshots, or inventories tracked. ✓
- GitHub releases: none. Tags: none. Actions artifacts: 0. Issues: 0. ✓
- Default branch `main`; visibility PUBLIC (owner requirement); license MIT. ✓

## What the ZIP contains (categories only)
HTML report pages, CSS/JS assets, CSV/JSONL/tree exports, manifest, summary —
i.e., personal filenames, folder structure, sizes and timestamps of the owner's
phone shared storage. No passwords, no database, no app content were in it.
No financial, medical or credential material is expected in such an export, but
the exposure cannot be narrowed further without reading it file by file (the
owner should review the list of categories above and assume the rest).

## Required owner actions
1. Re-clone on the phone (`rm -rf ~/StorageLens && git clone …`) — the old
   clone's object store may hold the ZIP blob.
2. If the inventory feels sensitive enough: change nothing else; the ZIP holds
   filenames/sizes/timestamps only. Consider whether any filenames themselves
   leak secrets (e.g., a file named `passwords.txt` reveals existence, not
   content).
3. Ask GitHub Support to purge cached copies of `f608258…` if you want the CDN
   copies invalidated sooner.
4. Decide whether to delete the two private backup artifacts on the agent host.

## Non-goals / standing rules
No report or inventory will ever be committed again; `.gitignore` and this audit
enforce it. Sanitized synthetic fixtures remain the only test data.
