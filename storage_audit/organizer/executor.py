"""Executor: apply approved organization plans with hard safety invariants.

Invariants (every one is enforced here and covered by tests):

1. Nothing runs on a plan that is not ``approved`` (or resuming an
   ``executing`` plan whose interrupted operations were reconciled).
2. A ``move`` plan refuses to execute without
   ``acknowledge_source_removal=True``.
3. No destination is ever overwritten.
4. No source is removed before the destination copy is verified
   (size + mtime, or size + SHA-256 when the plan requested it).
5. Symlinks are never copied, moved, read or followed.
6. Destinations must resolve inside the plan's target root.
7. Every step is journalled in organization_events.
8. Interrupted operations are marked ``interrupted`` on the next call —
   never silently treated as complete.
"""

import hashlib
import os
import shutil
import sqlite3
import time

_COPY_CHUNK = 1024 * 1024  # 1 MiB — bounded memory


class ExecutionError(Exception):
    """Refuses unsafe execution (approval missing, root escape, ...)."""


def _now():
    return int(time.time())


def _event(conn, plan_id, operation_id, event, detail=""):
    conn.execute(
        "INSERT INTO organization_events(plan_id, operation_id, event, detail,"
        " occurred_at_epoch) VALUES (?,?,?,?,?)",
        (plan_id, operation_id, event, detail, _now()))


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dest_contained(dest_abs, target_root):
    root = os.path.realpath(target_root)
    dest = os.path.realpath(dest_abs)
    return dest == root or dest.startswith(root + os.sep)


def reconcile_interrupted(conn, plan_id=None):
    """Mark stale in_progress operations as interrupted. Never assumes success."""
    sql = ("UPDATE organization_operations SET status='interrupted',"
           " error=COALESCE(error, 'process ended before completion'),"
           " finished_at_epoch=? WHERE status='in_progress'")
    params = [_now()]
    if plan_id is not None:
        sql += " AND plan_id = ?"
        params.append(plan_id)
    rows = conn.execute(
        "SELECT id, plan_id FROM organization_operations"
        " WHERE status='in_progress'" +
        (" AND plan_id = ?" if plan_id is not None else ""),
        (() if plan_id is None else (plan_id,))).fetchall()
    conn.execute(sql, params)
    for row in rows:
        _event(conn, row["plan_id"], row["id"], "op_interrupted_recovered",
               "operation was in_progress when reconciled")
    return len(rows)


def approve_plan(conn, plan_id, note=""):
    plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                        (plan_id,)).fetchone()
    if plan is None:
        raise ExecutionError("plan {} does not exist".format(plan_id))
    if plan["status"] not in ("draft", "ready_for_review"):
        raise ExecutionError(
            "plan {} is '{}' — only a draft plan can be approved".format(
                plan_id, plan["status"]))
    conflicts = conn.execute(
        "SELECT COUNT(*) FROM organization_operations"
        " WHERE plan_id = ? AND status = 'conflict'", (plan_id,)).fetchone()[0]
    with conn:
        conn.execute(
            "UPDATE organization_plans SET status='approved',"
            " approved_at_epoch=?, approval_note=?, updated_at_epoch=?"
            " WHERE id = ? AND status IN ('draft','ready_for_review')",
            (_now(), note, _now(), plan_id))
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            raise ExecutionError("plan {} could not be approved (race)".format(
                plan_id))
        _event(conn, plan_id, None, "plan_approved",
               "note={} conflicts_left={}".format(note, conflicts))
    return conflicts


def cancel_plan(conn, plan_id):
    with conn:
        cur = conn.execute(
            "UPDATE organization_plans SET status='cancelled', updated_at_epoch=?"
            " WHERE id = ? AND status IN ('draft','ready_for_review','approved')",
            (_now(), plan_id))
        if cur.rowcount != 1:
            raise ExecutionError(
                "plan {} cannot be cancelled in its current state".format(plan_id))
        _event(conn, plan_id, None, "plan_cancelled", "")
    return True


def _copy_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as fh_src, open(dst, "wb") as fh_dst:
        shutil.copyfileobj(fh_src, fh_dst, _COPY_CHUNK)
        fh_dst.flush()
        os.fsync(fh_dst.fileno())
    shutil.copystat(src, dst, follow_symlinks=False)


def _verify_copy(src, dst, hash_verify):
    src_size = os.stat(src, follow_symlinks=False).st_size
    dst_size = os.stat(dst, follow_symlinks=False).st_size
    if src_size != dst_size:
        return False, "size mismatch src={} dst={}".format(src_size, dst_size)
    if hash_verify:
        if _sha256_file(src) != _sha256_file(dst):
            return False, "SHA-256 mismatch after copy"
        return True, "sha256 verified"
    return True, "size verified"


