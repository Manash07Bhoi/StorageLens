"""Command-line interface: argparse subcommands, predictable exit codes.

Exit codes:
  0  success
  1  internal error (bug); scan marked failed in DB if possible
  2  usage / configuration / permission error
  3  scan incomplete (cancelled or failed after start)
  4  interrupted run detected and marked on this invocation (check)
"""

import argparse
import os
import sys
import time
from datetime import datetime

from . import __version__, MIN_PYTHON, SCHEMA_VERSION, config
from . import database
from .analytics import run_record
from .environment import gather_check_info, resolve_default_root
from .logging_config import setup_logging
from .safety import RootValidationError, validate_scan_root

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_INCOMPLETE = 3
EXIT_INTERRUPTED_FOUND = 4


def default_state_dir():
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, config.APP_DIR_NAME)
    return os.path.join(os.path.expanduser("~"), config.DEFAULT_STATE_DIR)


def default_db_path():
    return os.path.join(default_state_dir(), config.DB_FILENAME)


def human_bytes(n):
    if n is None:
        return "unavailable"
    size = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return ("{} B".format(int(size)) if unit == "B"
                    else "{:.2f} {}".format(size, unit))
        size /= 1024.0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="storage_audit.py",
        description="Android Storage Audit — read-only inventory of accessible "
                    "shared internal storage (Termux), plus an OPT-IN V2 organization "
                    "engine restricted to ONE explicitly selected, user-owned folder. "
                    "The scan never modifies, moves, renames or deletes source files. "
                    "V2 'organize-*' commands change files ONLY after an explicit, "
                    "logged approval, never overwrite existing files, and NEVER touch "
                    "Android/, system, application-private, Termux-private, hidden or "
                    "reserved locations (policy org-scope-1). No network access.",
        epilog="Environment variables: STORAGE_AUDIT_ROOT (default scan root), "
               "XDG_DATA_HOME (state directory base).")
    parser.add_argument("--version", action="version",
                        version="Android Storage Audit {} (schema {})".format(
                            __version__, SCHEMA_VERSION))
    parser.add_argument("--db", default=None,
                        help="SQLite database path (default: XDG_DATA_HOME/android-storage-audit/storage_audit.sqlite3 or ~/.local/share/android-storage-audit/storage_audit.sqlite3)")
    parser.add_argument("--output-dir", default=None,
                        help="Output directory for reports (default: state dir)")
    parser.add_argument("--verbose", action="store_true",
                        help="Debug logging (includes full paths in the log file)")
    parser.add_argument("--quiet", action="store_true",
                        help="Only errors on the console")

    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p_check = sub.add_parser("check", help="Verify environment and permissions")
    p_check.add_argument("--root", default=None,
                         help="Candidate scan root (default: ~/storage/shared "
                              "or $STORAGE_AUDIT_ROOT)")

    p_scan = sub.add_parser("scan", help="Run the read-only inventory scan")
    p_scan.add_argument("--root", default=None,
                        help="Scan root (default: ~/storage/shared or "
                             "$STORAGE_AUDIT_ROOT)")
    p_scan.add_argument("--batch-size", type=int, default=config.DEFAULT_BATCH_SIZE,
                        help="DB commit batch size, {}–{} (default: {})".format(
                            config.MIN_BATCH_SIZE, config.MAX_BATCH_SIZE,
                            config.DEFAULT_BATCH_SIZE))
    p_scan.add_argument("--i-know-this-is-broad", action="store_true",
                        help="Required when the canonical root is '/' or your home "
                             "directory (unusually broad scope).")

    p_report = sub.add_parser("report", help="(Re)build the HTML report from an "
                                             "existing scan — no rescanning")
    target = p_report.add_mutually_exclusive_group()
    target.add_argument("--latest", action="store_true",
                        help="Use the most recent run with a terminal status")
    target.add_argument("--scan-id", type=int, default=None,
                        help="Use a specific scan run id")
    p_report.add_argument("--fixture-label", action="store_true",
                          help=argparse.SUPPRESS)  # test/demo labelling only

    p_list = sub.add_parser("list-runs", help="List past scan runs")
    p_list.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show-run", help="Show counters for one run id")
    p_show.add_argument("scan_id", type=int)

    p_oplan = sub.add_parser("organize-plan",
                             help="V2: build a DRAFT plan for ONE explicitly selected, "
                                  "user-owned folder (Android/ and system locations are "
                                  "never permitted)")
    p_oplan.add_argument("--scan-id", type=int, default=None,
                         help="Scan run id (default: latest completed run). The scan is "
                              "provenance only — files are discovered by walking the "
                              "selected folder, never by unverified scan rows.")
    p_oplan.add_argument("--scope", "--target", dest="target", required=True,
                         help="The ONE user-owned folder to organize (e.g. "
                              "'~/storage/shared/Documents'). Only files inside this "
                              "folder are planned; Android/, system, Termux-private, "
                              "hidden and reserved content is default-deny.")
    p_oplan.add_argument("--rule", default="by-category", choices=["by-category"])
    p_oplan.add_argument("--action", default="copy-keep", choices=["copy-keep", "move"],
                         help="copy-keep (default) never deletes; move removes sources "
                              "only after verified copies")
    p_oplan.add_argument("--hash-verify", action="store_true",
                         help="Verify copies with SHA-256 (reads file contents; slower). "
                              "Default verifies size+mtime only.")

    p_oprev = sub.add_parser("organize-preview", help="V2: write an offline HTML preview of a plan")
    p_oprev.add_argument("--plan-id", type=int, required=True)
    p_oprev.add_argument("--output", default=None, help="Explicit output HTML path")

    p_oapp = sub.add_parser("organize-approve", help="V2: approve a draft plan (required before apply)")
    p_oapp.add_argument("--plan-id", type=int, required=True)
    p_oapp.add_argument("--note", default=None)
    p_oapp.add_argument("--yes", action="store_true",
                        help="Skip the interactive APPROVE confirmation (for scripts/tests)")

    p_oapply = sub.add_parser("organize-apply", help="V2: execute an APPROVED plan")
    p_oapply.add_argument("--plan-id", type=int, required=True)
    p_oapply.add_argument("--acknowledge-source-removal", action="store_true",
                          help="Required for move plans: sources are deleted ONLY after "
                               "their destinations are verified")
    p_oapply.add_argument("--stop-on-error", action="store_true")
    p_oapply.add_argument("--limit", type=int, default=None,
                          help="Apply only the first N pending operations")

    p_ohist = sub.add_parser("organize-history", help="V2: list organization plans")
    p_ohist.add_argument("--limit", type=int, default=20)

    p_oshow = sub.add_parser("organize-show", help="V2: show one organization plan")
    p_oshow.add_argument("--plan-id", type=int, required=True)

    p_oundo = sub.add_parser("organize-undo", help="V2: undo one completed operation")
    p_oundo.add_argument("--operation-id", type=int, required=True)
    p_oundo.add_argument("--approve-delete", action="store_true",
                         help="For copy-keep operations: delete the created copy "
                              "(the untouched source stays)")

    p_ocan = sub.add_parser("organize-cancel", help="V2: cancel a draft/approved plan")
    p_ocan.add_argument("--plan-id", type=int, required=True)

    parser.set_defaults(command=None)
    return parser


