"""Organization scope policy (org-scope-1) — the hard boundary for V2.

StorageLens V2 is a PERSONAL-FILE organization tool. This module is the
enforcement point for the rule:

    NEVER organize Android/, system files, protected application data,
    Termux-private data, hidden or unknown directories, anything outside an
    explicitly selected, validated, user-owned folder.

The policy is:

* **Default-deny** — anything the policy cannot clear is rejected, never
  permitted by silence. Uncertainty always means rejection.
* **Explicit selection only** — no automatic permissions; the scan never
  grants organization rights. A user must select a folder the policy clears.
* **Applied at every layer** — target validation at plan creation, recursive
  exclusions during the walk, per-operation revalidation at execution time,
  scope revalidation before apply and before undo. A UI warning is never the
  only control.
* **No overrides** — there is intentionally no flag/config/env that enables
  organizing a prohibited location.

Deterministic on any host (no Android assumptions required for the checks
that do not depend on one). On a device with shared storage present, targets
must also resolve inside the permitted shared-storage root.
"""

import os
import stat

SCOPE_POLICY_VERSION = "org-scope-1"

# Exact, case-insensitive directory-component matches that are ALWAYS
# prohibited, at any depth. "Android" is Android's reserved application
# directory tree (data/, obb/, media/, and everything created or will be
# created inside it). LOST.DIR is system-managed on shared storage.
DENIED_COMPONENTS = frozenset({"android", "lost.dir"})

# Hidden names (leading dot) are denied everywhere below the filesystem root.
RESERVED_PREFIXES = (".trash-",)        # trash dirs never organized
RESERVED_EXACT = frozenset({".thumbnails"})

# Absolute system prefixes (never user data). Only applied to absolute paths.
DEFAULT_PROTECTED_PREFIXES = (
    "/system", "/system_ext", "/vendor", "/product", "/apex", "/odm",
    "/data", "/acct", "/config", "/dev", "/proc", "/sys", "/root",
)
# /data covers Termux-private storage on Android
# (/data/data/com.termux/..., /data/user/0/com.termux/...).

_CATEGORY_HINT = (
    "Images|Videos|Audio|Documents|Archives|Packages|Databases|Code|Fonts|"
    "Backups|System|Unsorted|Other"
)


class ScopeRejected(Exception):
    """The selected scope is prohibited. Carries structured validation."""

    def __init__(self, validation):
        self.validation = validation
        super().__init__(
            "Organization unavailable: this location is protected or outside "
            "the permitted user-data scope. Reasons: "
            + "; ".join(validation["reasons"]))


def find_permitted_storage_root():
    """Best-effort Android shared-storage root; None on a development host."""
    candidates = [
        os.environ.get("STORAGE_AUDIT_SHARED_ROOT"),
        "/storage/emulated/0",
        "/storage/self/primary",
        os.path.expanduser("~/storage/shared"),
    ]
    for cand in candidates:
        if cand and os.path.isdir(cand):
            return os.path.realpath(cand)
    return None


def _path_components(path):
    parts = []
    cur = path
    while True:
        head, tail = os.path.split(cur)
        if tail:
            parts.append(tail)
            cur = head
        elif head != cur:
            cur = head
            break
        else:
            break
    return list(reversed(parts))


def _symlink_escape(path):
    """True if ANY component of an absolute path is a symlink.

    Strict: symlinked directories above the selected folder could redirect the
    scope into a prohibited location, so every component is checked with
    lstat — never resolved silently.
    """
    abspath = os.path.abspath(path)
    parts = _path_components(abspath)
    cur = os.sep
    for part in parts:
        cur = os.path.join(cur, part)
        try:
            st = os.lstat(cur)
        except OSError:
            return True, cur   # unreadable component: fail closed
        if stat.S_ISLNK(st.st_mode):
            return True, cur
    return False, None


def _component_violations(canonical):
    """Return list of reasons for denied components in a canonical path."""
    violations = []
    for comp in _path_components(canonical):
        low = comp.lower()
        if low in DENIED_COMPONENTS:
            violations.append("protected_android: prohibited component "
                              "{!r} in path".format(comp))
        elif comp.startswith("."):
            violations.append("hidden: hidden component {!r} in path".format(comp))
        elif low in RESERVED_EXACT:
            violations.append("reserved: {!r} is system-managed".format(comp))
        elif any(low.startswith(p) for p in RESERVED_PREFIXES):
            violations.append("reserved: {!r} is a trash directory".format(comp))
    return violations


