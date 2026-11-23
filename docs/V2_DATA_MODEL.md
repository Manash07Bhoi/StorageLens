# V2 Data Model — Schema Version 2

Schema v2 is **additive**: all V1 tables are untouched; `user_version=2`;
forward-only migration (`migrate()` upgrades fresh and v1 databases);
`schema_migrations` gains version 2. Scan history is never rewritten.

## organization_plans
| column | type/constraint | meaning |
|---|---|---|
| id | PK | plan id |
| scan_id | FK → scan_runs(id) RESTRICT | source scan; plan dies with nothing |
| rule_name / rule_version | TEXT | `by-category` / `1.0.0` |
| target_root | TEXT | realpath'd destination root |
| action | CHECK copy-keep\|move | default `copy-keep` |
| hash_verify | 0/1 | SHA-256 verify at apply time |
| status | CHECK draft\|ready_for_review\|approved\|executing\|completed\|completed_with_errors\|cancelled\|failed\|recovery_required | plan lifecycle |
| created_at_epoch / updated_at_epoch / approved_at_epoch | INTEGER | audit timestamps |
| approval_note | TEXT | free text from approver |
| total_operations / total_bytes / conflicts / invalid | INTEGER | counters reconciled by executor |
| notes | TEXT | e.g. `action=copy-keep; rule=by-category; skipped=N` |

## organization_operations
| column | meaning |
|---|---|
| plan_id | FK → organization_plans ON DELETE CASCADE |
| scan_id | denormalized for audit joins |
| seq | 1..N order within plan; UNIQUE(plan_id, seq) |
| action, source_rel/abs, dest_rel/abs | deterministic mapping; dest preserved under target |
| size_bytes / dest_size_bytes | planned vs post-copy observed |
| status | planned\|conflict\|in_progress\|completed\|failed\|interrupted\|rolled_back\|skipped |
| conflict | NULL\|exists\|duplicate_in_plan |
| error | failure detail (never swallowed) |
| started_at_epoch / finished_at_epoch | execution audit |

Indexes: (plan_id), (status).

## organization_events
Append-only journal: (plan_id, operation_id, event, detail, occurred_at_epoch).
Events: plan_created, plan_approved, plan_apply_started, plan_finished,
plan_cancelled, plan_recovery_required, op_started, op_verified,
op_source_removed, op_completed, op_failed, op_interrupted_recovered,
op_rolled_back, skipped_source.

## Metric definitions (unchanged from V1 + new)
- "Operations planned" = rows in organization_operations for the plan.
- "Move bytes" = SUM(size_bytes) where action='move' and status='completed'.
- "Conflicts" = status='conflict' — excluded from apply by construction.
- Plan throughput on 1500-file fixture: copy-keep, 0 failures, 0.67 s (host).
