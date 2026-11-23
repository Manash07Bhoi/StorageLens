"""Safety primitives: canonicalization, containment, exclusions.

Every filesystem-touching component routes its path decisions through here so
the rules are auditable in one place. No function in this module mutates the
scanned tree.
"""

import os


class SafetyError(Exception):
    """Raised when a path fails a safety check."""


class RootValidationError(SafetyError):
    """The requested scan root failed validation."""


def canonicalize(path):
    """Return the canonical absolute path for an *existing* path.

    Uses os.path.realpath (resolves symlinks lexically and physically).
    Returns a normalized absolute path. Does not check existence.
    """
    return os.path.realpath(os.path.abspath(os.path.expanduser(path)))


def validate_scan_root(requested_root):
    """Validate the scan root. Returns (canonical_root, info_dict).

    Raises RootValidationError with a precise, user-actionable message when
    the root is unusable. Never silently substitutes another path.
    """
    info = {"requested_root": requested_root, "canonical_root": None}
    if not requested_root or not str(requested_root).strip():
        raise RootValidationError("No scan root supplied and none resolved.")

    canonical = canonicalize(requested_root)
    info["canonical_root"] = canonical

    if not os.path.lexists(canonical):
        raise RootValidationError(
            "Scan root does not exist: {}\n"
            "If you are in Termux, run 'termux-setup-storage' and grant the "
            "storage permission, then check that ~/storage/shared exists."
            .format(canonical))

    if os.path.islink(requested_root) or os.path.islink(canonical):
        # Symlink resolution to the canonical path is fine (e.g. ~/storage/shared
        # -> /storage/emulated/0); we record both and continue.
        info["root_was_symlink"] = True

    if not os.path.isdir(canonical):
        raise RootValidationError(
            "Scan root exists but is not a directory: {}".format(canonical))

    try:
        probe = os.scandir(canonical)
        try:
            next(probe, None)
        finally:
            probe.close()
    except PermissionError as exc:
        raise RootValidationError(
            "Scan root cannot be listed (permission denied): {}\n"
            "The Termux storage permission may not be granted. "
            "Run 'termux-setup-storage' and grant access.".format(canonical)) from exc
    except OSError as exc:
        raise RootValidationError(
            "Scan root cannot be listed: {} ({})".format(canonical, exc)) from exc

    info["root_listed"] = True
    return canonical, info


def is_within(child, parent):
    """True if `child` is the same as or inside `parent`, by path components.

    Component-aware: /a/bc is NOT within /a/b. Purely lexical after both
    paths have been normalized; callers must canonicalize first.
    """
    child = os.path.normpath(child)
    parent = os.path.normpath(parent)
    if child == parent:
        return True
    rel = os.path.relpath(child, parent)
    return rel != os.pardir and not rel.startswith(os.pardir + os.sep) \
        and not os.path.isabs(rel)


def check_output_location(output_dir, scan_root):
    """Validate the report/database destination relative to the scan root.

    Returns (ok, message, exclusion_rel_path_or_None).
    - ok=False means the run must abort.
    - exclusion is set when the output lives inside the scan root and must be
      excluded from the traversal.
    """
    out = canonicalize(output_dir)
    root = canonicalize(scan_root)

    if out == root:
        return False, ("Output directory is the scan root itself; refusing to "
                       "proceed (the scan would enumerate its own growing "
                       "output)."), None
    if is_within(root, out):
        return False, ("Scan root is inside the output directory; refusing "
                       "to proceed. Choose an output directory that does not "
                       "contain the scan root."), None
    if is_within(out, root):
        return True, ("Output directory is inside the scan root; it will be "
                      "excluded from the scan and the exclusion recorded."), os.path.relpath(out, root)
    return True, "Output directory is outside the scan root.", None


def safe_relpath(path, root):
    """Relative path of `path` beneath canonical `root`, or None if outside."""
    path = os.path.normpath(path)
    root = os.path.normpath(root)
    if path == root:
        return "."
    rel = os.path.relpath(path, root)
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return None
    return rel


def bounded_error_message(exc):
    msg = "{}: {}".format(type(exc).__name__, exc)
    from .config import MAX_ERROR_MESSAGE_LEN
    if len(msg) > MAX_ERROR_MESSAGE_LEN:
        msg = msg[:MAX_ERROR_MESSAGE_LEN - 3] + "..."
    return msg


def error_category(exc):
    """Stable machine-readable categories for issue accounting."""
    if isinstance(exc, PermissionError):
        return "permission_denied"
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, NotADirectoryError):
        return "not_a_directory"
    if isinstance(exc, IsADirectoryError):
        return "is_a_directory"
    if isinstance(exc, OSError):
        code = getattr(exc, "errno", None)
        if code is not None:
            return "os_error_{}".format(code)
        return "os_error"
    return "unexpected_error"
