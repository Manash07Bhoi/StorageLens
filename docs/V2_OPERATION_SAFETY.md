# V2 Operation Safety — Invariants, Guarantees and Limitations

## Guarantees (each enforced in code + tested)
G1. **No approval → no execution.** Apply on a draft plan raises before any I/O.
G2. **Move requires double consent.** Plan `--action move` AND apply
    `--acknowledge-source-removal`. Missing either: nothing is copied or deleted.
G3. **No overwrite — ever.** Conflicts are marked, skipped, and listed in the
    preview and history. A destination that appears after planning is a failure,
    not an invitation.
G4. **No premature deletion.** Source is removed (move) only after the
    destination copy passes verification (size+mtime, or SHA-256 if requested).
    Copy failure ⇒ source untouched.
G5. **Atomicity per operation, not per plan.** Each file op is independently
    journalled; a plan can finish `completed_with_errors` with honest counters.
G6. **Cross-filesystem = copy→verify→(optionally)remove.** `rename` alone is
    never assumed to work across devices; fallback copy-verify-delete in undo.
G7. **Interruption is visible.** Crash ⇒ `in_progress` rows become
    `interrupted` on the next `organize-*` command or explicit reconcile call.
G8. **Undo is conservative.** Move undo: destination must match recorded size;
    source path must be free. Copy-keep undo (deletes our copy): explicit
    `--approve-delete` + destination size re-check. Any mismatch ⇒ refusal.
G9. **Symlinks: never followed, copied or moved.** Recorded, refused, logged.
G10. **Target containment.** Destinations are realpath-checked against the
     approved target root at apply time (not only at plan time).

## What happens on each failure (see V2_FILE_OPERATION_FAILURE_MATRIX.md)
- Destination exists → op failed; destination untouched; source untouched.
- Destination appears mid-run → op failed; the new file untouched.
- Source disappears → op failed; rest of plan continues (or halts with
  `--stop-on-error` → plan `recovery_required`).
- Hash/size verify fails → op failed; source kept; bogus destination left for
  inspection (documented; manual cleanup — V2 never auto-deletes destinations).
- fsync/write error → op failed; partial destination removed? **No** — preserved
  and reported; deleting an unverified copy automatically would violate G4's
  spirit (never silently delete user-visible data). Documented honestly.
- Insufficient space → whole apply refused before any file is copied.

## Non-guarantees (honest limitations)
- A move is not a transaction across the whole plan. Mid-plan crash = some ops
  done, some planned, some interrupted; all are inspectable and individually
  undoable.
- Undo cannot resurrect data if the destination was modified externally after a
  verified copy — it refuses instead (G8).
- SHA-256 equality proves byte equality, not "safety to delete". Deletion is a
  user decision; V2 only executes what was approved.
- Filesystem metadata (mtime) may change on some filesystems; size+SHA-256 is
  the strong check and is recommended for irreplaceable data.
- Reports/previews are private personal data; storing them in shared storage
  makes them visible to other apps with storage access.
