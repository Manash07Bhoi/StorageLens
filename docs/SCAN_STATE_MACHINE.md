# Scan State Machine (as implemented, v2.0.0)

## States (scan_runs.status)
`running` → `completed` | `completed_with_gaps` | `cancelled` | `failed` | `interrupted_or_recovered`

Terminal states are immutable for inventory rows (only report bookkeeping may
follow). `interrupted_or_recovered` is assigned at next launch for stale
`running` rows whose PID is no longer alive (best-effort PID check); the
previous evidence is preserved, never overwritten.

## Transitions
| From | Trigger | To | Guard / side effects |
|---|---|---|---|
| — | `scan` invoked | `running` | root validated; DB row created first |
| running | traversal ends; all entries accounted; counters reconcile; integrity_check OK; no gaps | `completed` | normal success |
| running | same + ≥1 issue/skip | `completed_with_gaps` | coverage_incomplete=1; notes list categories |
| running | Ctrl+C/SIGTERM | `cancelled` | batch committed; report marked INCOMPLETE |
| running | unrecoverable exception | `failed` | message recorded; DB closed cleanly |
| running | process vanished (next launch) | `interrupted_or_recovered` | stale detected; notes explain uncertainty |
| any terminal | `report` | unchanged | report_state transitions are separate (report_built/built_failed); never alter scan status |
| terminal | second `scan` | new `running` row | previous run untouched; IDs isolate runs |

**Forbidden:** running→completed without full traversal; cancelled→completed;
terminal→running; a completed run being mutated by another run; a report
failure downgrading a completed scan (report failure only sets
report_state='built_failed'... recorded independently via report_builds).

## Report lifecycle is separate
`report --latest|--scan-id` regenerates from an existing run. A report may
fail while the scan stays `completed`. A report built from
`completed_with_gaps` must carry the INCOMPLETE banner on every page and the
`scan_id` it represents (implemented and verified in the real artifact above).

## Decision table — the Android 15 case
| Condition | Result | Records |
|---|---|---|
| `Android/data` is directory, st_dev ≠ root | skip, never descend | entry row (skip_reason=mount_boundary), issue operation=mount_boundary (v1.0.1+) |
| Permission denied listing any dir | siblings continue; run → completed_with_gaps | issue operation=list/stat/readlink, error_category from errno |
| Entry vanishes between listdir and stat | issue recorded; scan completes | stat_status='failed', size NULL |
| Output inside scan root | exact subtree excluded; recorded | exclusions_json |
| Cancel during traversal | partial commit; cancelled | report regenerable, labelled INCOMPLETE |
| Root deleted mid-scan | current batch commits; failure → `failed` | error recorded |

## Test evidence
Gating/lifecycle/recovery: tests/test_database.py (transitions, immutability,
stale recovery, integrity), tests/test_scanner.py (cancel, vanish, permission,
incomplete labelling). 157 tests pass on the dev host; on-device execution is
NOT TESTED (see device gate).
