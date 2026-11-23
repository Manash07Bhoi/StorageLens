# V2 File Operation Failure Matrix

Legend: Src = source before/after · Dst = destination · Det = detection point ·
St = resulting operation status · Test = test in tests/test_organizer.py

| Trigger | Det | Src final | Dst final | Op status | Safety outcome | Test |
|---|---|---|---|---|---|---|
| Destination exists at plan time | planner | untouched | pre-existing file | conflict | excluded from apply | test_conflict_with_existing_destination_flagged |
| Destination appears before apply | apply re-check | intact | newcomer untouched | failed | never overwritten | test_destination_appearing_mid_run_is_not_overwritten |
| Source vanishes before apply | apply re-check | gone (external) | absent | failed | rest continues / halt w/ --stop-on-error | test_source_disappearing_fails_op_not_crash |
| Source is symlink | planner + apply | untouched | absent | failed at apply / skipped at plan | never followed | test_symlinks_are_never_planned |
| Source modified (size/mtime drift) between plan and apply | apply verify | current content copied | verified copy | completed | consistent because verify happens after copy | by construction (re-read at apply) |
| Hash verify mismatch (corruption/race) | post-copy | intact | bogus copy left, reported | failed | source never deleted | test_hash_verify_detects_corruption |
| Insufficient space on target | pre-flight | intact | nothing written | apply refused | all-or-nothing precheck | test_insufficient_space_refuses_before_copying |
| Interrupted mid-apply (crash/kill) | next command | intact (op not completed) | partial copy possible | interrupted (after reconcile) | never assumed done | test_reconcile_marks_in_progress_interrupted |
| Cancel requested during apply | between ops | intact (unapplied ops) | applied ops verified | plan cancelled | partial-but-honest plan state | test_cancel_event_leaves_plan_cancelled |
| Remove source fails after verified copy (permissions) | apply, move only | NOT removed | verified copy present | failed | copy exists; source intact; error loud | code path reviewed; fs-level failure not injected |
| Undo: destination changed since execution | undo re-check | n/a | changed file preserved | refused | no data rewritten | test_undo_refuses_when_dest_changed |
| Undo: source path occupied | undo re-check | would-be clobber refused | untouched | refused | no overwrite possible | gate in undo_operation |
| Undo copy-keep without approval | undo gate | intact | untouched | refused | deletion needs explicit flag | test_undo_copy_keep_requires_approve_delete |
| Verify fails but destination left behind | post-copy | intact | bogus dst preserved for inspection | failed | user-visible; never auto-deleted | by design (documented in V2_OPERATION_SAFETY.md) |
| DB write fails mid-apply | per-op transaction | intact or copied | per-op fsync'd | op failed; plan continues | operation atomicity | transactional design; not fault-injected |
| Rollback impossible (dst gone) | undo | — | absent | refused | explicit error | guard clauses in undo_operation |

## Explicit non-guarantees (honest)
- No distributed transaction across multi-file plans; per-file atomicity only.
- Partial destinations after a crash are surfaced, not cleaned automatically.
- `--stop-on-error` marks the plan `recovery_required`; resolution is manual
  review + (optionally) another apply after the cause is fixed.
