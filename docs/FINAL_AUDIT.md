# Final Audit — Supplement §13 (Items 1–16)

Executed 2026-11-23 on the development host after implementation, fixes, and
the full test suite were green. Both specifications were re-read end-to-end
this session (master §0–§18, supplement §1–§13). Every command shown was
actually run; every number is from this host.

## §13.1 Re-read both documents
Done — grep-verified section inventory matches both matrices
(`docs/TRACEABILITY_MASTER.md`, `docs/TRACEABILITY_SUPPLEMENT.md`).

## §13.2 Traceability matrix covering both documents
Produced: `TRACEABILITY_MASTER.md` (37 master requirements) and
`TRACEABILITY_SUPPLEMENT.md` (supplement sections §1–§13, gates A–G).
Every requirement carries module, verification/evidence, and status.
No requirement was silently omitted; device-dependent items are marked
**blocked (device)**, never **done**.

## §13.3 Requirements without implementation or weak evidence
Identified and registered with severities in `docs/GAP_REGISTER.md`:
on-device validation (G-001), DB lock/disk-full fault injection (G-005),
browser automation (G-007), dev-host-only performance (G-006), plus
low-severity notes (G-004, G-008, G-011, G-012). No critical items.

## §13.4 Expanded test matrix executed
`python3 -m unittest discover -s tests -v` → **110 tests, OK** (1.5 s).
Breakdown by module in `docs/TEST_EVIDENCE.md`. Fixture coverage includes
Unicode/emoji/Devanagari, newline/tab/comma/quote/`<img onerror>` filenames,
256 MiB sparse file, broken+loop symlinks, hidden/empty/dotfiles, compound
extensions, permission-denied and disappearing-file branches (mocked).

## §13.5 Failure-branch review (conditional-logic tables)
Reviewed `filesystem.py`, `scanner.py`, `database.py`, `exporters.py`,
`report_builder.py`:
- scandir `PermissionError`/`OSError` on a directory → issue recorded,
  sibling traversal continues (`test_scanner.py` mocked case →
  `completed_with_gaps`);
- `next(entries_iter)` `OSError` mid-listing → issue, directory treated as
  done;
- lstat failure on an entry → entry recorded with `stat_status='failed'`,
  `size_status='failed'` + issue (`test_scanner.py` mocked disappeared file);
- containment failure (`safe_relpath` → None) → skipped + issue;
- excluded output-under-root subtree → counted in `excluded_count`, never
  inventoried;
