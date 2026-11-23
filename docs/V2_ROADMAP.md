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

## Shipped increment v2.1.0 (2026-11-23)
- org-scope-1 policy: explicitly selected, validated user-owned folders only;
  Android/, system, Termux-private, hidden/reserved default-deny at plan time,
  before execution and before undo; documented 20-case security test suite.
- Schema v3 (scope manifest on organization_plans); preview renders the scope
  panel; CLI `--scope` flag (`--target` kept as compatibility alias).

## Shipped increment v2.2.0 (2026-11-23, corrective — independent review)
- org-scope-2 policy: canonical-path propagation fixed; trusted Termux
  `~/storage/<alias>` resolution; recognized personal-folder allowlist with
  explicit custom-folder registration (`organize-register-scope` /
  `organize-unregister-scope` / `organize-scopes`); registry mode-0600 and
  fail-closed; revocation enforced at apply and undo. Android/, system,
  Termux-private, hidden/reserved remain default-deny with NO override.
- Suite 157 → 201 tests (tests/test_scope_hardening.py + CLI registration
  tests). v2.1.0 was not accepted; see FINAL_AUDIT.md v2.2.0 addendum.
