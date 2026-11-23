# V2 Test Strategy

## Layers
L1 Unit — planner sanitization, category folders, segment rules, containment.
L2 Integration — plan→approve→apply→undo against real SQLite + synthetic trees.
L3 End-to-end CLI — `organize-*` commands via subprocess-style invocation paths
   covered by direct function calls in tests.
L4 Host benchmark — timing/memory on synthetic 1,500-file tree (reported in
   V2_PERFORMANCE_VALIDATION.md; not a phone).
L5 Device — NOT YET RUN. Blocked on user executing on Android 15 (see
   V2_ACCEPTANCE_CRITERIA.md #15/#16 and ANDROID_TERMUX_GUIDE).

## Synthetic fixture policy
Fixtures live in tests/helpers.py (generated fresh per test, temp dir, cleaned
up). They include: Unicode/emoji/newline names, zero-byte files, symlinks
(incl. loops), deep nesting, hidden files, mixed categories. **No personal data,
ever.** The 256 MiB sparse fixture is used only in scanner tests, never copied
by organizer tests.

## Failure-injection approach
- Vanishing source: delete file after plan → apply reports failed op, plan
  completes_with_errors, no crash.
- Corrupting copy: monkeypatched `_copy_file` appends a byte → SHA-256 verify
  fails → op failed → source preserved.
- Destination race: pre-create sentinel at dest before apply → dest untouched.
- Cancel: pre-set cancel event → plan cancelled, nothing copied.
- Disk-full: `shutil.disk_usage` mocked to 1 byte → apply refused pre-flight.
- Stop-on-error: halted plan = `recovery_required`; remaining ops untouched.
- Interrupted: `in_progress` op manually planted → reconcile → `interrupted`.
- DB: fresh vs v1-shaped database → migration → `user_version=2`, rows preserved.

## Pass/fail gates for release
All automated tests must pass on the release commit; any failure blocks
release. Manual/device checks are documented as NOT TESTED until performed —
they are never inferred from host results.

## Known gaps in testing (honest)
- No fuzzing of the preview HTML parser surface.
- No concurrent-apply stress (SQLite busy_timeout=30s covers basic contention;
  no multi-writer test exists).
- No large-plan (>100k ops) memory profile yet.
- No browser automation (click-through) for preview page — manual only.
