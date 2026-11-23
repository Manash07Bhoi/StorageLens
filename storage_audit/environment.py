"""Environment detection and the `check` command's data assembly.

Distinguishes Termux/Android from other hosts honestly and never claims
on-device validation that did not happen.
"""

import os
import shutil
import sqlite3
import sys

from . import MIN_PYTHON, __version__
from .filesystem import collect_environment
from .safety import canonicalize, is_within

DEFAULT_SHARED_ROOT = os.path.join("~", "storage", "shared")


def resolve_default_root():
    """Root for a real scan when the user did not pass --root.

    Order: $STORAGE_AUDIT_ROOT > ~/storage/shared. No fallback to $HOME.
    Returns the raw (unexpanded-as-string) default to display.
    """
    env_root = os.environ.get("STORAGE_AUDIT_ROOT")
    if env_root:
        return env_root
    return DEFAULT_SHARED_ROOT


def python_version_ok():
    return sys.version_info[:2] >= MIN_PYTHON


def gather_check_info(state_dir, db_path, requested_root=None):
    """Assemble every fact `check` reports. Nothing here is fabricated."""
    info = {}
    info["tool_version"] = __version__
    info["python_version"] = sys.version.split()[0]
    info["python_ok"] = python_version_ok()
    info["min_python"] = ".".join(str(p) for p in MIN_PYTHON)

    root = requested_root if requested_root else resolve_default_root()
    info["requested_root"] = root
    canonical = canonicalize(root) if root else None
    info["canonical_root"] = canonical
    info["root_exists"] = bool(canonical) and os.path.lexists(canonical)
    info["root_is_dir"] = bool(canonical) and os.path.isdir(canonical)
    info["root_listable"] = False
    info["root_error"] = None
    if info["root_is_dir"]:
        try:
            it = os.scandir(canonical)
            try:
                next(it, None)
            finally:
                it.close()
            info["root_listable"] = True
        except OSError as exc:
            info["root_error"] = "{}: {}".format(type(exc).__name__, exc)

    env = collect_environment(os.lstat(canonical) if info["root_exists"] else None)
    info["environment"] = env
    info["is_termux"] = env["is_termux"]

    # State/output location checks.
    info["state_dir"] = state_dir
    info["db_path"] = db_path
    try:
        os.makedirs(state_dir, exist_ok=True)
        probe = os.path.join(state_dir, ".write_probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        info["state_dir_writable"] = True
    except OSError as exc:
        info["state_dir_writable"] = False
        info["state_dir_error"] = "{}: {}".format(type(exc).__name__, exc)

    # Volume usage for the candidate root (or state dir on non-device hosts).
    try:
        usage = shutil.disk_usage(canonical if info["root_is_dir"] else state_dir)
        info["volume"] = {
            "total": int(usage.total), "used": int(usage.total - usage.free),
            "free": int(usage.free), "status": "observed",
        }
    except OSError as exc:
        info["volume"] = {"status": "unavailable: {}".format(exc)}

    # Output inside root?
    if info["root_is_dir"]:
        info["output_inside_root"] = is_within(canonicalize(state_dir), canonical)
    else:
        info["output_inside_root"] = None

    info["sqlite_version"] = sqlite3.sqlite_version
    return info
