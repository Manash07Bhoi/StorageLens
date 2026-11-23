"""Scan orchestration: DB + traversal + counters + finalization."""

import json
import os
import shutil
import signal
import sys
import threading
import time

from . import __version__, SCHEMA_VERSION, config, database
from .filesystem import (
    ScanCancelled,
    collect_environment,
    scan_tree,
)
from .safety import (
    RootValidationError,
    check_output_location,
    validate_scan_root,
)


class ScanResult(dict):
    """Plain dict subclass for clarity; keys documented in docs/ARCHITECTURE.md."""


def make_cancel_event():
    return threading.Event()


def install_signal_handlers(cancel_event):
    """SIGINT/SIGTERM request graceful cancellation. Returns previous handlers."""
    previous = {}

    def handler(signum, _frame):
        if not cancel_event.is_set():
            cancel_event.set()
            sys.stderr.write(
                "\nCancellation requested (signal {}). Finishing the current "
                "batch and committing collected records…\n".format(signum))
            sys.stderr.flush()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):
            pass  # not in main thread or unsupported: cancellation via event only
    return previous


def run_scan(root_requested, *, db_path, output_dir, batch_size=config.DEFAULT_BATCH_SIZE,
             progress=True, cancel_event=None, logger=None):
    """Execute a read-only inventory scan. Returns a ScanResult dict.

    Raises RootValidationError / safety errors for configuration problems
    (before any run row is created). Unexpected internal errors mark the run
    failed and propagate.
    """
    logger = logger or _NullLogger()

    if not (config.MIN_BATCH_SIZE <= int(batch_size) <= config.MAX_BATCH_SIZE):
        raise RootValidationError(
            "Batch size must be between {} and {} (got {}).".format(
                config.MIN_BATCH_SIZE, config.MAX_BATCH_SIZE, batch_size))

    canonical_root, root_info = validate_scan_root(root_requested)
    output_dir_abs = os.path.realpath(os.path.expanduser(output_dir))

    ok, output_message, exclusion_rel = check_output_location(output_dir_abs,
                                                              canonical_root)
    if not ok:
        raise RootValidationError(output_message)

    try:
        os.makedirs(output_dir_abs, exist_ok=True)
        reports_dir = os.path.join(output_dir_abs, config.REPORT_SUBDIR)
        logs_dir = os.path.join(output_dir_abs, config.LOG_SUBDIR)
        os.makedirs(reports_dir, exist_ok=True)
        os.makedirs(logs_dir, exist_ok=True)
    except OSError as exc:
        raise RootValidationError(
            "Output directory is not writable: {} ({})".format(output_dir_abs, exc)) from exc

    exclusions = []
    if exclusion_rel:
        exclusions.append(exclusion_rel)

    # Database files inside the scan root would be scanned while we write them.
    # Exclude the DB and its SQLite sidecars exactly (recorded on the run).
    from .safety import is_within
    db_canonical = os.path.realpath(db_path)
    if is_within(db_canonical, canonical_root):
        rel_db = os.path.relpath(db_canonical, canonical_root)
        exclusions.append(rel_db)
        exclusions.append(rel_db + "-wal")
        exclusions.append(rel_db + "-shm")
        exclusions.append(rel_db + "-journal")

    db_dir = os.path.dirname(db_canonical)
    try:
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    except OSError as exc:
        raise RootValidationError(
            "Database directory is not writable: {} ({})".format(db_dir, exc)) from exc

    conn = database.connect(db_path)
    try:
        database.migrate(conn)
        marked, uncertain = database.mark_interrupted_runs(conn)
        for run_id in marked:
            logger.warning(
                "Marked stale run %s as interrupted_or_recovered (process ended).",
                run_id)
        for run_id, why in uncertain:
            logger.warning(
                "Run %s is still marked 'running'; liveness could not be ruled out (%s).",
                run_id, why)

        # Volume metrics (best effort; explicitly marked when unavailable).
        volume_total = volume_used = volume_free = None
        volume_status = "unavailable"
        try:
            usage = shutil.disk_usage(canonical_root)
            volume_total, volume_free = int(usage.total), int(usage.free)
            volume_used = int(usage.total) - int(usage.free)
            volume_status = "observed"
        except OSError as exc:
            volume_status = "unavailable: {}".format(exc.errno or "os_error")

        root_stat = os.lstat(canonical_root)
        environment = collect_environment(root_stat)

        run_id = database.create_run(
            conn, requested_root=str(root_requested),
            root_path=canonical_root, tool_version=__version__,
            environment=environment, exclusions=exclusions,
            batch_size=int(batch_size))

        batch, issue_batch = [], []
        state_holder = {}

        def on_entry(row):
            batch.append(row)
            if len(batch) >= int(batch_size):
                _flush_batch(conn, run_id, batch, issue_batch)

        def on_issue(issue):
            issue_batch.append(issue)
            if len(issue_batch) >= int(batch_size):
                _flush_issues(conn, run_id, issue_batch)

        started_wall = time.time()
        status = database.STATUS_COMPLETED
        failure_note = None
        try:
            state_holder["state"] = scan_tree(
                canonical_root, exclusions_rel=exclusions,
                cancel_event=cancel_event, progress=progress,
                on_entry=on_entry, on_issue=on_issue)
        except ScanCancelled as exc:
            status = database.STATUS_CANCELLED
            state_holder["state"] = getattr(exc, "state", None)
        except Exception as exc:  # unexpected internal error: mark failed, preserve data
            status = database.STATUS_FAILED
            failure_note = "{}: {}".format(type(exc).__name__, exc)
            logger.error("Scan failed unexpectedly: %s", failure_note)

        _flush_batch(conn, run_id, batch, issue_batch)  # flushes remainders

        finished_wall = time.time()
        duration = finished_wall - started_wall

        # Integrity gate before any completion claim.
        ok_integrity, integrity_messages = database.integrity_check(conn)
        if not ok_integrity and status != database.STATUS_FAILED:
            status = database.STATUS_FAILED
            failure_note = ("SQLite integrity_check reported problems: {}".format(
                "; ".join(integrity_messages)))
            logger.error(failure_note)

        # Reconcile counters: persisted entries are the source of truth for
        # recorded counts; traversal state is the source of truth for excluded.
        counters = _reconcile_counters(conn, run_id)
        traversal_state = state_holder.get("state")
        if traversal_state is not None:
            counters["excluded_count"] = int(traversal_state.get("excluded", 0))
            counters["directories_seen"] = int(
                traversal_state.get("directories_seen",
                                    counters["directories_recorded"]))
        issue_count = counters.pop("errors_count")
        skipped = counters.pop("skipped_count")
        excluded = counters.pop("excluded_count")
        database.update_counters(conn, run_id, counters)

        coverage_incomplete = 1 if (issue_count or skipped or
                                    status != database.STATUS_COMPLETED) else 0
        if status == database.STATUS_COMPLETED and coverage_incomplete:
            status = database.STATUS_COMPLETED_WITH_GAPS

        coverage_notes = _coverage_notes(conn, run_id, issue_count, skipped,
                                         excluded, status, failure_note)

        database.transition_run(
            conn, run_id, status,
            finished_at_epoch=int(finished_wall),
            duration_seconds=duration,
            errors_count=issue_count,
            skipped_count=skipped,
            excluded_count=excluded,
            volume_total_bytes=volume_total,
            volume_used_bytes=volume_used,
            volume_free_bytes=volume_free,
            volume_status=volume_status,
            coverage_incomplete=coverage_incomplete,
            coverage_notes=coverage_notes)

        from .analytics import compute_directory_stats
        compute_directory_stats(conn, run_id)

        result = ScanResult(
            run_id=run_id,
            status=status,
            root=canonical_root,
            requested_root=str(root_requested),
            duration_seconds=duration,
            output_dir=output_dir_abs,
            db_path=os.path.realpath(db_path),
            exclusions=exclusions,
            coverage_incomplete=coverage_incomplete,
            coverage_notes=coverage_notes,
            volume_status=volume_status,
            integrity_ok=ok_integrity,
        )
        result.update({k: int(v) for k, v in counters.items()})
        result["errors_count"] = int(issue_count)
        result["skipped_count"] = int(skipped)
        result["excluded_count"] = int(excluded)
        return result
    finally:
        conn.close()


