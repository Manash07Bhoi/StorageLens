# Organization Scope Security Tests (org-scope-1)

**Mandatory acceptance deliverable.** Every case below is automated in
`tests/test_scope_security.py` unless marked otherwise, and runs on the
development host (Linux x86_64). None of them require a device. The two
device-specific facts (FUSE behaviour of `Android/data`, Termux `PREFIX`
layout) are modelled here by synthetic equivalents and are additionally
**NOT TESTED on a physical phone** — see honesty note at the end.

Command: `python3 -m unittest tests.test_scope_security -v`
Result at time of writing: **21 tests, all PASS.**

| # | Required case | Where enforced | Automated test | Result |
|---|---|---|---|---|
| 1 | Selecting `Android/` | scope validation + planner | `test_m01_selecting_android_root_rejected` | PASS |
| 2 | Selecting `Android/data/` | scope validation | `test_m02_selecting_android_data_rejected` | PASS |
| 3 | Selecting `Android/obb/` | scope validation | `test_m03_selecting_android_obb_rejected` | PASS |
| 4 | Selecting `Android/media/` | scope validation | `test_m04_selecting_android_media_rejected` | PASS |
| 5 | Selecting a nested application directory (`Android/data/<app>/files`) | scope validation | `test_m05_selecting_nested_application_directory_rejected` | PASS |
| 6 | Selecting Termux-private storage | scope validation (`PREFIX` check + protected `/data` prefix) | `test_m06_selecting_termux_private_storage_rejected` | PASS |
| 7 | Selecting a protected system-related directory | scope validation (absolute prefixes) | `test_m07_selecting_protected_system_directory_rejected` | PASS (synthetic prefix; real prefix list asserted) |
| 8 | Selecting a hidden directory | scope validation (`.` component rule) | `test_m08_selecting_hidden_directory_rejected` | PASS |
| 9 | Selecting an unknown/reserved directory (`LOST.DIR`, `.thumbnails`, `.Trash-*`) | scope validation (reserved names) | `test_m09_selecting_unknown_or_reserved_directory_rejected` | PASS |
| 10 | Selecting an allowed personal folder | scope validation + planner | `test_m10_selecting_allowed_personal_folder_permitted` | PASS |
| 11 | Allowed folder containing a prohibited child (`Documents/Android/…`, `Documents/.hidden_sub/…`) | recursive exclusion at every level | `test_m11_allowed_folder_with_prohibited_child_excluded` | PASS |
| 12 | A symlink pointing into `Android/` | symlink never followed at walk or target selection | `test_m12_symlink_into_android_never_followed` | PASS |
| 13 | A symlink pointing outside the selected root | walk exclusion + execution re-check | `test_m13_symlink_outside_selected_root_excluded` | PASS |
| 14 | A destination inside `Android/` | execution-time revalidation | `test_m14_destination_inside_android_refused` | PASS |
| 15 | A destination outside the selected root | execution-time revalidation | `test_m15_destination_outside_selected_root_refused` | PASS |
| 16 | A path changing after plan creation | apply-time scope revalidation | `test_m16_path_changing_after_plan_creation_refused` | PASS |
| 17 | A directory changing into a symlink before execution | execution-time revalidation (subdir swap and scope-root swap) | `test_m17a_scope_subdirectory_swapped_to_symlink_refused`, `test_m17b_scope_root_replaced_by_symlink_refused` | PASS |
| 18 | Batch operations containing both allowed and prohibited paths | default-deny plan; apply only touches allowed | `test_m18_batch_mixed_allowed_and_prohibited_only_allowed_runs` | PASS |
| 19 | An organization rule attempting to cross the approved scope | rule has no scope escape hatch; tampered destination rejected | `test_m19_rule_output_crossing_scope_refused` | PASS |
| 20 | An interrupted operation attempting to resume outside its original scope | reconcile marks interrupted; resume revalidates; nothing executes | `test_m20_interrupted_plan_cannot_resume_outside_original_scope` | PASS |

**Prohibited cases never execute.** For each prohibited case the test asserts
both the refusal and the filesystem invariant (no file created, moved,
renamed, modified or deleted anywhere, and the prohibited tree's before/after
snapshot is unchanged). For plan-refusal cases the plan is never created.

## Enforcement points (all present, all tested)

| Layer | Enforcement | Code |
|---|---|---|
| Target selection | `validate_scope()` — default-deny; returns checks/reasons; `ScopeRejected` otherwise | `organizer/scope.py` |
| Recursive traversal | `walk_eligible()` — lstat, never follow, prune Android/ hidden/reserved/boundary dirs at every level; records exclusions | `organizer/scope.py` |
| Plan creation | planner refuses via `ScopeRejected`; exclusions persisted on the plan row + events | `organizer/planner.py` |
| Per-operation | `op_path_check()` — source & destination must both be in scope, unprohibited, non-symlink — re-evaluated at execution | `organizer/scope.py`, `executor.apply_plan` |
| Before apply | `revalidate_plan_scope()` — full re-validation; refusal journalled (`scope_revalidation_failed`) | `executor.apply_plan` |
| Before undo | same revalidation; recovery never widens scope | `executor.undo_operation` |
| Database | scope manifest on every plan: target root, canonical, allowed dirs, exclusions, validation result, policy version (schema v3) | `database.py` |
| UI | scope panel in the offline preview: selected folder, canonical path, eligibility counts, excluded reasons, validation checks, hard-boundary banner | `organizer/preview.py` |
| CLI | `--scope` flag; refusal prints the exact message "Organization unavailable: this location is protected or outside the permitted user-data scope." with per-reason lines; no override flag exists anywhere | `cli.py` |
| Docs/tests | this document + `test_scope_security.py` + `V2_OPERATION_SAFETY.md` | — |

## Policy decisions recorded (not loopholes)

1. **"Unknown directories"** are rejected when they are hidden, reserved
   (`LOST.DIR`, trash), Android-reserved or under protected absolute prefixes.
   A *visible* folder the user explicitly selects cannot be ownership-guessed
   by any reliable method on shared storage; it is cleared path-wise by the
   same validation. Uncertainty always defaults to rejection — there is no
   code path in which an unverifiable location is permitted.
2. **No overrides exist** for Android/ or other prohibited locations.
   There is intentionally no flag, env var, config file or hidden switch.
3. **Validation is re-done at execution time.** Plan-time validation is a
   convenience, not a guarantee; the executor revalidates the scope and every
   operation before touching the filesystem (TOCTOU defence).
4. **Copy-keep never deletes**; move requires double acknowledgement; sources
   are deleted only after verified copies — all inside the approved scope.

## Not tested (honesty)

- On a physical Android 15 device with the real FUSE-backed `Android/data` and
  `Android/obb`: the scope policy treats them as prohibited at the *path*
  level (component rule), which holds regardless of FUSE behaviour. No device
  assertion is claimed.
- Real `PREFIX` layout on the user's Termux build (test 6 uses the documented
  `PREFIX` mechanism with a synthetic private dir; the Android app-private
  absolute prefixes `/data/...` are covered by the shipped protected list).
- Hostile directory swaps racing the copy itself (no dirfd-anchored I/O exists
  in stdlib) — mitigated by post-copy verification before any source removal;
  documented in PATH_SECURITY_VALIDATION.md.