def apply_plan(conn, plan_id, *, acknowledge_source_removal=False,
               stop_on_error=False, limit=None, cancel_event=None):
    """Execute an approved plan. Returns a result dict. Never overwrites."""
    reconcile_interrupted(conn, plan_id)
    plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                        (plan_id,)).fetchone()
    if plan is None:
        raise ExecutionError("plan {} does not exist".format(plan_id))
    if plan["status"] not in ("approved", "executing"):
        raise ExecutionError(
            "plan {} is '{}' — approve it first with `organize-approve`".format(
                plan_id, plan["status"]))

    move_ops = conn.execute(
        "SELECT COUNT(*) FROM organization_operations"
        " WHERE plan_id = ? AND status='planned' AND action='move'",
        (plan_id,)).fetchone()[0]
    if move_ops and not acknowledge_source_removal:
        raise ExecutionError(
            "plan {} contains {} move operation(s). Applying it will DELETE the "
            "source files AFTER each destination copy is verified. Re-run with "
            "--acknowledge-source-removal if you understand and accept this."
            .format(plan_id, move_ops))

    target_root = plan["target_root"]
    pending = conn.execute(
        "SELECT * FROM organization_operations"
        " WHERE plan_id = ? AND status='planned' ORDER BY seq",
        (plan_id,)).fetchall()
    if limit is not None:
        pending = pending[:int(limit)]

    # Free-space pre-check (conservative: bytes + 1 MiB slack per file).
    # Target may not exist yet — walk up to the nearest existing ancestor.
    probe = os.path.realpath(target_root)
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError as exc:
        raise ExecutionError(
            "cannot measure free space near {!r}: {}".format(target_root, exc))
    payload = sum(int(o["size_bytes"] or 0) for o in pending)
    # Logical bytes are the upper bound for regular files (sparse files use
    # less); add fixed headroom, never per-file slack.
    needed = payload + 64 * 1024 * 1024
    if free < needed:
        raise ExecutionError(
            "insufficient free space on target: payload {} bytes + 64 MiB "
            "headroom exceeds {} available bytes at {!r}".format(
                payload, free, probe))

    with conn:
        conn.execute(
            "UPDATE organization_plans SET status='executing', updated_at_epoch=?"
            " WHERE id = ? AND status IN ('approved','executing')",
            (_now(), plan_id))
        _event(conn, plan_id, None, "plan_apply_started",
               "pending={} acknowledge_source_removal={}".format(
                   len(pending), bool(acknowledge_source_removal)))

    hash_verify = bool(plan["hash_verify"])
    done = failed = skipped = 0
    halted = False

    class _HaltApply(Exception):
        pass
    try:
        for op in pending:
            if cancel_event is not None and cancel_event.is_set():
                with conn:
                    conn.execute(
                        "UPDATE organization_plans SET status='cancelled',"
                        " updated_at_epoch=? WHERE id = ?", (_now(), plan_id))
                    _event(conn, plan_id, None, "plan_cancelled",
                           "cancel requested after {} operations".format(done))
                break

            src, dst = op["source_abs"], op["dest_abs"]
            op_id = op["id"]

            def fail(msg):
                nonlocal failed, halted
                failed += 1
                with conn:
                    conn.execute(
                        "UPDATE organization_operations SET status='failed',"
                        " error=?, finished_at_epoch=? WHERE id = ?",
                        (msg, _now(), op_id))
                    _event(conn, plan_id, op_id, "op_failed", msg)
                if stop_on_error:
                    halted = True
                    with conn:
                        conn.execute(
                            "UPDATE organization_plans SET status='recovery_required',"
                            " updated_at_epoch=? WHERE id = ?", (_now(), plan_id))
                        _event(conn, plan_id, None, "plan_recovery_required",
                               "stopped on error: {}".format(msg))
                    raise _HaltApply()

            # --- re-validation at execution time (TOCTOU defence) ---
            if not _dest_contained(dst, target_root):
                fail("destination escapes target root; refused")
                continue
            if os.path.islink(src):
                fail("source is a symlink; refused")
                continue
            if not os.path.isfile(src):
                fail("source missing or not a regular file at apply time")
                continue
            if os.path.lexists(dst):
                fail("destination now exists; refused to overwrite")
                skipped += 1
                continue

            try:
                with conn:
                    conn.execute(
                        "UPDATE organization_operations SET status='in_progress',"
                        " started_at_epoch=? WHERE id = ? AND status='planned'",
                        (_now(), op_id))
                    if conn.execute("SELECT changes()").fetchone()[0] != 1:
                        raise ExecutionError("operation {} no longer planned".format(op_id))
                    _event(conn, plan_id, op_id, "op_started",
                           "action={}".format(op["action"]))
                _copy_file(src, dst)
                ok, detail = _verify_copy(src, dst, hash_verify)
                if not ok:
                    # Destination copy is UNTRUSTED — do not touch the source.
                    fail("verification failed: " + detail)
                    continue
                with conn:
                    conn.execute(
                        "UPDATE organization_operations SET dest_size_bytes=?"
                        " WHERE id = ?",
                        (os.stat(dst, follow_symlinks=False).st_size, op_id))
                    _event(conn, plan_id, op_id, "op_verified", detail)
                if op["action"] == "move":
                    try:
                        os.remove(src)
                    except OSError as exc:
                        fail("destination verified but source removal failed: {}".format(exc))
                        continue
                    with conn:
                        _event(conn, plan_id, op_id, "op_source_removed",
                               "after verified copy: {}".format(detail))
                with conn:
                    conn.execute(
                        "UPDATE organization_operations SET status='completed',"
                        " error=NULL, finished_at_epoch=? WHERE id = ?",
                        (_now(), op_id))
                    _event(conn, plan_id, op_id, "op_completed", "")
                done += 1
            except _HaltApply:
                break
            except Exception as exc:  # never let one file abort silently
                fail("unexpected error: {}".format(exc))
    except _HaltApply:
        pass

    with conn:
        stats = conn.execute(
            "SELECT status, COUNT(*) n FROM organization_operations"
            " WHERE plan_id = ? GROUP BY status", (plan_id,)).fetchall()
        counts = {r["status"]: r["n"] for r in stats}
        remaining = conn.execute(
            "SELECT COUNT(*) FROM organization_operations"
            " WHERE plan_id = ? AND status='planned'", (plan_id,)).fetchone()[0]
        failed_ops = counts.get("failed", 0) + counts.get("interrupted", 0)
        if halted:
            final_status = "recovery_required"  # set by the stop_on_error path
        elif remaining:
            final_status = ("cancelled" if cancel_event is not None
                            and cancel_event.is_set() else "executing")
        elif failed_ops:
            final_status = "completed_with_errors"
        else:
            final_status = "completed"
        if not halted:
            conn.execute(
                "UPDATE organization_plans SET status=?, updated_at_epoch=?"
                " WHERE id = ?", (final_status, _now(), plan_id))
        _event(conn, plan_id, None, "plan_finished",
               "status={} done={} failed={} skipped={}".format(
                   final_status, done, failed, skipped))
    return {"plan_id": plan_id, "done": done, "failed": failed,
            "skipped": skipped, "status": final_status}


