"""Plan builder: inventory scan run → organization plan (no filesystem writes)."""

import json
import os
import re
import sqlite3

from .. import config

PLAN_STATUS_DRAFT = "draft"
PLAN_RULE_VERSION = "1.0.0"

# Human-readable folder names per category; only categories that exist in
# classifier.py. Unknown stays "Unsorted" — nothing is ever invented.
_CATEGORY_FOLDERS = {
    "image": "Images",
    "video": "Videos",
    "audio": "Audio",
    "document": "Documents",
    "archive": "Archives",
    "package": "Packages",
    "database": "Databases",
    "code": "Code",
    "font": "Fonts",
    "backup": "Backups",
    "system/unknown": "System",
    "unknown": "Unsorted",
    "other": "Other",
}
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._ -]+")


class PlanError(Exception):
    """Raised for invalid plan requests (not for individual file problems)."""


def category_folder(category):
    folder = _CATEGORY_FOLDERS.get((category or "unknown").lower(), "Unsorted")
    return folder


def _safe_dest_rel(category, source_rel):
    """Map a scanned relative path into the target tree.

    Deterministic; never escapes: every segment of source_rel is used only
    as path components under <Category>/, and each component is basename-
    sanitised (no separators, no dot-dot).
    """
    safe_parts = []
    for part in source_rel.replace("\\", "/").split("/"):
        part = part.strip()
        if part in ("", ".", ".."):
            continue
        # Keep legal leading dots (dotfiles). Only strip characters that are
        # nowhere legal in a path segment; never strip away identity.
        part = _SAFE_SEGMENT.sub("_", part).strip()
        if part in ("", ".", ".."):
            continue
        safe_parts.append(part)
    if not safe_parts:
        return None
    dest = os.path.join(category_folder(category), *safe_parts)
    # Normalise separators for the platform, keep it relative and contained.
    dest = os.path.normpath(dest)
    if dest.startswith("..") or os.path.isabs(dest):
        return None
    return dest


def build_plan(conn, scan_id, target_root, *, rule="by-category",
               action="copy-keep", hash_verify=False):
    """Create a DRAFT plan from a completed scan. Returns (plan_id, stats).

    Only regular files with observed stat (stat_status='ok') are planned.
    Symlinks, directories, and failed/unavailable entries are skipped with
    explicit reasons recorded as events. Nothing is written to the user's
    filesystem here — the plan is rows in the database plus, optionally, a
    preview file rendered separately.
    """
    if rule != "by-category":
        raise PlanError("unknown rule {!r}; supported: by-category".format(rule))
    if action not in ("copy-keep", "move"):
        raise PlanError("action must be 'copy-keep' or 'move'")

    target_root = os.path.realpath(os.path.expanduser(target_root))
    if not target_root or target_root == os.path.sep:
        raise PlanError("refusing to use filesystem root as organization target")

    run = conn.execute(
        "SELECT * FROM scan_runs WHERE id = ?", (scan_id,)).fetchone()
    if run is None:
        raise PlanError("scan run {!r} does not exist".format(scan_id))
    if run["status"] not in ("completed", "completed_with_gaps"):
        raise PlanError(
            "scan run {} is '{}' — only completed scans can be organized "
            "(run `report --latest` to use the newest completed run).".format(
                scan_id, run["status"]))
    root = run["root_path"]

    rows = conn.execute(
        "SELECT relative_path, absolute_path, size_bytes, category, is_symlink,"
        " stat_status, kind FROM entries WHERE scan_id = ? AND kind = 'file'"
        " ORDER BY relative_path COLLATE NOCASE, relative_path",
        (scan_id,)).fetchall()

    operations = []
    skipped = []
    reserved = {}          # dest_rel -> first seq (deterministic collision map)
    total_bytes = 0
    for row in rows:
        if row["stat_status"] != "ok":
            skipped.append((row["relative_path"], "stat_failed"))
            continue
        if row["is_symlink"]:
            skipped.append((row["relative_path"], "symlink_refused"))
            continue
        dest_rel = _safe_dest_rel(row["category"], row["relative_path"])
        if dest_rel is None:
            skipped.append((row["relative_path"], "dest_unrepresentable"))
            continue
        dest_abs = os.path.join(target_root, dest_rel)
        conflict = None
        if os.path.exists(dest_abs):
            conflict = "exists"
        elif dest_rel in reserved:
            conflict = "duplicate_in_plan"
        else:
            reserved[dest_rel] = True
        operations.append({
            "source_rel": row["relative_path"],
            "source_abs": row["absolute_path"],
            "dest_rel": dest_rel,
            "dest_abs": dest_abs,
            "size_bytes": row["size_bytes"],
            "action": action,
            "conflict": conflict,
        })
        total_bytes += int(row["size_bytes"] or 0)

    conflicts = sum(1 for o in operations if o["conflict"])
    import time
    now = int(time.time())
    with conn:
        cur = conn.execute(
            "INSERT INTO organization_plans("
            " scan_id, rule_name, rule_version, target_root, action,"
            " hash_verify, status, created_at_epoch, updated_at_epoch,"
            " total_operations, total_bytes, conflicts, invalid, notes)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (scan_id, rule, PLAN_RULE_VERSION, target_root, action,
             1 if hash_verify else 0, PLAN_STATUS_DRAFT,
             now, now, len(operations), total_bytes, conflicts, 0,
             "action={}; rule={}; skipped={}".format(action, rule, len(skipped))))
        plan_id = cur.lastrowid
        for i, op in enumerate(operations, start=1):
            status = "planned" if op["conflict"] is None else "conflict"
            conn.execute(
                "INSERT INTO organization_operations("
                " plan_id, scan_id, seq, action, source_rel, source_abs,"
                " dest_rel, dest_abs, size_bytes, status, conflict)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (plan_id, scan_id, i, op["action"], op["source_rel"],
                 op["source_abs"], op["dest_rel"], op["dest_abs"],
                 op["size_bytes"], status, op["conflict"]))
        for rel, reason in skipped:
            conn.execute(
                "INSERT INTO organization_events(plan_id, operation_id, event,"
                " detail, occurred_at_epoch) VALUES (?,?,?,?,?)",
                (plan_id, None, "skipped_source",
                 "{}: {}".format(reason, rel), now))
        conn.execute(
            "INSERT INTO organization_events(plan_id, operation_id, event,"
            " detail, occurred_at_epoch) VALUES (?,?,?,?,?)",
            (plan_id, None, "plan_created",
             "operations={} conflicts={} skipped={} action={}".format(
                 len(operations), conflicts, len(skipped), action), now))
    return plan_id, {
        "operations": len(operations),
        "total_bytes": total_bytes,
        "conflicts": conflicts,
        "skipped": len(skipped),
        "target_root": target_root,
        "action": action,
    }