def _flush_batch(conn, run_id, batch, issue_batch):
    if batch:
        for row in batch:
            row["scan_id"] = run_id
        database.insert_entries(conn, batch)
        batch.clear()
    _flush_issues(conn, run_id, issue_batch)


def _flush_issues(conn, run_id, issue_batch):
    if not issue_batch:
        return
    for issue in issue_batch:
        database.insert_issue(
            conn, run_id, path=issue["path"], operation=issue["operation"],
            error_category=issue["error_category"],
            error_code=issue.get("error_code"),
            error_message=issue["error_message"])
    issue_batch.clear()


def _reconcile_counters(conn, run_id):
    row = conn.execute(
        "SELECT"
        "  SUM(CASE WHEN kind='file' AND stat_status='ok' THEN 1 ELSE 0 END) AS files_recorded,"
        "  SUM(CASE WHEN kind='file' THEN 1 ELSE 0 END) AS files_seen,"
        "  SUM(CASE WHEN kind='directory' THEN 1 ELSE 0 END) AS directories_recorded,"
        "  SUM(CASE WHEN kind='symlink' THEN 1 ELSE 0 END) AS symlinks_seen,"
        "  SUM(CASE WHEN kind IN ('other','unknown') THEN 1 ELSE 0 END) AS other_entries_seen,"
        "  SUM(CASE WHEN stat_status='failed' THEN 1 ELSE 0 END) AS failed_entries,"
        "  SUM(CASE WHEN skip_reason IS NOT NULL THEN 1 ELSE 0 END) AS skipped_count,"
        "  SUM(CASE WHEN kind='directory' THEN 1 ELSE 0 END) AS dir_count"
        " FROM entries WHERE scan_id = ?", (run_id,)).fetchone()
    issues = conn.execute(
        "SELECT COUNT(*) FROM scan_issues WHERE scan_id = ?", (run_id,)).fetchone()[0]
    return {
        "files_seen": row["files_seen"] or 0,
        "files_recorded": row["files_recorded"] or 0,
        "directories_seen": row["directories_recorded"] or 0,
        "directories_recorded": row["directories_recorded"] or 0,
        "symlinks_seen": row["symlinks_seen"] or 0,
        "other_entries_seen": row["other_entries_seen"] or 0,
        "errors_count": int(issues),
        "skipped_count": row["skipped_count"] or 0,
        "excluded_count": 0,  # caller overwrites with traversal state when known
    }


def _coverage_notes(conn, run_id, issue_count, skipped, excluded, status,
                    failure_note):
    notes = []
    if failure_note:
        notes.append(failure_note)
    if status == database.STATUS_CANCELLED:
        notes.append("Scan was cancelled by the user; coverage is partial.")
    if issue_count:
        ops = conn.execute(
            "SELECT operation, COUNT(*) AS n FROM scan_issues WHERE scan_id = ?"
            " GROUP BY operation ORDER BY n DESC", (run_id,)).fetchall()
        notes.append("Issues: " + ", ".join(
            "{} {}".format(r["n"], r["operation"]) for r in ops))
    if skipped:
        notes.append("{} entr{} skipped (e.g. mount boundary), not crossed.".format(
            skipped, "y" if skipped == 1 else "ies"))
    if excluded:
        notes.append("{} path(s) excluded (output location inside scan root).".format(excluded))
    if not notes:
        notes.append("No issues observed within the accessible tree.")
    return "; ".join(notes)


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass
