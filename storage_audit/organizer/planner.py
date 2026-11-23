"""Plan builder: selected user-owned folder → organization plan (no writes).

Scope policy (org-scope-1) is mandatory and enforced here:

* The user selects ONE personal folder (the organization scope). The scan is
  used only as provenance/inventory context — never as a source of files to
  move. The V1 scan sees the whole shared-storage tree; the organization
  engine must not widen an approved selection, so the plan is built by a
  fresh, lstat-based walk of the selected folder only.
* Android/, system, Termux-private, hidden and reserved content is
  default-deny at every level (see scope.py). Exclusions are recorded on the
  plan and in the preview.
* Sources and destinations both live inside the approved scope.
"""

import json
import os
import re
import sqlite3
import time

from .. import config
from .scope import (SCOPE_POLICY_VERSION, ScopeRejected, validate_scope,
                    walk_eligible, op_path_check)

PLAN_STATUS_DRAFT = "draft"
PLAN_RULE_VERSION = "1.1.0"

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
CATEGORY_FOLDERS = frozenset(_CATEGORY_FOLDERS.values())
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
               action="copy-keep", hash_verify=False, storage_root=None):
    """Create a DRAFT plan for one explicitly selected, user-owned folder.

    ``target_root`` is the organization scope: the only tree the plan may
    touch. It must pass the org-scope-1 validation (see scope.py) — Android/,
    system, Termux-private, hidden, reserved and cross-boundary locations are
    rejected outright with ScopeRejected (a PlanError subclass).

    The plan copies/moves eligible files found inside the scope into
    ``<scope>/<Category>/<original relative path>``. Nothing outside the
    scope is planned, nothing is written to the filesystem here.
    """
    if rule != "by-category":
        raise PlanError("unknown rule {!r}; supported: by-category".format(rule))
    if action not in ("copy-keep", "move"):
        raise PlanError("action must be 'copy-keep' or 'move'")

    # --- org-scope-1: target validation (default-deny) ---
    validation = validate_scope(target_root, storage_root=storage_root)
    if not validation["ok"]:
        raise ScopeRejected(validation)
    scope = validation["canonical"]

    run = conn.execute(
        "SELECT * FROM scan_runs WHERE id = ?", (scan_id,)).fetchone()
    if run is None:
        raise PlanError("scan run {!r} does not exist".format(scan_id))
    if run["status"] not in ("completed", "completed_with_gaps"):
        raise PlanError(
            "scan run {} is '{}' — only completed scans can be organized "
            "(run `report --latest` to use the newest completed run).".format(
                scan_id, run["status"]))

    # --- recursive, exclusion-enforcing walk of the scope ---
    eligible, exclusions, allowed_dirs = walk_eligible(scope)

    # Classify with the same tables V1 uses (filename only; never contents).
    from .. import classifier
    operations = []
    skipped = []
    reserved = {}          # dest_rel -> True (deterministic collision map)
    total_bytes = 0
    for item in eligible:
        rel = item["source_rel"]
        ext, _compound, _orig = classifier.split_extension(os.path.basename(rel))
        category = classifier.classify_extension(ext) if ext else "unknown"
        dest_rel = _safe_dest_rel(category, rel)
        if dest_rel is None:
            skipped.append((rel, "dest_unrepresentable"))
            continue
        # Files already sitting inside a category folder are never re-nested
        # (Images/x.jpg must not become Images/Images/x.jpg on a re-plan).
        first_component = rel.split(os.sep)[0] if os.sep in rel else rel
        if first_component in CATEGORY_FOLDERS:
            skipped.append((rel, "already_categorized"))
            continue
        dest_abs = os.path.join(scope, dest_rel)
        conflict = None
        if os.path.lexists(dest_abs):
            conflict = "exists"
        elif dest_rel in reserved:
            conflict = "duplicate_in_plan"
        else:
            reserved[dest_rel] = True
        operations.append({
            "source_rel": rel,
            "source_abs": item["source_abs"],
            "dest_rel": dest_rel,
            "dest_abs": dest_abs,
            "size_bytes": item["size_bytes"],
            "action": action,
            "conflict": conflict,
        })
        total_bytes += int(item["size_bytes"] or 0)

    for rel, reason in skipped:
        exclusions.append({"path": rel, "reason": reason})

    conflicts = sum(1 for o in operations if o["conflict"])
    now = int(time.time())
    exclusion_cap = 1000
    excluded_json = json.dumps(
        exclusions[:exclusion_cap], ensure_ascii=False)
    allowed_json = json.dumps(allowed_dirs[:500], ensure_ascii=False)
    validation_json = json.dumps(validation, ensure_ascii=False)
    with conn:
        cur = conn.execute(
            "INSERT INTO organization_plans("
            " scan_id, rule_name, rule_version, target_root, action,"
            " hash_verify, status, created_at_epoch, updated_at_epoch,"
            " total_operations, total_bytes, conflicts, invalid, notes,"
            " eligible_files, excluded_entries, scope_policy_version,"
            " scope_canonical, scope_allowed_json, scope_excluded_json,"
            " scope_validation_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (scan_id, rule, PLAN_RULE_VERSION, scope, action,
             1 if hash_verify else 0, PLAN_STATUS_DRAFT,
             now, now, len(operations), total_bytes, conflicts, 0,
             "action={}; rule={}; skipped={}; policy={}".format(
                 action, rule, len(skipped), SCOPE_POLICY_VERSION),
             len(eligible), len(exclusions), SCOPE_POLICY_VERSION,
             scope, allowed_json, excluded_json, validation_json))
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
        for item in exclusions:
            conn.execute(
                "INSERT INTO organization_events(plan_id, operation_id, event,"
                " detail, occurred_at_epoch) VALUES (?,?,?,?,?)",
                (plan_id, None, "skipped_source",
                 "{}: {}".format(item["reason"], item["path"]), now))
        conn.execute(
            "INSERT INTO organization_events(plan_id, operation_id, event,"
            " detail, occurred_at_epoch) VALUES (?,?,?,?,?)",
            (plan_id, None, "plan_created",
             "operations={} conflicts={} skipped={} eligible={} policy={}".format(
                 len(operations), conflicts, len(skipped), len(eligible),
                 SCOPE_POLICY_VERSION), now))
    return plan_id, {
        "operations": len(operations),
        "total_bytes": total_bytes,
        "conflicts": conflicts,
        "skipped": len(skipped),
        "target_root": scope,
        "action": action,
        "eligible_files": len(eligible),
        "excluded_entries": len(exclusions),
        "exclusions": exclusions,
        "allowed_dirs": allowed_dirs,
        "scope_policy_version": SCOPE_POLICY_VERSION,
    }