def validate_scope(path, *, storage_root=None, home=None,
                   protected_prefixes=None, prefix=None):
    """Validate an explicitly selected organization scope.

    Returns a validation dict:
      {ok, canonical, reasons[], checks[], policy_version}

    OK requires ALL of:
      1. selected path exists                       (missing)
      2. it is a directory                          (not_directory)
      3. no component of the given path is a symlink (symlink_escape)
      4. it resolves inside permitted shared storage when a storage root is
         determinable (outside_shared_storage / entire_shared_storage)
      5. it is not an operating-system or protected directory (protected_system)
      6. it is not Termux-private (termux_private)
      7. no component is Android/ or hidden/reserved (protected_android/hidden/reserved)
      8. it is not the filesystem root, the home directory or the shared
         storage root itself (too_broad)
      9. it does not cross an unsupported storage boundary (mount_boundary)
    """
    checks = []
    reasons = []

    def add(check, passed, detail):
        checks.append({"check": check, "result": "pass" if passed else "FAIL",
                       "detail": detail})
        if not passed:
            reasons.append("{}: {}".format(check, detail))

    def validation():
        return {"ok": not reasons, "canonical": locals().get("canonical", path),
                "requested": path, "reasons": reasons, "checks": checks,
                "policy_version": SCOPE_POLICY_VERSION}

    p = os.path.expanduser(path or "")
    if not p.strip():
        add("missing", False, "no path given")
        return validation()

    try:
        st = os.lstat(p)
    except OSError as exc:
        add("missing", False, "cannot stat {!r}: {}".format(p, exc))
        return validation()
    add("exists", True, "lstat succeeded")

    if stat.S_ISLNK(st.st_mode):
        add("not_a_symlink", False, "{!r} is a symlink; select the real folder".format(p))
        canonical = os.path.realpath(p)
        return validation()
    add("not_a_symlink", True, "selection itself is not a symlink")

    if not stat.S_ISDIR(st.st_mode):
        add("is_directory", False, "{!r} is not a directory".format(p))
        return validation()
    add("is_directory", True, "selection is a directory")

    canonical = os.path.realpath(p)

    # Component-wise symlink scan of the *argument* path.
    escaped, bad = _symlink_escape(p)
    add("symlink_escape", not escaped,
        "no symlink components" if not escaped else
        "symlink component at {!r} — refusing to follow".format(bad))

    home_dir = os.path.realpath(home) if home else os.path.realpath(
        os.path.expanduser("~"))
    root_case = (canonical == os.path.sep)
    add("not_filesystem_root", not root_case,
        "target is '/'" if root_case else "not the filesystem root")
    too_broad_home = (canonical == home_dir)
    add("not_home_directory", not too_broad_home,
        "refusing to organize the entire home directory" if too_broad_home
        else "not the home directory")

    root = storage_root if storage_root is not None else find_permitted_storage_root()
    if root:
        rootc = os.path.realpath(root)
        if canonical == rootc:
            add("not_entire_shared_storage", False,
                "refusing to organize the entire shared-storage root")
        elif canonical.startswith(rootc + os.sep):
            add("inside_shared_storage", True,
                "inside permitted shared storage ({})".format(rootc))
        else:
            add("inside_shared_storage", False,
                "{!r} is outside the permitted shared-storage root {!r}".format(
                    canonical, rootc))
    else:
        # Development host: no shared storage determinable. Component rules
        # still apply; shared-storage containment is reported as untested.
        checks.append({"check": "inside_shared_storage", "result": "skip",
                       "detail": "no permitted shared-storage root detected "
                                 "(development host)"})

    # Protected absolute prefixes (system + all app/Termux-private storage).
    prefixes = protected_prefixes if protected_prefixes is not None else \
        DEFAULT_PROTECTED_PREFIXES
    blocked = next((pref for pref in prefixes
                    if canonical == pref or canonical.startswith(pref + os.sep)),
                   None)
    add("protected_system", blocked is None,
        "not under a protected system prefix" if blocked is None else
        "under protected prefix {!r} (system / application-private / "
        "Termux-private)".format(blocked))

    # Termux-private storage explicitly (not under /data in all setups, e.g.
    # Termux on some ROMs uses an app-private path under /data/user/0).
    termux_prefix = prefix if prefix is not None else os.environ.get("PREFIX")
    if termux_prefix:
        tp = os.path.realpath(termux_prefix)
        in_termux = canonical == tp or canonical.startswith(tp + os.sep)
        add("termux_private", not in_termux,
            "not inside the Termux installation prefix" if not in_termux else
            "inside the Termux installation prefix {!r}".format(tp))
    else:
        checks.append({"check": "termux_private", "result": "skip",
                       "detail": "PREFIX not set (development host)"})

    # Reserved hidden/Android/trash components, anywhere in the path.
    component_hits = _component_violations(canonical)
    if component_hits:
        for hit in component_hits:
            add(hit.split(":")[0], False, hit.split(": ", 1)[1])
    else:
        add("component_policy", True,
            "no Android/ hidden/reserved components in path")

    # Storage boundary between scope and its parent.
    parent = os.path.dirname(canonical)
    try:
        dev_self = os.stat(canonical, follow_symlinks=False).st_dev
        dev_parent = os.stat(parent, follow_symlinks=False).st_dev if parent else dev_self
        same = (dev_self == dev_parent)
        add("mount_boundary", same,
            "same storage boundary as its parent" if same else
            "scope lives on a different filesystem than its parent "
            "(unsupported boundary)")
    except OSError as exc:
        add("mount_boundary", False, "cannot stat parent boundary: {}".format(exc))

    return validation()