def _resolve_paths(args):
    state_dir = default_state_dir()
    db_path = args.db or default_db_path()
    output_dir = args.output_dir or state_dir
    return state_dir, db_path, output_dir


def _make_logger(state_dir, verbose, quiet):
    try:
        return setup_logging(os.path.join(state_dir, config.LOG_SUBDIR),
                             verbose=verbose, quiet=quiet)
    except OSError:
        import logging
        logger = logging.getLogger("storage_audit")
        logger.addHandler(logging.NullHandler())
        return logger


def cmd_check(args, state_dir, db_path, output_dir):
    info = gather_check_info(state_dir, db_path, args.root)
    env = info["environment"]
    print("Android Storage Audit {} — environment check".format(info["tool_version"]))
    print("=" * 60)
    print("Python:            {} (minimum {})  {}".format(
        info["python_version"], info["min_python"],
        "OK" if info["python_ok"] else "TOO OLD"))
    print("Platform:          {} {} {}".format(
        env["platform_system"], env["platform_release"], env["platform_machine"]))
    print("Termux detected:   {}".format("yes" if env["is_termux"] else "no"))
    print("Termux version:    {}".format(env["termux_version"]))
    print("Android release:   {} (SDK {})".format(env["android_release"], env["android_sdk"]))
    print("SQLite:            {}".format(info["sqlite_version"]))
    print("-" * 60)
    print("Requested root:    {}".format(info["requested_root"]))
    print("Canonical root:    {}".format(info["canonical_root"]))
    print("Root exists:       {}".format(info["root_exists"]))
    print("Root is directory: {}".format(info["root_is_dir"]))
    print("Root listable:     {}".format(info["root_listable"]))
    if info["root_error"]:
        print("Root error:        {}".format(info["root_error"]))
    print("Output directory:  {} (writable: {})".format(
        info["state_dir"], info["state_dir_writable"]))
    print("Database path:     {}".format(db_path))
    if info["output_inside_root"]:
        print("WARNING: output directory is inside the scan root; it would be "
              "excluded from the scan (or use a different --output-dir).")
    volume = info["volume"]
    if volume.get("status") == "observed":
        print("Volume:            {} total, {} used, {} free".format(
            human_bytes(volume["total"]), human_bytes(volume["used"]),
            human_bytes(volume["free"])))
    else:
        print("Volume:            unavailable ({})".format(volume.get("status")))

    print("-" * 60)
    ok = (info["python_ok"] and info["root_is_dir"] and info["root_listable"]
          and info["state_dir_writable"])

    # Stale-run detection for honest status reporting.
    interrupted = False
    if os.path.exists(db_path):
        conn = database.connect(db_path)
        try:
            database.migrate(conn)
            marked, uncertain = database.mark_interrupted_runs(conn)
            if marked:
                interrupted = True
                print("NOTE: marked stale run(s) as interrupted_or_recovered: {}".format(
                    ", ".join(str(m) for m in marked)))
            for run_id, why in uncertain:
                print("WARNING: run {} still marked 'running' ({}); not changed.".format(
                    run_id, why))
        finally:
            conn.close()

    if not info["is_termux"]:
        print("NOTE: this is NOT a Termux/Android environment. The tool works, but "
              "results here do NOT validate Android behavior. Run on-device with "
              "'termux-setup-storage' first.")
    if ok:
        print("RESULT: ready. Next: python storage_audit.py scan")
        return EXIT_INTERRUPTED_FOUND if interrupted else EXIT_OK
    print("RESULT: NOT ready.")
    if not info["root_is_dir"] or not info["root_listable"]:
        print("Fix: run 'termux-setup-storage' in Termux, grant the storage "
              "permission, then confirm ~/storage/shared exists and is listable.")
    if not info["python_ok"]:
        print("Fix: install a newer Python (pkg install python in Termux).")
    if not info["state_dir_writable"]:
        print("Fix: choose a writable --output-dir / XDG_DATA_HOME.")
    return EXIT_USAGE


def cmd_scan(args, state_dir, db_path, output_dir):
    from .scanner import install_signal_handlers, make_cancel_event, run_scan

    root = args.root or resolve_default_root()
    logger = _make_logger(state_dir, args.verbose, args.quiet)

    # Broad-scope guard for '/' and $HOME.
    from .safety import canonicalize, is_within  # local import to keep top tidy
    canonical = canonicalize(root)
    home = os.path.expanduser("~")
    if not args.i_know_this_is_broad and (
            canonical == os.path.sep or canonical == os.path.normpath(home)):
        print("Refusing unusually broad root: {}\n"
              "Re-run with --i-know-this-is-broad if you truly want this scope.".format(
                  canonical), file=sys.stderr)
        return EXIT_USAGE

    try:
        canonical_root, root_info = validate_scan_root(root)
    except RootValidationError as exc:
        print("Cannot scan: {}\n".format(exc), file=sys.stderr)
        return EXIT_USAGE

    excluded_note = ""
    from .safety import check_output_location
    ok, message, exclusion_rel = check_output_location(output_dir, canonical_root)
    if not ok:
        print("Cannot scan: {}".format(message), file=sys.stderr)
        return EXIT_USAGE
    if exclusion_rel:
        excluded_note = (" (inside scan root — will be EXCLUDED from the scan: {})"
                         .format(exclusion_rel))

    if not args.quiet:
        print("About to run a READ-ONLY inventory scan.")
        print("  Root:            {}".format(canonical_root))
        print("  Database:        {}".format(db_path))
        print("  Reports:         {}{}".format(output_dir, excluded_note))
        print("  No files will be renamed, moved, modified, compressed or deleted.")
        print("  File contents will NOT be read; no hashes will be calculated.")
        print("  Hidden entries are included; symlinks are recorded, never followed.")
        print("  Ctrl+C cancels gracefully; collected records are kept and the run is")
        print("  marked 'cancelled' (never shown as a completed scan).")
        print()

    cancel_event = make_cancel_event()
    install_signal_handlers(cancel_event)

    try:
        result = run_scan(root, db_path=db_path, output_dir=output_dir,
                          batch_size=args.batch_size,
                          progress=not args.quiet,
                          cancel_event=cancel_event,
                          logger=logger)
    except RootValidationError as exc:
        print("Cannot scan: {}".format(exc), file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:  # internal error
        print("Internal error during scan: {}: {}".format(
            type(exc).__name__, exc), file=sys.stderr)
        return EXIT_INTERNAL

    print()
    print("Scan run #{} finished with status: {}".format(result["run_id"], result["status"]))
    print("  Files inventoried:   {}".format(result.get("files_recorded")))
    print("  Directories:         {}".format(result.get("directories_recorded")))
    print("  Symlinks:            {}".format(result.get("symlinks_seen")))
    print("  Inventoried bytes:   {} (logical)".format(
        human_bytes(_run_bytes(db_path, result["run_id"]))))
    print("  Scan issues:         {}".format(result.get("errors_count")))
    print("  Coverage complete:   {}".format("yes" if not result["coverage_incomplete"] else "NO — see coverage notes"))
    print("  Coverage notes:      {}".format(result["coverage_notes"]))
    print("  Database:            {}".format(result["db_path"]))
    print("  Duration:            {:.1f}s".format(result["duration_seconds"]))
    print()
    print("Next: python storage_audit.py report --latest")

    if result["status"] in (database.STATUS_COMPLETED,
                            database.STATUS_COMPLETED_WITH_GAPS):
        return EXIT_OK
    return EXIT_INCOMPLETE


def _run_bytes(db_path, run_id):
    conn = database.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(size_bytes),0) FROM entries"
            " WHERE scan_id = ? AND kind='file' AND size_status='observed'",
            (run_id,)).fetchone()
        return int(row[0])
    finally:
        conn.close()


def cmd_report(args, state_dir, db_path, output_dir):
    logger = _make_logger(state_dir, args.verbose, args.quiet)
    if not os.path.exists(db_path):
        print("Database not found: {}\nRun: python storage_audit.py scan".format(
            db_path), file=sys.stderr)
        return EXIT_USAGE

    from .report_builder import build_report
    conn = database.connect(db_path)
    try:
        database.migrate(conn)
        database.mark_interrupted_runs(conn)
        run = None
        if args.scan_id is not None:
            run = database.get_run(conn, args.scan_id)
            if run is None:
                print("Scan run #{} not found. Refusing to substitute another run."
                      .format(args.scan_id), file=sys.stderr)
                return EXIT_USAGE
        else:
            run = database.latest_run(
                conn, statuses=[database.STATUS_COMPLETED,
                                database.STATUS_COMPLETED_WITH_GAPS,
                                database.STATUS_CANCELLED,
                                database.STATUS_FAILED,
                                database.STATUS_INTERRUPTED])
            if run is None:
                print("No terminal scan runs found. Run: python storage_audit.py scan",
                      file=sys.stderr)
                return EXIT_USAGE
            print("Using latest terminal run: #{} ({})".format(run["id"], run["status"]))

        status = run["status"]
        if status in (database.STATUS_RUNNING,):
            print("Run #{} is still marked running; refusing to build a report.".format(
                run["id"]), file=sys.stderr)
            return EXIT_USAGE

        try:
            result = build_report(conn, run["id"], output_dir,
                                  fixture_label=args.fixture_label,
                                  logger=logger)
        except Exception as exc:
            database.set_report_state(conn, run["id"], "failed")
            try:
                database.record_report_build(
                    conn, run["id"], started_at=time.time(),
                    finished_at=time.time(), status="failed",
                    output_dir=None, file_count=0,
                    notes="{}: {}".format(type(exc).__name__, exc))
            except database.DatabaseError:
                pass
            print("Report build FAILED: {}: {}\nThe scan data is intact; fix the "
                  "error and re-run 'report'.".format(
                      type(exc).__name__, exc), file=sys.stderr)
            return EXIT_INTERNAL

        print()
        print("Report built for run #{} ({})".format(run["id"], status))
        print("  Directory:      {}".format(result["report_dir"]))
        print("  Open:           {}/index.html".format(result["report_dir"]))
        print("  Inventory rows: {} ({})".format(
            result["inventory_records"],
            "chunked JS data" if result["chunked_search_data"] else "inline data"))
        print("  Static file pages: {} (500 rows/page)".format(
            result["static_file_pages"]))
        print("  Exports:        {}".format(result["exports_dir"]))
        if status != database.STATUS_COMPLETED:
            print()
            print("NOTE: status is '{}' — the report is marked incomplete and "
                  "incomplete banners appear on every page.".format(status))
        return EXIT_OK
    finally:
        conn.close()


