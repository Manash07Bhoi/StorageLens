# V2 Architecture — Organization Engine (M1)

## Context
V2 adds a **bounded, separate command family** (`organize-*`) on top of the V1
inventory. V1 modules (scanner, safety, analytics, exporters, report) are
unchanged in behavior. Shared pieces: `database.connect/migrate`, `config`,
`logging_config`, `safety` primitives.

## Module map
```
storage_audit/organizer/
├── __init__.py      package exports
├── scope.py         org-scope-1: validate_scope(), walk_eligible(),
│                    op_path_check() — the default-deny boundary
├── planner.py       build_plan(): ONE explicitly selected user-owned
│                    folder → DRAFT plan (lstat walk; no file writes)
├── executor.py      approve_plan(), apply_plan(), undo_operation(),
│                    reconcile_interrupted(), cancel_plan()
└── preview.py       render_plan_preview() / write_plan_preview()
                     (offline, premium dark, escaped, atomic replace,
                      with the organization-scope panel)
```

## Data flow
```
ONE explicitly selected, user-owned folder ─── USER SELECTION (mandatory)
      │  org-scope-1 validate_scope() — default-deny (Android/, system,
      │  Termux-private, hidden, reserved, cross-boundary, symlink escape)
      ▼
walk_eligible() ─── fresh lstat walk OF THE SCOPE ONLY; exclusions recorded
      │             (Android/ hidden/reserved/boundary pruned at EVERY level)
      ▼
planner ──► organization_plans (status=draft; scope manifest columns)
            organization_operations (planned | conflict; sources & dests
                                    both inside the scope)
            organization_events (plan_created, skipped_source with reasons…)
      │  user reviews (organize-show / organize-history / organize-preview
      │  — preview renders the scope panel: selection, validation, exclusions)
      ▼
organize-approve ──► plan.status = approved (explicit, logged)
      ▼
organize-apply ──► revalidate_plan_scope() — full re-validation; refusal
      │            journalled; NOTHING runs on failure
      │            per op: op_path_check() (src+dst in scope, unprohibited,
      │            not symlink) + re-validate (exists, dst free, dest
      │            contained, free space ≥ payload+64MiB)
      │            → copy 1 MiB chunks → fsync → verify (size+mtime | size+SHA-256)
      │            → [move only + --acknowledge-source-removal] os.remove(src)
      │            → op.status = completed | failed | interrupted
      ▼
organize-undo ──► same scope revalidation; move: dst→src (rename |
                  copy-verify-delete fallback); copy-keep: --approve-delete
```

## Invariants (code-enforced)
1. Apply requires plan `approved` (executing/resume allowed).
2. Move plans require `acknowledge_source_removal=True`.
3. Destination never overwritten (plan-time reservation + lexists re-check).
4. Source removed only after destination verified (size+mtime or SHA-256).
5. Symlinks refused at plan and apply time; never followed.
6. Destinations realpath-contained in the approved scope (re-checked at
   apply, per operation, and at undo).
7. Moves crossing filesystems are copy→verify→remove, never rename() alone.
8. Every transition journalled (`organization_events`), plans and ops.
9. `in_progress` at restart → reconciled to `interrupted`; never trusted.
10. Dry-run is the default: `organize-plan` writes only DB rows; the user
    creates the HTML preview explicitly.
11. Sources and destinations BOTH stay inside the approved scope; the scope
    is revalidated before apply and before undo (org-scope-1, G11–G13).

## Deliberate non-goals of M1
No recommendation engine, no dedup, no native UI, no background worker, no
network, no new runtime dependencies. V1 modules are not modified to serve V2.

## Native vs offline-HTML decision
An offline-HTML V2 preview was chosen for M1: it reuses the V1 distribution
model (git clone + python), works offline on Android, and is auditable.
A native app was evaluated and rejected for this milestone: it would add a
build toolchain, signing, Play-Store or sideload friction, and a second code
base, without improving safety. Revisit after M3 (see V2_ROADMAP.md) with a
documented migration plan if the user wants an app.
