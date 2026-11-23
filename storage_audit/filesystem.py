"""Filesystem traversal: safe, bounded-memory, iterative.

Uses os.scandir() with an explicit stack (no recursion). Symlinks are never
followed. The scan root is resolved once and retained immutably for the run.
Source files are never opened, read, executed or modified.
"""

import os
import stat as stat_module
import sys
import time
from datetime import datetime

from . import CLASSIFICATION_VERSION, config
from .classifier import (
    classify_extension,
    mime_guess_for,
    normalize_compare_name,
    split_extension,
)
from .safety import (
    bounded_error_message,
    error_category,
    safe_relpath,
)


class ScanCancelled(Exception):
    """Raised inside traversal when cancellation was requested.

    Carries the partial counters in `.state` so the caller can persist them.
    """

    def __init__(self, state=None):
        super().__init__("scan cancelled")
        self.state = state


def _iso_local(epoch):
    return datetime.fromtimestamp(epoch).astimezone().isoformat(
        sep=" ", timespec="seconds")


def _progress_line(state):
    elapsed = time.time() - state["started_wall"]
    path = state.get("current_path") or ""
    if len(path) > config.MAX_PROGRESS_PATH_LEN:
        path = "…" + path[-(config.MAX_PROGRESS_PATH_LEN - 1):]
    return ("\r[{elapsed:7.1f}s] dirs={dirs} files={files} "
            "errors={errors} | {path}").format(
                elapsed=elapsed,
                dirs=state["directories_seen"],
                files=state["files_seen"],
                errors=state["issues"],
                path=path,
            )


def collect_environment(root_stat=None):
    """Reproducibility facts. Deliberately excludes personal identifiers."""
    uname = os.uname() if hasattr(os, "uname") else None
    env = {
        "python_version": sys.version.split()[0],
        "python_implementation": sys.implementation.name,
        "platform_system": uname.sysname if uname else "unavailable",
        "platform_release": uname.release if uname else "unavailable",
        "platform_machine": uname.machine if uname else "unavailable",
        "tz_local": datetime.now().astimezone().tzname() or "unavailable",
    }
    prefix = os.environ.get("PREFIX", "")
    termux_env = os.environ.get("TERMUX_VERSION")
    is_termux = bool(termux_env) or ("com.termux" in prefix)
    env["is_termux"] = bool(is_termux)
    env["termux_version"] = termux_env or ("present" if is_termux else "not detected")
    if is_termux:
        release, sdk = _try_getprop("ro.build.version.release",
                                    "ro.build.version.sdk")
    else:
        release, sdk = "unavailable", "unavailable"
    env["android_release"] = release
    env["android_sdk"] = sdk
    if root_stat is not None:
        env["root_device_id"] = int(root_stat.st_dev)
    return env


def _try_getprop(*props):
    """Best-effort read-only Android property lookup.

    Fixed, non-user-controlled argument list. Any failure yields 'unavailable'.
    """
    results = ["unavailable"] * len(props)
    try:
        import shutil
        import subprocess
        tool = shutil.which("getprop")
        if not tool:
            return tuple(results)
        for i, prop in enumerate(props):
            try:
                out = subprocess.run([tool, prop], capture_output=True,
                                     text=True, timeout=2)
                value = out.stdout.strip()
                if out.returncode == 0 and value:
                    results[i] = value
            except Exception:
                continue
    except Exception:
        pass
    return tuple(results)


def build_exclusion_checker(exclusions_rel):
    """Return function(rel_path) -> bool for exact subtree exclusions only."""
    normalized = []
    for item in exclusions_rel or []:
        item = os.path.normpath(item)
        if item in (".", os.sep) or item.startswith(os.pardir) or os.path.isabs(item):
            continue  # refuse non-exact/escaping exclusions
        normalized.append(item)

    def _excluded(rel):
        rel = os.path.normpath(rel)
        for item in normalized:
            if rel == item or rel.startswith(item + os.sep):
                return True
        return False

    return _excluded


def scan_tree(root_canonical, *, exclusions_rel=None, cancel_event=None,
              progress=True, on_entry=None, on_issue=None):
    """Traverse root iteratively. Calls on_entry(row) / on_issue(issue_dict).

    Never writes to the source tree. Returns the counters dict.
    Raises ScanCancelled if cancel_event is set mid-traversal.
    """
    excluded = build_exclusion_checker(exclusions_rel)
    root_stat = os.lstat(root_canonical)
    root_dev = root_stat.st_dev

    state = {
        "files_seen": 0,
        "files_recorded": 0,
        "directories_seen": 0,
        "directories_recorded": 0,
        "symlinks_seen": 0,
        "other_entries_seen": 0,
        "skipped": 0,
        "excluded": 0,
        "issues": 0,
        "started_wall": time.time(),
        "current_path": root_canonical,
        "last_progress": 0.0,
    }

    def emit_issue(path, operation, category, code, message):
        state["issues"] += 1
        if on_issue is not None:
            on_issue({"path": path, "operation": operation,
                      "error_category": category, "error_code": code,
                      "error_message": message[:config.MAX_ERROR_MESSAGE_LEN]})

    def emit_os_issue(path, operation, exc):
        emit_issue(path, operation, error_category(exc),
                   getattr(exc, "errno", None), bounded_error_message(exc))

    def cancelled():
        return cancel_event is not None and cancel_event.is_set()

    if progress:
        sys.stderr.write(_progress_line(state))
        sys.stderr.flush()

    # The root itself is a recorded directory entry (relative_path ".").
    root_row = _describe_directory(root_canonical, ".", "", 0, root_dev,
                                    root_stat, state)
    if on_entry is not None:
        on_entry(root_row)

    stack = [(root_canonical, ".", 0)]

    while stack:
        if cancelled():
            raise ScanCancelled(state)

        dir_abs, dir_rel, dir_depth = stack.pop()
        state["current_path"] = dir_abs
        state["directories_seen"] += 1

        pending_dirs = []
        try:
            iterator = os.scandir(dir_abs)
        except OSError as exc:
            emit_os_issue(dir_rel, "list", exc)
            continue

        try:
            entries_iter = iter(iterator)
            while True:
                if cancelled():
                    raise ScanCancelled(state)
                try:
                    entry = next(entries_iter)
                except StopIteration:
                    break
                except OSError as exc:
                    emit_os_issue(dir_rel, "list", exc)
                    break

                name = entry.name
                child_rel = name if dir_rel == "." else dir_rel + os.sep + name

                rel_check = safe_relpath(entry.path, root_canonical)
                if rel_check is None:
                    state["skipped"] += 1
                    emit_issue(child_rel, "containment", "path_outside_root",
                               None,
                               "entry resolved outside the scan root; skipped")
                    continue

                if excluded(child_rel):
                    state["excluded"] += 1
                    continue

                row = _describe_entry(entry, child_rel, root_canonical,
                                      dir_rel, dir_depth + 1, root_dev,
                                      state, emit_issue)
                if row["kind"] == "directory" and row["skip_reason"] is None:
                    pending_dirs.append((entry.path, child_rel, dir_depth + 1))
                if on_entry is not None:
                    on_entry(row)
        finally:
            try:
                iterator.close()
            except Exception:
                pass

        # Push children deepest-first so traversal order is stable.
        for sub in reversed(pending_dirs):
            stack.append(sub)

        if progress:
            now = time.time()
            if now - state["last_progress"] >= 1.0:
                state["last_progress"] = now
                sys.stderr.write(_progress_line(state))
                sys.stderr.flush()

    if progress:
        sys.stderr.write(_progress_line(state) + "\n")
        sys.stderr.flush()

    return state


def _describe_directory(dir_abs, rel, parent_rel, depth, root_dev, lstat_result,
                        state):
    """Build the row for a directory whose stat we already have (the root)."""
    mode = lstat_result.st_mode
    size_bytes, size_status = None, "not_applicable"
    mtime = lstat_result.st_mtime
    ts_status = "observed" if mtime is not None else "unavailable"
    mtime_epoch = int(mtime) if mtime is not None else None
    birthtime_epoch, birthtime_status = _birthtime(lstat_result)
    now = int(time.time())
    name = os.path.basename(dir_abs.rstrip(os.sep)) or dir_abs
    if rel == ".":
        name = os.path.basename(dir_abs.rstrip(os.sep)) or "."
    state["directories_recorded"] += 1
    return {
        "relative_path": rel,
        "absolute_path": dir_abs,
        "name": name if rel != "." else (os.path.basename(dir_abs.rstrip(os.sep)) or "."),
        "normalized_name": normalize_compare_name(
            os.path.basename(dir_abs.rstrip(os.sep)) or "."),
        "parent_relative_path": parent_rel,
        "depth": depth,
        "kind": "directory",
        "entry_subtype": None,
        "extension": None,
        "extension_original": None,
        "compound_extension": None,
        "mime_guess": None,
        "category": "unknown",
        "size_bytes": size_bytes,
        "size_status": size_status,
        "mtime_epoch": mtime_epoch,
        "mtime_iso": _iso_local(mtime) if mtime is not None else None,
        "timestamp_status": ts_status,
        "birthtime_epoch": birthtime_epoch,
        "birthtime_status": birthtime_status,
        "is_hidden": 1 if name.startswith(".") else 0,
        "is_symlink": 0,
        "symlink_target": None,
        "symlink_target_status": None,
        "is_readable": None,
        "stat_status": "ok",
        "observation_epoch": now,
        "classification_version": CLASSIFICATION_VERSION,
        "device_id": int(lstat_result.st_dev),
        "skip_reason": None,
        "error_category": None,
        "error_message": None,
    }


def _describe_entry(entry, child_rel, root_canonical, dir_rel, depth,
                    root_dev, state, emit_issue):
    name = entry.name
    is_link = entry.is_symlink()
    now = int(time.time())

    try:
        lst = entry.stat(follow_symlinks=False)
    except FileNotFoundError as exc:
        emit_issue(child_rel, "stat", "disappeared_during_scan",
                   getattr(exc, "errno", None), bounded_error_message(exc))
        return _failed_entry(entry, child_rel, dir_rel, depth, now,
                             "disappeared_during_scan", exc, is_link)
    except OSError as exc:
        emit_issue(child_rel, "stat", error_category(exc),
                   getattr(exc, "errno", None), bounded_error_message(exc))
        return _failed_entry(entry, child_rel, dir_rel, depth, now,
                             "stat_failed", exc, is_link)

    mode = lst.st_mode

    if is_link:
        kind = "symlink"
        subtype = None
        state["symlinks_seen"] += 1
        size_bytes, size_status = None, "not_applicable"
    elif stat_module.S_ISDIR(mode):
        kind = "directory"
        subtype = None
        state["directories_recorded"] += 1
        size_bytes, size_status = None, "not_applicable"
    elif stat_module.S_ISREG(mode):
        kind = "file"
        subtype = None
        state["files_seen"] += 1
        state["files_recorded"] += 1
        size_bytes, size_status = int(lst.st_size), "observed"
    else:
        kind = "other"
        if stat_module.S_ISSOCK(mode):
            subtype = "socket"
        elif stat_module.S_ISFIFO(mode):
            subtype = "fifo"
        elif stat_module.S_ISBLK(mode):
            subtype = "block_device"
        elif stat_module.S_ISCHR(mode):
            subtype = "char_device"
        else:
            kind = "unknown"
            subtype = None
        state["other_entries_seen"] += 1
        size_bytes, size_status = None, "not_applicable"

    ext, compound, ext_original = split_extension(name)
    if kind == "file":
        category = classify_extension(ext)
        mime = mime_guess_for(ext)
    else:
        category = "unknown"
        mime = None

    mtime = lst.st_mtime
    timestamp_status = "observed" if mtime is not None else "unavailable"
    mtime_epoch = int(mtime) if mtime is not None else None
    mtime_iso = _iso_local(mtime) if mtime is not None else None
    birthtime_epoch, birthtime_status = _birthtime(lst)
    is_hidden = 1 if name.startswith(".") else 0

    skip_reason = None
    if int(lst.st_dev) != int(root_dev):
        skip_reason = "mount_boundary"
        state["skipped"] += 1
        emit_issue(child_rel, "containment", "mount_boundary", None,
                   "entry lives on a different filesystem device; "
                   "not crossed in V1")

    symlink_target = None
    symlink_target_status = None
    if is_link:
        try:
            target = os.readlink(entry.path)
            symlink_target = target[:config.MAX_SYMLINK_TARGET_LEN]
            try:
                os.stat(entry.path)  # follow: metadata only, never contents
                symlink_target_status = "ok"
            except OSError:
                symlink_target_status = "broken"
        except OSError as exc:
            symlink_target_status = "failed"
            emit_issue(child_rel, "readlink", error_category(exc),
                       getattr(exc, "errno", None), bounded_error_message(exc))

    return {
        "relative_path": child_rel,
        "absolute_path": entry.path,
        "name": name,
        "normalized_name": normalize_compare_name(name),
        "parent_relative_path": dir_rel,
        "depth": depth,
        "kind": kind,
        "entry_subtype": subtype,
        "extension": ext,
        "extension_original": ext_original,
        "compound_extension": compound,
        "mime_guess": mime,
        "category": category,
        "size_bytes": size_bytes,
        "size_status": size_status,
        "mtime_epoch": mtime_epoch,
        "mtime_iso": mtime_iso,
        "timestamp_status": timestamp_status,
        "birthtime_epoch": birthtime_epoch,
        "birthtime_status": birthtime_status,
        "is_hidden": is_hidden,
        "is_symlink": 1 if is_link else 0,
        "symlink_target": symlink_target,
        "symlink_target_status": symlink_target_status,
        "is_readable": None,
        "stat_status": "ok",
        "observation_epoch": now,
        "classification_version": CLASSIFICATION_VERSION,
        "device_id": int(lst.st_dev),
        "skip_reason": skip_reason,
        "error_category": None,
        "error_message": None,
    }


