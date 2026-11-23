# V2 Recommendation Validation (what V2 may and may NOT claim)

## Delivered (v2.0.0): no recommendation engine. By design.
M1 ships mechanics (plan/approve/apply/undo), not opinions. The only heuristic
shipped as a report page is V1's "Review Candidates" — neutral observations
with explicit labels. V2 adds nothing that labels user content as junk.

## Rules of evidence for any future recommendation feature
R1. Every row must be reproducible from the inventory DB (file path, size,
    mtime, category) — never from content inference or invented scores.
R2. Language: "same-size candidate", "unmodified for 5+ years", "large" —
    never "duplicate", "unnecessary", "safe to delete".
R3. Confidence labels, when shown, name their basis (size-only / name+size /
    opt-in hash). Size-only matches are explicitly "unverified".
R4. Zero-byte ≠ deletable; empty directory ≠ always safe; old ≠ unwanted.
R5. No ranking that pretends to know value (no ML, no heuristics invented in
    M1). Category folders are the only classification applied.
R6. Every recommendation row carries its evidence columns (path, size, mtime,
    category) — no opaque scores.

## Validation status of the recommendation surface
- V1 Review Candidates page: built from DB queries; counts verified against DB
  in fixture tests; labelled neutral; **NOT TESTED for false-positive rate on
  real user data** (it doesn't need one — it makes no claims).
- Same-size grouping: verified groups in fixtures; sizes only.
- M2 recommendation engine: NOT IMPLEMENTED; acceptance criteria deferred to
  V2_ROADMAP M2 with explicit tests to be written then.

## Why no content hashing in default flows
Hashing reads every byte of private files, costs time/battery, and still
cannot prove value. `--hash-verify` (plan opt-in) and `--hash-verify` semantics
are explicit and documented; duplicates are never deleted by the tool.
