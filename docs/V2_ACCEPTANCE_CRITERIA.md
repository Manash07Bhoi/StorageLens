# V2 Acceptance Criteria (M1 ship gate)

Status key: PASS = verified with evidence. NOT TESTED = not executed anywhere.

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | V1 scan behavior unchanged; all V1 tests pass | PASS | 136/136 unittest, incl. unchanged V1 suite |
| 2 | Plan created only from completed runs | PASS | planner refuses non-terminal statuses (test) |
| 3 | Apply refused on unapproved plan; zero fs changes | PASS | gating tests; manual CLI smoke |
| 4 | Copy-keep apply copies bytes identical to source | PASS | executor + end-to-end smoke (1500/1500) |
| 5 | Move apply without `--acknowledge-source-removal` refused; nothing copied or deleted | PASS | gating test |
| 6 | No destination overwritten (plan-time or mid-run) | PASS | conflict tests (sentinel file intact) |
| 7 | Source never removed before verified destination | PASS | hash-verify corruption test; move ack test |
| 8 | Symlinks never copied/moved/followed | PASS | planner + executor tests |
| 9 | Destinations cannot escape target root | PASS | containment tests (incl. hostile stored path) |
| 10 | Interruption detectable; in_progress → interrupted on next run | PASS | reconcile test |
| 11 | Undo move round-trips; copy-keep undo gated by `--approve-delete` | PASS | undo tests |
| 12 | Journal (events) exists for every step | PASS | events written in all paths tested |
| 13 | Plan preview renders offline, escaped, no network refs | PASS | 0 external refs; embedded JSON escaped |
| 14 | DB migration v1→v2 preserves scan history | PASS | migration test; fresh+legacy paths |
| 15 | Phone (Android 15/Termux) executes V2 flows | NOT TESTED | requires user device run — see ANDROID_TERMUX_GUIDE |
| 16 | Move execution on real user data | NOT TESTED | intentionally — user runs on device first |