def _open_db(db_path):
    if not os.path.exists(db_path):
        print("No database yet at {}".format(db_path), file=sys.stderr)
        return None
    conn = database.connect(db_path)
    database.migrate(conn)
    return conn


def _latest_terminal_scan(conn):
    row = conn.execute(
        "SELECT id FROM scan_runs WHERE status IN"
        " ('completed','completed_with_gaps') ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def cmd_organize_plan(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        from storage_audit import organizer
        scan_id = args.scan_id if args.scan_id is not None else _latest_terminal_scan(conn)
        if scan_id is None:
            print("No completed scan found — run `scan` first.", file=sys.stderr)
            return EXIT_USAGE
        if not args.target:
            print("--target is required (a folder OUTSIDE the scan, or a new "
                  "'Organized' folder inside it). Nothing is created yet.",
                  file=sys.stderr)
            return EXIT_USAGE
        plan_id, stats = organizer.build_plan(
            conn, scan_id, args.target, rule=args.rule, action=args.action,
            hash_verify=args.hash_verify)
        print("Organization plan #{} created (DRAFT — nothing has been changed)".format(plan_id))
        print("  Selection:       {} (policy {})".format(
            stats["target_root"], stats["scope_policy_version"]))
        print("  Source scan:     #{}  | rule: {} | action: {}".format(
            scan_id, args.rule, stats["action"]))
        print("  Eligible files:  {}".format(stats["eligible_files"]))
        print("  Excluded:        {} entries (protected/hidden/reserved boundary)".format(
            stats["excluded_entries"]))
        print("  Operations:      {}  ({} bytes, {} conflicts, {} skipped)".format(
            stats["operations"], stats["total_bytes"], stats["conflicts"],
            stats["skipped"]))
        print("  Scope policy:    Android/, system, Termux-private, hidden and reserved")
        print("                   content is default-deny and will never be touched.")
        print("  Next: python storage_audit.py organize-preview --plan-id {}".format(plan_id))
        return EXIT_OK
    except organizer.ScopeRejected as exc:
        print("Organization unavailable: this location is protected or outside "
              "the permitted user-data scope.", file=sys.stderr)
        for reason in exc.validation["reasons"]:
            print("  - {}".format(reason), file=sys.stderr)
        print("Select a personal folder instead (e.g. Documents, Download, "
              "Pictures). There is no override.", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:
        print("Could not create plan: {}".format(exc), file=sys.stderr)
        return EXIT_INTERNAL
    finally:
        conn.close()


def cmd_organize_preview(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        from storage_audit.organizer import preview as preview_mod
        out = args.output or os.path.join(output_dir, config.REPORT_SUBDIR,
                                          "plan_{}.html".format(args.plan_id))
        path = preview_mod.write_plan_preview(conn, args.plan_id, out)
        print("Plan preview written: {}".format(path))
        print("Open it in your Android browser — it is fully offline.")
        return EXIT_OK
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    finally:
        conn.close()


def cmd_organize_approve(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        from storage_audit.organizer import executor
        plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                            (args.plan_id,)).fetchone()
        if plan is None:
            print("Plan #{} not found.".format(args.plan_id), file=sys.stderr)
            return EXIT_USAGE
        conflicts = conn.execute(
            "SELECT COUNT(*) FROM organization_operations"
            " WHERE plan_id = ? AND status='conflict'",
            (args.plan_id,)).fetchone()[0]
        try:
            eligible = plan["eligible_files"]
            excluded = plan["excluded_entries"]
            policy = plan["scope_policy_version"] or "(pre-2.1.0 plan)"
        except KeyError:
            eligible = excluded = None
            policy = "(pre-2.1.0 plan)"
        print("Plan #{}: {} operations, {} bytes, action={}, conflicts={}".format(
            plan["id"], plan["total_operations"], plan["total_bytes"],
            plan["action"], conflicts))
        print("  Approved scope: {} (policy {})".format(plan["target_root"], policy))
        if eligible is not None:
            print("  Eligible files: {} | Excluded entries: {}".format(
                eligible, excluded))
        if plan["action"] == "move":
            print("WARNING: this is a MOVE plan — sources will be DELETED after "
                  "verified copies.")
        if not args.yes:
            reply = input("Type APPROVE to approve this plan: ").strip()
            if reply != "APPROVE":
                print("Not approved.", file=sys.stderr)
                return EXIT_USAGE
        executor.approve_plan(conn, args.plan_id, note=args.note or "")
        print("Plan #{} approved.".format(args.plan_id))
        return EXIT_OK
    except Exception as exc:
        print("Approval failed: {}".format(exc), file=sys.stderr)
        return EXIT_INTERNAL
    finally:
        conn.close()


def cmd_organize_apply(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        from storage_audit import organizer
        result = organizer.apply_plan(
            conn, args.plan_id,
            acknowledge_source_removal=args.acknowledge_source_removal,
            stop_on_error=args.stop_on_error,
            limit=args.limit)
        print("Plan #{} finished with status: {}".format(
            args.plan_id, result["status"]))
        print("  done={} failed={} skipped={}".format(
            result["done"], result["failed"], result["skipped"]))
        return EXIT_OK if result["failed"] == 0 else EXIT_INCOMPLETE
    except Exception as exc:
        print("Apply refused/failed: {}".format(exc), file=sys.stderr)
        return EXIT_INTERNAL
    finally:
        conn.close()


def cmd_organize_history(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        rows = conn.execute(
            "SELECT id, scan_id, rule_name, action, status, total_operations,"
            " total_bytes, created_at_epoch FROM organization_plans"
            " ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
        if not rows:
            print("No organization plans yet.")
            return EXIT_OK
        print("{:<4} {:<6} {:<12} {:<10} {:<22} {:>5} {:>12}  Created".format(
            "ID", "Scan", "Rule", "Action", "Status", "Ops", "Bytes"))
        for r in rows:
            ts = datetime.fromtimestamp(r["created_at_epoch"]).astimezone().strftime(
                "%Y-%m-%d %H:%M")
            print("{:<4} {:<6} {:<12} {:<10} {:<22} {:>5} {:>12}  {}".format(
                r["id"], r["scan_id"], r["rule_name"], r["action"], r["status"],
                r["total_operations"], human_bytes(r["total_bytes"]), ts))
        return EXIT_OK
    finally:
        conn.close()


def cmd_organize_show(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                            (args.plan_id,)).fetchone()
        if plan is None:
            print("Plan #{} not found.".format(args.plan_id), file=sys.stderr)
            return EXIT_USAGE
        print("Organization plan #{}".format(plan["id"]))
        for key in ("scan_id", "rule_name", "rule_version", "target_root",
                    "action", "hash_verify", "status", "total_operations",
                    "total_bytes", "conflicts", "created_at_epoch",
                    "approved_at_epoch", "approval_note",
                    "eligible_files", "excluded_entries",
                    "scope_policy_version", "scope_canonical"):
            try:
                print("  {:<20} {}".format(key + ":", plan[key]))
            except KeyError:
                pass
        counts = conn.execute(
            "SELECT status, COUNT(*) n FROM organization_operations"
            " WHERE plan_id = ? GROUP BY status", (args.plan_id,)).fetchall()
        print("  Operations by status:")
        for r in counts:
            print("    {:<16} {}".format(r["status"], r["n"]))
        return EXIT_OK
    finally:
        conn.close()


def cmd_organize_undo(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        from storage_audit.organizer import executor
        result = executor.undo_operation(
            conn, args.operation_id,
            approve_delete_copy=args.approve_delete)
        print("Operation #{} undone: {}".format(args.operation_id, result))
        return EXIT_OK
    except Exception as exc:
        print("Undo refused: {}".format(exc), file=sys.stderr)
        return EXIT_INTERNAL
    finally:
        conn.close()


def cmd_organize_cancel(args, state_dir, db_path, output_dir):
    conn = _open_db(db_path)
    if conn is None:
        return EXIT_USAGE
    try:
        from storage_audit.organizer import executor
        executor.cancel_plan(conn, args.plan_id)
        print("Plan #{} cancelled.".format(args.plan_id))
        return EXIT_OK
    except Exception as exc:
        print("Cancel refused: {}".format(exc), file=sys.stderr)
        return EXIT_INTERNAL
    finally:
        conn.close()

def cmd_list_runs(args, state_dir, db_path, output_dir):
    if not os.path.exists(db_path):
        print("No database yet at {}".format(db_path))
        return EXIT_OK
    conn = database.connect(db_path)
    try:
        database.migrate(conn)
        runs = database.list_runs(conn, limit=args.limit)
        if not runs:
            print("No scan runs recorded yet.")
            return EXIT_OK
        print("{:<4} {:<27} {:<26} {:>6} {:>10} {:>6}".format(
            "ID", "Started (local)", "Status", "Files", "Bytes", "Dur(s)"))
        print("-" * 84)
        for run in runs:
            started = datetime.fromtimestamp(
                run["started_at_epoch"]).astimezone().strftime("%Y-%m-%d %H:%M:%S")
            bytes_row = conn.execute(
                "SELECT COALESCE(SUM(size_bytes),0) FROM entries"
                " WHERE scan_id = ? AND kind='file' AND size_status='observed'",
                (run["id"],)).fetchone()[0]
            print("{:<4} {:<27} {:<26} {:>6} {:>10} {:>6.1f}".format(
                run["id"], started, run["status"],
                run["files_recorded"], human_bytes(bytes_row),
                run["duration_seconds"] or 0.0))
        return EXIT_OK
    finally:
        conn.close()


def cmd_show_run(args, state_dir, db_path, output_dir):
    if not os.path.exists(db_path):
        print("No database at {}".format(db_path), file=sys.stderr)
        return EXIT_USAGE
    conn = database.connect(db_path)
    try:
        database.migrate(conn)
        run = database.get_run(conn, args.scan_id)
        if run is None:
            print("Run #{} not found.".format(args.scan_id), file=sys.stderr)
            return EXIT_USAGE
        print("Scan run #{}".format(run["id"]))
        print("  Status:            {}".format(run["status"]))
        print("  Scope:             {}".format(run["scope_label"]))
        print("  Requested root:    {}".format(run["requested_root"]))
        print("  Canonical root:    {}".format(run["root_path"]))
        print("  Started:           {}".format(
            datetime.fromtimestamp(run["started_at_epoch"]).astimezone().isoformat(sep=" ", timespec="seconds")))
        print("  Finished:          {}".format(
            datetime.fromtimestamp(run["finished_at_epoch"]).astimezone().isoformat(sep=" ", timespec="seconds")
            if run["finished_at_epoch"] else "—"))
        print("  Duration (s):      {}".format(run["duration_seconds"]))
        print("  Files recorded:    {} / seen {}".format(
            run["files_recorded"], run["files_seen"]))
        print("  Directories:       {} / seen {}".format(
            run["directories_recorded"], run["directories_seen"]))
        print("  Symlinks:          {}".format(run["symlinks_seen"]))
        print("  Issues:            {}  Skipped: {}  Excluded: {}".format(
            run["errors_count"], run["skipped_count"], run["excluded_count"]))
        print("  Coverage complete: {}".format(not bool(run["coverage_incomplete"])))
        print("  Coverage notes:    {}".format(run["coverage_notes"]))
        print("  Exclusions:        {}".format(run["exclusions_json"]))
        print("  Volume:            total={} used={} free={} ({})".format(
            run["volume_total_bytes"], run["volume_used_bytes"],
            run["volume_free_bytes"], run["volume_status"]))
        print("  Report state:      {}".format(run["report_state"]))
        return EXIT_OK
    finally:
        conn.close()


_COMMANDS = {
    "check": cmd_check,
    "scan": cmd_scan,
    "report": cmd_report,
    "list-runs": cmd_list_runs,
    "show-run": cmd_show_run,
    "organize-plan": cmd_organize_plan,
    "organize-preview": cmd_organize_preview,
    "organize-approve": cmd_organize_approve,
    "organize-apply": cmd_organize_apply,
    "organize-history": cmd_organize_history,
    "organize-show": cmd_organize_show,
    "organize-undo": cmd_organize_undo,
    "organize-cancel": cmd_organize_cancel,
}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    state_dir, db_path, output_dir = _resolve_paths(args)

    if sys.version_info[:2] < MIN_PYTHON:
        print("Python {} is required; found {}.".format(
            ".".join(map(str, MIN_PYTHON)), sys.version.split()[0]),
            file=sys.stderr)
        return EXIT_USAGE

    if args.command is None:
        parser.print_help()
        return EXIT_OK
    return _COMMANDS[args.command](args, state_dir, db_path, output_dir)