def _failed_entry(entry, child_rel, dir_rel, depth, now, reason, exc, is_link):
    name = entry.name
    try:
        if entry.is_dir(follow_symlinks=False):
            kind = "directory"
        elif entry.is_file(follow_symlinks=False):
            kind = "file"
        elif is_link:
            kind = "symlink"
        else:
            kind = "unknown"
    except OSError:
        kind = "unknown"

    ext, compound, ext_original = split_extension(name)
    return {
        "relative_path": child_rel,
        "absolute_path": entry.path,
        "name": name,
        "normalized_name": normalize_compare_name(name),
        "parent_relative_path": dir_rel,
        "depth": depth,
        "kind": kind,
        "entry_subtype": None,
        "extension": ext,
        "extension_original": ext_original,
        "compound_extension": compound,
        "mime_guess": None,
        "category": "unknown",
        "size_bytes": None,
        "size_status": "failed",
        "mtime_epoch": None,
        "mtime_iso": None,
        "timestamp_status": "failed",
        "birthtime_epoch": None,
        "birthtime_status": "unavailable",
        "is_hidden": 1 if name.startswith(".") else 0,
        "is_symlink": 1 if is_link else 0,
        "symlink_target": None,
        "symlink_target_status": "failed" if is_link else None,
        "is_readable": None,
        "stat_status": "failed",
        "observation_epoch": now,
        "classification_version": CLASSIFICATION_VERSION,
        "device_id": None,
        "skip_reason": None,
        "error_category": error_category(exc),
        "error_message": bounded_error_message(exc),
    }


def _birthtime(lst):
    """Birth time only when the platform exposes it; never derived."""
    stat_result = getattr(lst, "st_birthtime", None)
    if stat_result is not None:
        try:
            return int(stat_result), "observed"
        except (TypeError, ValueError, OverflowError):
            return None, "failed"
    return None, "unavailable"
