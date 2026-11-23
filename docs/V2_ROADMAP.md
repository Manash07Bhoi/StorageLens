# V2 Roadmap — Milestones and Boundaries

**Current release: v2.0.0 (M1).** Everything below the line is NOT implemented;
no dates are promised.

## M1 — Safe organization core (this release)
Plan → preview → approve → apply → verify → undo, journalled, tested on
synthetic fixtures, Linux-host only. See V2_PRD.md.

## M2 — Richer analysis (not started)
- Large/old/zero-byte/empty-directory analysis views surfaced as "review
  candidates" (neutral observations, never "safe to delete").
- Same-size candidate grouping promoted from report section to planner input
  (opt-in `--hash-verify` already exists for execution-time content equality).
- **M2 guardrail:** hashing is opt-in everywhere; default remains metadata-only.

## M3 — Organization UX (design required first)
- Interactive CLI wizard for plan construction (rule selection, target picker).
- V2 dashboard inside the offline report (organization plan summary, history,
  recovery status). Still offline HTML; no native app decision yet — see
  V2_DESIGN_SYSTEM.md and V2_PRD.md "native UI comparison".

## M4 — Android on-device validation (BLOCKED — user action required)
Re-run the full V1/V2 suite on the physical Android 15/Termux device:
scan → report → organize dry-run → organize apply on a small target folder →
verify undo round trip. All results to be documented in TEST_EVIDENCE.

## Explicitly not planned (V1 boundary stands)
Cloud sync/backup, dedup-by-delete, automatic cleanup, deletion commands in
scan path, content indexing, OCR, thumbnails, background services.

## Dependency policy
Standard library only. No new runtime dependencies for M1/M2. Any future
dependency requires a documented decision (license, size, Android wheel
availability, supply-chain review) in DECISIONS.md.
