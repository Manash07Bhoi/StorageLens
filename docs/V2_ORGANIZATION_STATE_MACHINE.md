# V2 Organization State Machines (as implemented)

## Plan: organization_plans.status
```
draft ──(organize-approve)──────────────► approved ──(organize-apply)──► executing
  │                                        │                                 │
  ├──(organize-cancel)──► cancelled       ├──(organize-cancel)──► cancelled ├─ all ops ok ─► completed
  │                                        │                                 ├─ any op failed/interp ─► completed_with_errors
  │                                        │                                 ├─ stop-on-error ─► recovery_required
  │                                        │                                 └─ cancel event ─► cancelled
  └──(execute apply on draft)── REFUSED by gate
```
Invalid: draft→executing, approved→completed (skips execution), terminal→any.

## Operation: organization_operations.status
```
planned ─(apply: validate fail)─► failed
planned ─(conflict at plan)──────► conflict  (terminal for apply; visible; re-plan to fix)
planned ─(apply: start)──────────► in_progress ─(success+verify)─► completed
                                      │
                                      ├─(copy/verify error)─► failed
                                      └─(crash/kill)────────► interrupted  (reconcile_interrupted)
completed ─(undo)─► rolled_back
```
Invalid: conflict→completed, failed→completed, interrupted→completed (manual
review required), rolled_back→anything.

## Approval rules
- `approve_plan` accepts only draft|ready_for_review; conflicts counted and
  reported at approval time.
- `apply_plan` accepts approved|executing (resume), never draft.
- `undo_operation` accepts only completed ops; copy-keep undo additionally
  requires `approve_delete_copy=True`.
- Gates are code paths, not UI hints; no flag ordering bypass (move requires
  BOTH `--action move` at plan AND `--acknowledge-source-removal` at apply).

## Persistence rules
- One transaction per op for status flips; plan transition in its own
  transaction; events appended within the same transaction.
- A failed apply never rolls back already-completed operations (they are
  verified and complete); it reports them and stops (or continues per flag).

## Test coverage of transitions
See tests/test_organizer.py — gating (draft refusal), move ack (refusal vs
success), cancel event, stop-on-error halting, reconcile of planted
`in_progress`, undo gates. Full matrix: V2_FILE_OPERATION_FAILURE_MATRIX.md.
