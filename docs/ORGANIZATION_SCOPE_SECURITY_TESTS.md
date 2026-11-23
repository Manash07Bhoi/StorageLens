# Organization Scope Security Tests (org-scope-2)

**Mandatory acceptance deliverable.** Every case below is automated in
`tests/test_scope_security.py` (the twenty mandatory review cases) plus
`tests/test_scope_hardening.py` (the 2026-11-23 review corrections:
canonical-path propagation, trusted Termux storage aliases, recognized
personal folders, explicit custom-folder registration, registry fail-closed
and revocation, post-plan scope changes, boundary branches) unless marked
otherwise, and runs on the development host (Linux x86_64). None of them
require a device. The two device-specific facts (FUSE behaviour of
`Android/data`, Termux `PREFIX` and `~/storage/<alias>` layout) are modelled
here by synthetic equivalents and are additionally **NOT TESTED on a physical
phone** — see honesty note at the end.

Commands:

```sh
python3 -m unittest tests.test_scope_security -v   # 21 tests
python3 -m unittest tests.test_scope_hardening -v  # 41 tests
python3 -m unittest discover -s tests              # 201 tests total
```

Result at time of writing: **all PASS on the development host.** Command
output and fresh-clone verification are recorded in `docs/TEST_EVIDENCE.md`.

## Mandatory cases (twenty)

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

## Additional org-scope-2 cases (2026-11-23 review)

| # | Required case | Where enforced | Automated test (`tests/test_scope_hardening.py`) | Result |
|---|---|---|---|---|
| H01 | `<A>/../<B>` argv propagates **canonical** path into validation and plan manifest | `validate_scope()` + planner | `test_unnormalized_dotdot_input_yields_canonical`, `test_plan_manifest_stores_canonical_not_raw_argument` | PASS |
| H02 | `~`-expanded input | `validate_scope()` | `test_expanded_home_input` | PASS |
| H03 | Double slashes / leading `.` components | `validate_scope()` | `test_double_slashes_and_dot_components` | PASS |
| H04 | Relative argv resolved against cwd | `validate_scope()` | `test_relative_input_from_cwd` | PASS |
| H05 | Already-canonical input unchanged | `validate_scope()` | `test_already_canonical_input_unchanged` | PASS |
| H06 | Nonexistent path fails closed; reported canonical still canonical | `validate_scope()` | `test_nonexistent_path_still_fails_closed_with_canonical` | PASS |
| H07 | Termux `~/storage/shared/Documents` (alias → root) accepted; canonical inside permitted root | trusted-alias resolution | `test_documented_alias_documents_accepted`, `test_trusted_alias_check_recorded` | PASS (synthetic layout) |
| H08 | Documented alias `~/storage/documents` selected directly | trusted-alias resolution | `test_documented_alias_documents_direct` | PASS (synthetic layout) |
| H09 | Alias resolving to the shared-storage root itself rejected as too broad | validation | `test_alias_to_shared_root_itself_rejected_as_too_broad` | PASS |
| H10 | Undocumented name under `~/storage` rejected | trusted-alias resolution + strict fallback | `test_undocumented_name_in_storage_rejected` | PASS |
| H11 | Documented alias name pointing **outside** the permitted root rejected | trusted-alias resolution (no resolve) | `test_known_alias_name_pointing_outside_root_rejected` | PASS |
| H12 | Alias pointing at `Android/` stays rejected | component policy after resolution | `test_alias_pointing_at_android_stays_rejected` | PASS |
| H13 | Symlink **below** the resolved root still excluded at walk | `walk_eligible()` | `test_symlink_inside_alias_resolved_scope_still_excluded` | PASS |
| H14 | Unrecognized visible folder rejected (visibility ≠ ownership) | recognition check | `test_unrecognized_visible_folder_rejected` | PASS |
| H15 | Recognized folder needs no registration (and creates no registry file) | recognition check | `test_recognized_folder_needs_no_registration` | PASS |
| H16 | Register custom folder → validate OK → plan created → unregister → rejected again | registry flow | `test_register_custom_folder_then_plan_then_unregister` | PASS |
| H17 | Registration refused for Android/, hidden, filesystem root | `register_scope()` re-validates prohibited classes | `test_registration_refused_for_prohibited_locations` | PASS |
| H18 | Registry file is mode 0600 and round-trips | registry writer | `test_registration_file_is_private_and_roundtrips` | PASS |
| H19 | Corrupt registry fails closed for custom folders | registry fail-closed branch | `test_tampered_registry_fails_closed_for_custom_folder` | PASS |
| H20 | Corrupt registry does NOT break recognized folders | recognition independent of registry | `test_tampered_registry_does_not_break_recognized_folder` | PASS |
| H21 | Registry revocation invalidates an APPROVED plan at apply; zero FS changes, zero completed ops | `revalidate_plan_scope()` at apply | `test_registry_revocation_blocks_approved_plan_at_apply` | PASS |
| H22 | Rejection creates **no plan row** and **no filesystem change** | planner runs validation before insert | `test_zero_rows_and_zero_fs_changes_on_rejected_plan` | PASS |
| H23 | Scope deleted after approval → apply refuses | `revalidate_plan_scope()` | `test_scope_deleted_after_approval_fails_revalidation` | PASS |
| H24 | Scope replaced by symlink after approval → apply refuses | `revalidate_plan_scope()` + `lstat` | `test_scope_replaced_by_symlink_after_approval_fails` | PASS |
| H25 | Protected-prefix check is path-boundary aware (sibling ≠ child) | component check | `test_protected_prefix_boundary_is_path_aware` | PASS |
| H26 | `STORAGE_AUDIT_SHARED_ROOT` candidate honoured; must exist; `~/storage/shared` fallback | `find_permitted_storage_root()` | `test_env_var_candidate_wins`, `test_env_var_candidate_must_exist`, `test_home_storage_shared_candidate_used` | PASS |
| H27 | Cross-boundary scope rejected; unstatable parent fails closed | `mount_boundary` check | `test_cross_boundary_scope_rejected`, `test_unstatable_parent_fails_closed` | PASS (mocked devices) |
| H28 | Source/destination escapes, Android components, symlink source rejected at op level; in-scope pair accepted | `op_path_check()` | `test_source_outside_scope_rejected`, `test_destination_outside_scope_rejected`, `test_destination_with_android_component_rejected`, `test_symlink_source_rejected`, `test_ordinary_in_scope_pair_accepted` | PASS |
| H29 | Undo refused after scope deleted | `revalidate_plan_scope()` before undo | `test_undo_refused_after_scope_deleted` | PASS |
| H30 | Undo refused after registry revocation | `revalidate_plan_scope()` before undo | `test_undo_refused_after_registry_revocation` | PASS |
| H31 | Policy-version drift is journalled, never widens a scope | `apply_plan()` drift telemetry | `test_policy_version_drift_is_journalled_not_widened` | PASS |
| H32 | Empty/missing path inputs rejected | `validate_scope()` | `test_validate_scope_never_returns_ok_for_empty_path` | PASS |
| H33 | CLI end-to-end: scan → refused plan (exit 2) → confirmation required → register → plan OK → unregister → refused again | `cli.py` + `organize-register-scope` | `tests/test_cli.py::TestCliScopeRegistration` (3 tests) | PASS |
| H34 | CLI registration of prohibited folder refused (exit 2) | `cli.py` | `test_registration_of_prohibited_folder_refused` | PASS |
| H35 | Recognized folder needs no registration over the CLI | `cli.py` | `test_recognized_folder_needs_no_registration` | PASS |

**Prohibited cases never execute.** For each prohibited case the tests assert
both the refusal and the filesystem invariant (no file created, moved,
renamed, modified or deleted anywhere, and the prohibited tree's before/after
snapshot is unchanged), and for plan-refusal cases that no `organization_plans`
row is written.

## Enforcement points (all present, all tested)

