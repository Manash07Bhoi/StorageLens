# V2 Product Requirements Document — StorageLens Organization Engine

**Status:** M1 implemented & tested (v2.0.0, dev host) · **on-device validation pending**
**Companion specs:** V2 Engineering Master Execution Prompt + V2 Validation Supplement
(one contract with the V1 master + gap supplement).

## Problem
The V1 scan answers *what is on your storage and how is it distributed* (8,584
files / 42.36 GiB on the real device). It cannot *safely reorganize* anything —
by design, V1 is read-only. Users still need a safe path from "I understand my
storage" to "I fixed my layout" without data-loss risk.

## Product principle
**Understand → Analyze → Plan → Preview → Approve → Execute → Verify → Undo (where possible).**
No phase is skipped, no phase is hidden behind a single button.

## M1 scope (implemented, v2.0.0)
| Capability | Implementation |
|---|---|
| Organization plan builder | `organize-plan` — deterministic `by-category` rule applied to a fresh walk of ONE explicitly selected, user-owned folder (Images/Videos/Audio/Documents/Archives/Packages/Databases/Code/Fonts/Backups/System/Unsorted/Other) preserving source directory structure under that folder; scope policy org-scope-2 is mandatory (see V2_OPERATION_SAFETY.md G11–G13 and ORGANIZATION_SCOPE_SECURITY_TESTS.md) |
| Plan preview | `organize-preview` — fully offline, premium dark HTML; embedded JSON rows; search/filter/pagination; per-op status; conflict exclusion visible; approval instructions inline |
| Explicit approval gate | `organize-approve` — interactive `APPROVE` confirmation or `--yes`; plan becomes `approved`; nothing executes before this |
| Safe execution | `organize-apply` — re-validates every source/destination at execution time; copies in 1 MiB chunks; fsync; verifies (size+mtime, or SHA-256 with `--hash-verify` at plan time); **copy-keep is the default**; sources are removed only for `move` plans AND only after each destination verifies AND only with `--acknowledge-source-removal` |
| Conflict safety | destination exists (in plan or appearing before apply) → operation marked `conflict`/`failed`, never overwritten; `duplicate_in_plan` detection |
| Cancellation | `--stop-on-error` → plan `recovery_required`; cancellation via event → `cancelled` |
| Interruption recovery | stale `in_progress` operations are reconciled to `interrupted` on next command; never assumed complete |
| Operation history | `organize-history` / `organize-show`; full journal in `organization_events` |
| Undo | move → destination moved back to (free) source path; copy-keep → copy deleted only with `--approve-delete`; destination change since execution → undo refused |
| Audit trail | every step journalled per operation; plan-level and op-level events |

## Out of scope for M1 (designed, not implemented — see V2_ROADMAP.md)
Storage dashboard rewrite, file/folder explorers, native Android UI, automatic
"recommendations", duplicate confirmation by hashing, background execution,
mount-crossing moves, network/cloud anything. None of these are faked or stubbed;
they are absent.

## Non-negotiables (restated)
- Read-only V1 scan remains untouched and works as before.
- No overwrite of existing files, ever.
- No source deletion before destination verification.
- No silent failures; every refusal is explicit and journalled.
- Private data never leaves the device; reports are local; V2 preview is local.
- Honest statuses everywhere; on-device validation still pending.

## Success metrics (measured on dev host only — NOT phone)
Fixture: 1,500 synthetic files / 15.3 MB. Scan 0.23 s · plan 0.14 s · apply
(copy-keep, 1500/1500 completed, 0 failed) 0.67 s · peak child RSS 24 MiB.
Android 15 numbers: **not yet measured — requires on-device run.**