- mount-boundary device mismatch → recorded, not descended (unit-tested via
  device injection, DECISIONS.md #3);
- broken symlink → recorded with `symlink_target_status` failure, not
  followed;
- DB `integrity_check` failure → run downgraded to `failed` (never
  `completed`);
- report build exception → `report_state='failed'`, scan status untouched,
  exit 1, data preserved (`cli.py` cmd_report);
- cancellation during traversal → commit current batch, finalize as
  `cancelled`, `coverage_incomplete=1` (executed manually: 14/14 pages of
  the cancelled-run report carry the incomplete marker);
- stale `running` at startup → `os.kill(pid, 0)` probe; dead →
  `interrupted_or_recovered`; alive → untouched; undeterminable → left +
  warning (DECISIONS.md #14).

Open failure-branch debt: none beyond G-005/G-007.

## §13.6 Filesystem interaction audit (mutation / content reads / symlink / escape)
`docs/SECURITY_READONLY_AUDIT.md` — every write call site inventoried and
classified; writes confined to state/output dirs; scanned tree snapshot
before/after scans proves read-only; symlinks never followed; no content
reads in default mode (no hashing anywhere except manifest SHA-256 of
*exports this tool itself writes* — documented).

## §13.7 SQL audit (parameterization / transactions / run isolation)
100% parameterized statements; the only interpolated fragments are column
lists from closed whitelists (`_TRANSITION_COLUMNS`, `update_counters`) and
placeholder counts — no user data. `with conn:` transactions; WAL;
`synchronous=FULL`; FKs `ON DELETE RESTRICT`; `UNIQUE(scan_id,
relative_path)`; run isolation proven by tests.

## §13.8 Output audit (escaping / injection / offline)
Offline: regex sweep over all generated pages for external URLs — none;
`node --check report.js` passes; no CDN/fonts/remote assets. Escaping:
HTML entity escaping incl. C0 controls; embedded JSON is `\uXXXX`-escaped
for `<`, `>`, `&`, U+2028/29; CSV formula-injection neutralization with
always-on test; tree/summary control chars escaped; Markdown code spans
handled by `md_code` (backslash-literal aware). `<img onerror>` fixture
renders as inert text on every page (test enforced).

## §13.9 Metric reconciliation vs database + exports
Executed on a fresh synthetic fixture (run #1):

| Metric | DB query | Export/manifest | Match |
|---|---|---|---|
| Regular files | 29 | `files.csv` 29 rows | ✓ |
| Directories | 22 | manifest counters `directories` = 22 | ✓ |
| Inventoried bytes (file, observed) | 268,435,613 | JSONL Σ bytes = 268,435,613; manifest `inventoried_file_bytes` = 268,435,613 | ✓ |
| Total entries | 54 | JSONL lines = 54 | ✓ |
| Scan issues | 0 | `scan_issues.csv` header only; manifest `issues` = 0 | ✓ |
| Unavailable-size files | 0 | manifest `unavailable_size_files` = 0 | ✓ |

Analytics cross-check: grand total computed once from regular files
(`test_analytics.py`); directory recursive rollups verified against manual
sums (a = 120 B / 5 files; root = 130 B / 6 files fixture).

## §13.10 Report regenerated from an older scan without rescanning
Executed: two fixture scans (run 1, run 2). Rebuilt run 1's report twice —
`entries` rows for run 1 unchanged (54 → 54), counters unchanged,
`report_state` = `built`, run 2 untouched, `report_builds` audit rows
written. See `docs/TEST_EVIDENCE.md` §report-regeneration.

## §13.11 Cancelled/failed never shown as complete
Executed: pre-cancelled run → `status=cancelled`,
`coverage_incomplete=1`; built report; **14/14 HTML pages** contain the
partial/incomplete marker; `test_report.py` enforces the same for
`cancelled` fixtures; `list-runs` shows `cancelled` distinctly; CLI exits 3.

## §13.12 Fixture data never labelled as a real phone scan
Every test fixture sets `fixture_label=True`; pages built from fixtures
render the banner "SYNTHETIC TEST DATA — NOT THE USER'S PHONE." The
benchmark fixture likewise. Real-scan pages carry no such banner; the
README/guides never present fixture output as device output.

## §13.13 Fake metrics / TODO / FIXME / placeholder search
Sweep over both source trees for `TODO|FIXME|XXX|HACK|WIP|placeholder`
(case-insensitive): zero real hits (only `placeholder=` HTML input
attributes and the word in prose). `100%` appears only in explicit
non-claims ("no 100% device coverage", "no claim of 100% scanned"). No
fabricated numbers: every figure in docs comes from either the fixture
runs above, the unittest suite, or the benchmark (labelled with host).
Every visible control in the report is wired (search/filter/sort/reset/
pagination/nav links) or a static link — no decorative buttons (audit
checklist in `SECURITY_READONLY_AUDIT.md`).

## §13.14 All fixable defects fixed
See `docs/GAP_REGISTER.md` "Resolved during this build" — R-001…R-011,
including two sub-second full rescans to verify counters end-to-end. The
final full suite passes on the shipped code.

## §13.15 Gap register produced, severity-tagged
`docs/GAP_REGISTER.md`: Critical 0 open · High 1 open (G-001, blocked
validation, not a code defect) · Medium 3 open (G-005, G-006, G-007) ·
Low 5 open; 11 resolved with evidence. No unresolved critical defects.

## §13.16 Final wording
> **V1 implementation complete; on-device validation pending.**

NOT declared production-ready for the phone. The implementation host is
Linux x86_64; no command in this repository has been executed on the
user's device. Gate A is partial; Gates B–G pass on the dev host with
mobile/a11y verified manually only. On-device acceptance steps are in
`README.md` §5–§6 and `docs/ANDROID_TERMUX_GUIDE.md`.

---

## Deliverables checklist (Supplement §"Required final deliverables")

- [x] completed V1 project (this tree)
- [x] master requirements traceability matrix (`TRACEABILITY_MASTER.md`)
- [x] supplement requirements traceability matrix (`TRACEABILITY_SUPPLEMENT.md`)
- [x] test report with actual results (`TEST_EVIDENCE.md`)
- [x] security/read-only audit report (`SECURITY_READONLY_AUDIT.md`)
- [x] performance measurement report (`PERFORMANCE.md`)
- [x] known limitations and unresolved gap register (`GAP_REGISTER.md`, `LIMITATIONS.md`)
- [x] exact Termux first-run instructions (`README.md`, `ANDROID_TERMUX_GUIDE.md`)
- [x] clear statement distinguishing remote fixture validation from real-device validation (this file, §13.16; `TEST_EVIDENCE.md` honesty note; README "Validation status")

---

## Public release addendum (2026-11-23)

- Repository: https://github.com/Manash07Bhoi/StorageLens — created public
  on 2026-11-23; MIT license (SPDX-detected); default branch `main`;
  topics set (android, termux, storage, audit, inventory, read-only,
  offline-first, sqlite, html-report, python).
- Pre-push hygiene: 48 staged files scanned — no token/credential material,
  no local databases, no scan exports/reports, no `__pycache__`/build
  artifacts, no personal filesystem data; `.gitignore` narrows `output/` to
  `output/README.md` only; remote URL carries no credentials (token used
  only via per-call credential helper; `.git/config` contains no token).
- Post-create verification via GitHub API: repository public, description
  set, `main` HEAD matches the pushed release commit, 48 files in the
  remote tree, all required files present, no forbidden file types.
- This addendum changes documentation only; no code paths modified after
  the final `Ran 110 tests … OK` run.

**Final wording (unchanged): V1 implementation complete; on-device
validation pending.**

---

## V2 addendum — 2026-11-23 (v2.0.0)

**What shipped (host-validated only):** planning-first organization engine —
`organize-plan/preview/approve/apply/history/show/undo/cancel`; schema v2
(additive migration); offline dark HTML preview of plans; explicit approval
gate enforced in code; copy→fsync→verify journaling; copy-keep default;
move double-consent; never overwrites; interrupted applies reconciled; undo
refuses on changed files. See `V2_*` docs and `CHANGELOG.md`.

**Verification re-run after all doc edits (release line):**
`python3 -m unittest discover -s tests` → `Ran 136 tests ... OK`;
`python3 -m compileall` clean; `node --check` exits 0; wheel builds with
`storage_audit/organizer/*` and templates included.

**Device reality:** one V1 run on Android 15 (owner-executed, private
artifact) revealed two mount-boundary skips mislabelled as "containment" —
fixed in v1.0.1 (`operation=mount_boundary`), **not re-validated on-device**.
V2 has never run on a device.

**Publication history (2026-11-23):** private report ZIP was briefly public
via owner's web upload (commit range removed by owner-authorized history
rewrite; repo stayed PUBLIC). CDN cache may retain copies — see
`PUBLICATION_PRIVACY_AUDIT.md` for the honest residual-exposure statement and
owner actions (re-clone; optional GitHub Support purge).

**Gates:** A PARTIAL (device) · B PASS host · C PASS host · D PASS host ·
E PASS · F PASS · G PASS · H PASS host · I PARTIAL · J NOT TESTED · K PASS
(with cache caveat) · L PASS. Critical defects open: 0.

**Final wording (unchanged): v2.0.0 is a public source release, host-validated.
It is NOT Android-validated, NOT production-for-phone-proven; the owner's
on-device acceptance run is the next milestone (M2).**

## Independent public-clone audit — 2026-11-23 (release verification)

After pushing `d24c08b`, a **fresh clone of the public repository** was made on
the dev host and every release-critical step was re-executed from it (not from
the working tree):

- `git clone https://github.com/Manash07Bhoi/StorageLens.git` → HEAD = `d24c08b`; 35 docs present.
- `python3 storage_audit.py --version` → `Android Storage Audit 2.0.0 (schema 2)`.
- `python3 -m unittest discover -s tests` → `Ran 136 tests in 3.7s — OK`.
- Fresh-HOME end-to-end V2 loop on a 40-file synthetic fixture:
  `scan` (exit 0) → `organize-plan --target …/Organized` (40 ops, 0 conflicts)
  → `organize-preview` (offline HTML written) → `organize-approve` (typed
  APPROVE gate enforced — EOF refused without input) → `organize-apply`
  (plan completed, done=40 failed=0 skipped=0) → `organize-history` shows
  `completed`. Copy-keep left all 40 source files intact (40 sources + 40
  copies verified on disk).
- GitHub API (authenticated): repository `Manash07Bhoi/StorageLens` PUBLIC,
  MIT, default branch `main`, zero open issues, tree contains no
  `.zip`/`.sqlite3`/`.jsonl`/`.csv`, required files present,
  `raw.../main/docs/V2_PRD.md` serves HTTP 200.
- Public-repo clone tests ran inside the dev host; **no device was involved**.

This is the strongest release evidence available without a phone: the public
artifact itself, not the author's working tree, is what was verified.

## v2.1.0 addendum — 2026-11-23 (org-scope-1 mandatory policy)

**Trigger:** product-owner mandate — V2 must NEVER organize Android/, system,
application-private, Termux-private, hidden or reserved content; only an
explicitly selected, validated, user-owned folder may be organized.

**What changed (behaviour-breaking, deliberately):**
- `organizer/scope.py` introduced (validate_scope / walk_eligible /
  op_path_check). Android/ is rejected anywhere in the path; hidden/reserved/
  cross-boundary/Termux-private/system-prefix selections rejected; recursive
  traversal prunes prohibited directories at every depth and records reasons;
  execution revalidates the scope from scratch before the first operation and
  per operation; undo revalidates too. No override exists anywhere.
- Plan candidates now come from a fresh lstat walk of the approved scope —
  NOT from V1 scan rows (the scan can see more than the user approved;
  visibility ≠ permission).
- Schema v3 adds the scope manifest to organization_plans (eligible/excluded
  counts, policy version, canonical path, violation-free allowed dirs, JSON
  exclusions + validation report). Forward-only, idempotent, v1→v3 and
  v2→v3 paths tested.
- Preview renders the organization-scope panel; CLI gained `--scope`
  (`--target` retained as compatibility alias); protected selections exit 2
  with the standard refusal message; the refusal is journalled.
- Tests: 136 → **157**; mandatory ORGANIZATION_SCOPE_SECURITY_TESTS.md
  (20 cases) implemented in tests/test_scope_security.py (21 tests) — all
  pass. V1 untouched.

**Not claimed:** on-device validation (still pending); Android/ protection
relies on path rules that hold regardless of FUSE internals. The v2.0.0
"organize entire scan" behaviour no longer exists; any plan built under
v2.0.0 semantics would be a different, broader scope and is impossible to
build in v2.1.0.

## v2.2.0 addendum — 2026-11-23 (org-scope-2: independent-review corrections)

**Trigger:** independent product-owner review of PUBLIC v2.1.0 found three
defects; v2.1.0 was explicitly NOT declared accepted. The owner's correction
order is reproduced in `CHANGELOG.md` [2.2.0]. This addendum records what was
actually done and what was NOT verified.

**Findings confirmed in source before fixing:**
1. `validate_scope()` nested `validation()` read `locals().get("canonical", path)`;
   the enclosing function's `canonical` was invisible to the closure, so the
   RAW argument (unnormalized) was stored as `canonical` in the returned
   validation and persisted by the planner (`scope_canonical`,
   `scope_validation_json`, `target_root`). **Fix:** canonical is computed
   once in the enclosing scope and passed explicitly; failure-path validation
   reports a consistent canonical too. Regression tests H01–H06 plus a
   plan-manifest assertion.
2. `_symlink_escape()` rejected EVERY symlink component, making the documented
   `~/storage/shared/Download` selection (a `termux-setup-storage` symlink)
   impossible. **Fix:** strict trusted-alias resolution — only documented
   alias names under `~/storage`, only when the alias is a symlink (or plain
   dir) whose realpath is the permitted shared-storage root or inside it,
   only when the permitted root is determinable; the resolved path is then
   re-validated like any other selection. Arbitrary escapes, undocumented
   names, alias-targets outside the root, and any symlink below the resolved
   root remain rejected (H07–H13). No control weakened.
3. "Visible = selectable": any non-hidden, non-Android visible folder
   validated out of the box. **Fix:** recognized personal-folder allowlist
   (case-insensitive; immediate child of shared storage or selection basename
   on a dev host); every other visible folder requires EXPLICIT registration
   by the user on this device (`organize-register-scope`, interactive
   confirmation, mode-0600 registry, `organize-unregister-scope` to revoke;
   `organize-scopes` to list). Registration can NEVER clear Android/,
   system, application-private, Termux-private, hidden, reserved or
   cross-boundary locations — `register_scope()` runs full prohibited-class
   validation first. Registry reads fail closed; recognized folders do not
   depend on the registry; revocation invalidates pending plans at apply AND
   at undo (`revalidate_plan_scope()`). Ownership is never inferred from
   visibility (H14–H22).

**Branch audit performed** (path normalization, symlink resolution,
storage-root discovery incl. `STORAGE_AUDIT_SHARED_ROOT`, mount-boundary
detection incl. unstatable-parent fail-closed, source/destination
operation checks, post-plan scope changes — deletion, symlink replacement,
registry revocation — apply-time revalidation, undo revalidation, policy
drift telemetry journalled as `scope_policy_mismatch`). Tests H23–H31 plus
H25–H28 cover these branches; the Termux layout is exercised with a
synthetic `~/storage/<alias>` fixture (the real FUSE layout was NOT tested).

**Rejection integrity (item 5 of the correction order):** for every
rejection path the tests assert BOTH a refusal AND an unchanged filesystem
snapshot AND zero new `organization_plans` rows (H22, M01–M09, H14).

**Suite:** 201 tests, all PASS (was 157). Per-module counts in
`docs/TEST_EVIDENCE.md`. Full branch coverage of the new policy is listed in
`docs/ORGANIZATION_SCOPE_SECURITY_TESTS.md`.

**Explicitly NOT done / NOT claimed:**
- No physical Android device was used at any point. The Termux alias
  resolution is validated only against a synthetic fixture. FUSE behaviour,
  the real `~/storage` symlink farm, and Android 15 specifics remain
  **NOT TESTED**.
- v2.2.0 is NOT a claim of acceptance. The owner must review the evidence and
  run the device trial (read-only checks first, then a disposable test
  folder) before any organization command touches real content.
- No personal files were read, moved, modified or organized at any point.
- GitHub repository remained public throughout; private scan data was not
  used or committed.
- The pre-existing GitHub CDN exposure of the rewritten history (see
  PUBLICATION_PRIVACY_AUDIT.md, 2026-11-23) is unchanged and remains the
  owner's action (GitHub Support purge).

**Fresh public-clone verification (executed 2026-11-23, after push):**
`git clone https://github.com/Manash07Bhoi/StorageLens.git` (fresh, HEAD
`af91af8`) → `python3 storage_audit.py --version` ⇒
"Android Storage Audit 2.2.0 (schema 3)"; `python3 -m unittest discover -s
tests` ⇒ **Ran 201 tests — OK**. Fresh-clone smoke on a synthetic tree
(Android/data selection exits 2 with `protected_android` and a clean
single-reason refusal; recognized `Documents/` yields a DRAFT plan under
policy org-scope-2; unregistered custom folder exits 2 with
`recognized_personal`; `organize-register-scope --yes` enables it; plan then
builds; unregister revokes it; registry file mode 0600). `pip wheel` from the
clone builds `android_storage_audit-2.2.0-py3-none-any.whl` containing
`organizer/scope.py` and no `.zip`/`.sqlite3`/`.jsonl`/`.csv` artifacts.
Authenticated GitHub API tree query (main, recursive): 86 entries, no
forbidden artifacts; `organizer/scope.py` and `tests/test_scope_hardening.py`
present. No device was involved; nothing was executed on the owner's phone.