| Layer | Enforcement | Code |
|---|---|---|
| Target selection | `validate_scope()` — default-deny; returns checks/reasons; `ScopeRejected` otherwise | `organizer/scope.py` |
| Termux aliases | `resolve_trusted_alias()` — documented `~/storage/<alias>` names only, realpath inside permitted shared storage, final destination re-validated; anything else falls back to strict checks | `organizer/scope.py` |
| Recursive traversal | `walk_eligible()` — lstat, never follow, prune Android/ hidden/reserved/boundary dirs at every level; records exclusions | `organizer/scope.py` |
| Recognition | recognized personal-folder allowlist; other visible folders rejected (`recognized_personal`) | `organizer/scope.py` |
| Explicit registration | `register_scope()` — validates prohibited classes first (can never clear them), writes mode-0600 registry; `organize-register-scope` CLI with interactive confirmation | `organizer/scope.py`, `cli.py` |
| Plan creation | planner refuses via `ScopeRejected` BEFORE any INSERT; exclusions persisted on the plan row + events | `organizer/planner.py` |
| Per-operation | `op_path_check()` — source & destination must both be in scope, unprohibited, non-symlink — re-evaluated at execution | `organizer/scope.py`, `executor.apply_plan` |
| Before apply | `revalidate_plan_scope()` — full re-validation under the CURRENT policy; refusal journalled (`scope_revalidation_failed`); policy mismatch journalled (`scope_policy_mismatch`) | `executor.apply_plan` |
| Before undo | same revalidation; recovery never widens scope | `executor.undo_operation` |
| Database | scope manifest on every plan: target root, canonical, allowed dirs, exclusions, validation result, policy version (schema v3) | `database.py` |
| UI | scope panel in the offline preview: selected folder, canonical path, eligibility counts, excluded reasons, validation checks, hard-boundary banner | `organizer/preview.py` |
| CLI | `--scope` flag; refusal prints the exact message "Organization unavailable: this location is protected or outside the permitted user-data scope." with per-reason lines; registration commands additionally require explicit confirmation; no override flag exists anywhere | `cli.py` |
| Docs/tests | this document + `test_scope_security.py` + `test_scope_hardening.py` + `V2_OPERATION_SAFETY.md` | — |

## Policy decisions recorded (not loopholes)

1. **Visibility is not ownership.** A visible folder is NOT accepted merely
   because it is visible. Only the recognized personal-folder allowlist
   (Download/Downloads, Documents, Pictures, Movies, Music, Ringtones,
   Alarms, Notifications, DCIM, Recordings, Screenshots, Podcasts,
   Audiopodcasts, Audiobooks, Bluetooth — case-insensitive, immediate child
   of shared storage or selection basename on a dev host) is accepted
   without extra ceremony. Every other visible folder must be explicitly
   registered by the user on this device (`organize-register-scope`).
   Uncertainty always defaults to rejection — there is no code path in
   which an unverifiable or merely-visible location is permitted.
2. **Registration is not an override.** Registration clears ONLY the
   "unknown folder" check, for the exact canonical folder the user selects,
   on this device, after explicit confirmation. It can never clear Android/,
   system, application-private, Termux-private, hidden, reserved or
   cross-boundary locations — `register_scope()` runs the full prohibited
   validation and refuses before writing. There is no flag, env var, config
   file or hidden switch anywhere.
3. **Registry is fail-closed.** An unreadable/corrupt registry rejects every
   custom folder. Recognized personal folders are unaffected (recognition
   does not read the registry). Revocation (`organize-unregister-scope`)
   invalidates pending plans at apply and at undo.
4. **Validation is re-done at execution time.** Plan-time validation is a
   convenience, not a guarantee; the executor revalidates the scope and every
   operation before touching the filesystem (TOCTOU defence).
5. **Copy-keep never deletes**; move requires double acknowledgement; sources
   are deleted only after verified copies — all inside the approved scope.
6. **Trusted aliases never widen the scope.** The Termux alias mechanism
   resolves a documented `~/storage/<name>` symlink to the permitted
   shared-storage root and then re-validates the result; an alias whose
   target escapes the root, or an undocumented name, is refused.

## Not tested (honesty)

- On a physical Android 15 device with the real FUSE-backed `Android/data`
  and `Android/obb`: the scope policy treats them as prohibited at the
  *path* level (component rule), which holds regardless of FUSE behaviour.
  No device assertion is claimed.
- Real `PREFIX` layout on the user's Termux build (test M06 uses the
  documented `PREFIX` mechanism with a synthetic private dir; the Android
  app-private absolute prefixes `/data/...` are covered by the shipped
  protected list).
- The real Termux `~/storage/<alias>` symlink farm created by
  `termux-setup-storage`: the resolution logic is tested against a synthetic
  fixture reproducing that layout; the exact symlink targets and any
  ROM-specific naming on the user's device are NOT verified.
- On-device trial must start with a disposable test folder; see
  `docs/FINAL_AUDIT.md` for the read-only check commands.