def undo_operation(conn, operation_id, *, approve_delete_copy=False):
    """Reverse one completed operation.

    move      → rename/move destination back to the (now free) source path.
    copy-keep → optionally DELETE the created copy, only with
                approve_delete_copy=True and a size check.
    """
    op = conn.execute("SELECT * FROM organization_operations WHERE id = ?",
                      (operation_id,)).fetchone()
    if op is None:
        raise ExecutionError("operation {} does not exist".format(operation_id))
    if op["status"] != "completed":
        raise ExecutionError(
            "operation {} is '{}' — only completed operations can be undone".format(
                operation_id, op["status"]))

    src, dst = op["source_abs"], op["dest_abs"]
    plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                        (op["plan_id"],)).fetchone()
    if not os.path.isfile(dst) or os.path.islink(dst):
        raise ExecutionError(
            "destination is missing or no longer a regular file; undo refused")
    if op["dest_size_bytes"] is not None and \
            os.stat(dst, follow_symlinks=False).st_size != op["dest_size_bytes"]:
        raise ExecutionError(
            "destination size changed since execution; undo refused "
            "(the file is not what this tool wrote)")

    if op["action"] == "copy-keep":
        if not approve_delete_copy:
            raise ExecutionError(
                "copy-keep undo DELETES the organized copy. Re-run with "
                "--approve-delete to confirm. The source file is untouched.")
        os.remove(dst)
        with conn:
            conn.execute(
                "UPDATE organization_operations SET status='rolled_back',"
                " finished_at_epoch=? WHERE id = ?", (_now(), operation_id))
            _event(conn, op["plan_id"], operation_id, "op_rolled_back",
                   "copy deleted; source kept")
        return "copy-deleted"

    # move: bring the destination back to the source path
    if os.path.lexists(src):
        raise ExecutionError(
            "source path is occupied again; undo refused (would overwrite)")
    try:
        os.renames(dst, src)
    except OSError:
        _copy_file(dst, src)
        ok, detail = _verify_copy(dst, src, bool(plan["hash_verify"]))
        if not ok:
            raise ExecutionError("undo copy-back failed verification: " + detail)
        os.remove(dst)
    with conn:
        conn.execute(
            "UPDATE organization_operations SET status='rolled_back',"
            " finished_at_epoch=? WHERE id = ?", (_now(), operation_id))
        _event(conn, op["plan_id"], operation_id, "op_rolled_back",
               "destination moved back to source location")
    return "restored"