def dir_exclusion_reason(name, path, st, base_dev):
    """Why a child DIRECTORY encountered during the walk is excluded."""
    low = name.lower()
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if low in DENIED_COMPONENTS:
        return "protected_android" if low == "android" else "reserved"
    if name.startswith("."):
        return "hidden"
    if low in RESERVED_EXACT or any(low.startswith(p) for p in RESERVED_PREFIXES):
        return "reserved"
    if st.st_dev != base_dev:
        return "mount_boundary"
    if not stat.S_ISDIR(st.st_mode):
        return "unsupported_type"
    return None


def file_exclusion_reason(name, path, st, base_dev):
    """Why a child FILE encountered during the walk is excluded."""
    if stat.S_ISLNK(st.st_mode):
        return "symlink"
    if name.startswith("."):
        return "hidden"
    if not stat.S_ISREG(st.st_mode):
        return "unsupported_type"   # fifo/socket/device: refuse
    if st.st_dev != base_dev:
        return "mount_boundary"
    return None


def walk_eligible(scope_canonical):
    """Walk the selected scope with default-deny exclusions at EVERY level.

    Returns (eligible, exclusions, allowed_dirs):
      eligible     — list of dicts {source_abs, source_rel, size_bytes,
                     mtime_epoch, is_regular(True)} for regular, visible,
                     in-scope files
      exclusions   — list of dicts {path (scope-relative), reason} for every
                     skipped entry (files and directories, never entered)
      allowed_dirs — sorted set of traversed (scope-relative) directories

    Symlinks are never followed (os.walk followlinks=False + lstat), Android/
    is rejected by name at every depth, hidden and reserved directories are
    pruned, and nothing outside the scope boundary is considered.
    """
    eligible, exclusions, allowed = [], [], []
    base_dev = os.stat(scope_canonical, follow_symlinks=False).st_dev

    for dirpath, dirnames, filenames in os.walk(scope_canonical,
                                                followlinks=False):
        keep = []
        for d in dirnames:
            full = os.path.join(dirpath, d)
            rel = os.path.relpath(full, scope_canonical)
            try:
                st = os.lstat(full)
            except OSError:
                exclusions.append({"path": rel, "reason": "unreadable"})
                continue
            reason = dir_exclusion_reason(d, full, st, base_dev)
            if reason:
                exclusions.append({"path": rel, "reason": reason})
            else:
                allowed.append(rel)
                keep.append(d)
        dirnames[:] = keep  # prune — excluded directories are never entered

        for fname in filenames:
            full = os.path.join(dirpath, fname)
            rel = os.path.relpath(full, scope_canonical)
            try:
                st = os.lstat(full)
            except OSError:
                exclusions.append({"path": rel, "reason": "unreadable"})
                continue
            reason = file_exclusion_reason(fname, full, st, base_dev)
            if reason:
                exclusions.append({"path": rel, "reason": reason})
                continue
            eligible.append({"source_abs": full, "source_rel": rel,
                             "size_bytes": int(st.st_size),
                             "mtime_epoch": int(st.st_mtime)})
    eligible.sort(key=lambda e: (e["source_rel"].lower(), e["source_rel"]))
    return eligible, exclusions, sorted(set(allowed))


def op_path_check(src_abs, dest_abs, scope_canonical):
    """Per-operation validation used at execution time (and for tests).

    Both paths must remain inside the approved scope, must not contain
    denied components, and the source must not be a symlink. Never trust
    validation performed at plan time — revalidate now.
    """
    scope = os.path.realpath(scope_canonical)

    def under_scope(p):
        rp = os.path.realpath(p)
        return rp == scope or rp.startswith(scope + os.sep), rp

    def clean_components(rp):
        return not _component_violations(rp)

    ok_src, src_rp = under_scope(src_abs)
    if not ok_src:
        return False, "source escapes the approved scope: {!r}".format(src_abs)
    if not clean_components(src_rp):
        return False, "source contains a prohibited component: {!r}".format(src_rp)
    if os.path.islink(src_abs):
        return False, "source is a symlink; refused"

    ok_dst, dst_rp = under_scope(dest_abs)
    if not ok_dst:
        return False, "destination escapes the approved scope: {!r}".format(dest_abs)
    if not clean_components(dst_rp):
        return False, ("destination contains a prohibited component: "
                       "{!r}".format(dst_rp))
    return True, "ok"
