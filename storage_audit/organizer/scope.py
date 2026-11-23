"""Organization scope policy (org-scope-2) — the hard boundary for V2.

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
  organizing a prohibited location. Registration of a custom folder
  (organize-register-scope) is NOT an override: it can only ever clear the
  "unknown folder" check for a folder the user explicitly selects, and it is
  impossible for Android/, system, application-private, Termux-private,
  hidden, reserved or cross-boundary locations, which no registration can
  clear.
* **Visibility is not ownership** — a visible folder is NEVER presumed safe
  merely because the user can see it. Only well-known personal folders are
  recognized by name; anything else must be explicitly registered by the
  user on this device before it can be organized.
* **Trusted aliases only** — the documented Termux ``~/storage/<alias>``
  symlinks (created by ``termux-setup-storage``) are resolved through a
  strict trusted-alias check: the alias must be a known name AND a symlink
  (or plain dir) whose realpath is inside the permitted shared-storage root.
  Every other symlink component is still rejected, and the final canonical
  destination is re-validated like any other selection.

Deterministic on any host (no Android assumptions required for the checks
that do not depend on one). On a device with shared storage present, targets
must also resolve inside the permitted shared-storage root.
"""

import json
import os
import stat
import time

from .. import config

SCOPE_POLICY_VERSION = "org-scope-2"

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

# Organization is permitted WITHOUT extra ceremony only for the ordinary,
# well-known personal folders that appear as an immediate child of shared
# storage (or as the basename of the selection on a development host). Any
# other visible folder is NOT presumed safe: it must be explicitly
# registered by the user (organize-register-scope) — ownership is never
# inferred from path visibility.
RECOGNIZED_PERSONAL_FOLDERS = frozenset({
    "download", "downloads", "documents", "pictures", "movies", "music",
    "ringtones", "alarms", "notifications", "dcim", "recordings",
    "screenshots", "podcasts", "audiopodcasts", "audiobooks", "bluetooth",
})

# Symlinks inside ~/storage created by termux-setup-storage. Each documented
# alias is trusted ONLY when it points into the permitted shared-storage
# root; anything else under ~/storage is not an alias we resolve.
TERMUX_STORAGE_ALIASES = frozenset({
    "shared", "audiopodcasts", "alarms", "dcim", "documents", "downloads",
    "movies", "music", "notifications", "pictures", "podcasts", "ringtones",
    "audiobooks",
})

SCOPE_REGISTRY_FILENAME = "scope_registry.json"


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
                   protected_prefixes=None, prefix=None,
                   registered_scopes=None, _allow_unrecognized=False):
    """Validate an explicitly selected organization scope.

    Returns a validation dict:
      {ok, canonical, reasons[], checks[], policy_version}

    OK requires ALL of:
      1. selected path exists                       (missing)
      2. it is a directory                          (not_directory)
      3. no symlink components; the ONLY symlinks resolved are documented
         Termux shared-storage aliases via trusted-alias resolution
         (symlink_escape / trusted_storage_alias)
      4. it resolves inside permitted shared storage when a storage root is
         determinable (outside_shared_storage / not_entire_shared_storage)
      5. it is not an operating-system or protected directory (protected_system)
      6. it is not Termux-private (termux_private)
      7. no component is Android/ or hidden/reserved (component_policy)
      8. it is not the filesystem root, the home directory or the shared
         storage root itself (not_filesystem_root / not_home_directory /
         not_entire_shared_storage)
      9. it does not cross an unsupported storage boundary (mount_boundary)
     10. it is a recognized personal folder, or a folder the user has
         explicitly registered on this device
         (recognized_personal / registered_custom_scope) — ownership is
         never inferred from visibility; unknown folders are rejected

    No ordering of these checks permits a prohibited location. There is no
    override switch. ``_allow_unrecognized`` exists ONLY for the registration
    flow (organize-register-scope), which must register the very folder the
    user selects; it is never passed by the planner, the executor or undo.
    """
    checks = []
    reasons = []

    def add(check, passed, detail):
        checks.append({"check": check, "result": "pass" if passed else "FAIL",
                       "detail": detail})
        if not passed:
            reasons.append("{}: {}".format(check, detail))

    def validation(canon=None):
        if canon is None:
            try:
                canon = os.path.realpath(effective) if effective else p
            except OSError:
                canon = p
        return {"ok": not reasons, "canonical": canon,
                "requested": path, "reasons": reasons, "checks": checks,
                "policy_version": SCOPE_POLICY_VERSION}

    home_dir = os.path.realpath(home) if home else os.path.realpath(
        os.path.expanduser("~"))

    p = os.path.expanduser(path or "")
    effective = p
    if not p.strip():
        effective = ""
        add("missing", False, "no path given")
        return validation(canon="")

    # Trusted Termux ~/storage/<alias> resolution (never widens the scope).
    alias_resolved, alias_detail = resolve_trusted_alias(
        p, home=home_dir, storage_root=storage_root)
    if alias_resolved is not None:
        effective = alias_resolved
        checks.append({"check": "trusted_storage_alias", "result": "pass",
                       "detail": alias_detail})

    try:
        st = os.lstat(effective)
    except OSError as exc:
        add("missing", False, "cannot stat {!r}: {}".format(effective, exc))
        return validation()
    add("exists", True, "lstat succeeded")

    if stat.S_ISLNK(st.st_mode):
        add("not_a_symlink", False,
            "{!r} is a symlink; select the real folder".format(effective))
        return validation(canon=os.path.realpath(effective))
    add("not_a_symlink", True, "selection itself is not a symlink")

    if not stat.S_ISDIR(st.st_mode):
        add("is_directory", False, "{!r} is not a directory".format(effective))
        return validation(canon=os.path.realpath(effective))
    add("is_directory", True, "selection is a directory")

    canonical = os.path.realpath(effective)

    # Component-wise symlink scan of the *effective* path (trusted aliases
    # have already been collapsed to their canonical target).
    escaped, bad = _symlink_escape(effective)
    add("symlink_escape", not escaped,
        "no symlink components" if not escaped else
        "symlink component at {!r} — refusing to follow".format(bad))

    root_case = (canonical == os.path.sep)
    add("not_filesystem_root", not root_case,
        "target is '/'" if root_case else "not the filesystem root")
    too_broad_home = (canonical == home_dir)
    add("not_home_directory", not too_broad_home,
        "refusing to organize the entire home directory" if too_broad_home
        else "not the home directory")

    root = storage_root if storage_root is not None else find_permitted_storage_root()
    rootc = os.path.realpath(root) if root else None
    if rootc:
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

    # Recognition / registration — NEVER overrides the prohibited checks above.
    if _allow_unrecognized:
        checks.append({"check": "recognized_personal", "result": "skip",
                       "detail": "unrecognized-name check skipped (registration flow)"})
    else:
        selection = _selection_name(canonical, rootc)
        if reasons:
            # A prohibited check already failed: the verdict is a rejection
            # either way, so recognition is moot — report it as skipped
            # instead of piling a redundant failure line onto the refusal.
            checks.append({"check": "recognized_personal", "result": "skip",
                           "detail": "not evaluated — a prohibited check already failed"})
        elif selection and selection in RECOGNIZED_PERSONAL_FOLDERS:
            # Recognition is independent of the registry: a corrupt registry
            # never manufactures uncertainty about a well-known personal folder.
            add("recognized_personal", True,
                "recognized personal folder {!r}".format(selection))
        else:
            # The custom-folder path DEPENDS on the registry; fail closed on
            # any registry error — uncertainty never means permission.
            if registered_scopes is None:
                registered_scopes, registry_error = load_registered_scopes()
            else:
                registry_error = None
            if registry_error:
                add("registry", False,
                    "cannot read scope registry — failing closed: {}".format(
                        registry_error))
            elif canonical in registered_scopes:
                add("registered_custom_scope", True,
                    "explicitly registered by the user on this device")
            else:
                add("recognized_personal", False,
                    "{!r} is not a recognized personal folder and is not "
                    "explicitly registered on this device. Select a recognized "
                    "folder (Download, Documents, Pictures, DCIM, Music, Movies, "
                    "Ringtones, Alarms, Recordings, Screenshots, Podcasts, …) or "
                    "register this folder explicitly with `organize-register-scope`. "
                    "Unknown folders are never assumed safe.".format(
                        selection or canonical))

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

    return validation(canonical)


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


# --------------------------------------------------------------------------
# Termux storage aliases (trusted-alias resolution) and scope registry
# --------------------------------------------------------------------------

def resolve_trusted_alias(path, *, home=None, storage_root=None):
    """Resolve a documented Termux shared-storage alias, or refuse.

    ``termux-setup-storage`` exposes shared storage through symlinks under
    ``~/storage`` (``shared``, ``downloads``, ``dcim``, …). Refusing every
    symlink component of an argument would reject the documented
    ``~/storage/shared/Download`` selection — so this function resolves an
    alias ONLY when ALL of these hold:

      1. the argument path passes through ``~/storage/<alias>`` where
         ``<alias>`` is one of the documented names;
      2. the alias component is a symlink (or the plain ``shared`` dir) whose
         realpath is the permitted shared-storage root or inside it;
      3. the permitted shared-storage root can be determined.

    Anything else — a user-created symlink in ~/storage, an undocumented
    name, an alias escaping the shared root — returns ``(None, None)`` and
    the caller applies the strict rule. Resolution never widens the scope:
    the result is a canonical path under the permitted root, re-validated
    like any other selection.
    """
    expanded = os.path.expanduser(path or "")
    if not expanded.strip():
        return None, None
    home_real = (os.path.realpath(home) if home
                 else os.path.realpath(os.path.expanduser("~")))
    storage_dir = os.path.join(home_real, "storage")
    abspath = os.path.abspath(expanded)
    prefix = storage_dir + os.sep
    if not abspath.startswith(prefix):
        return None, None
    rest = abspath[len(prefix):]
    parts = rest.split(os.sep) if rest else []
    if not parts or not parts[0]:
        return None, None
    alias_name = parts[0].lower()
    if alias_name not in TERMUX_STORAGE_ALIASES:
        return None, None                      # undocumented name: never trusted
    alias_path = os.path.join(storage_dir, parts[0])
    try:
        lst = os.lstat(alias_path)
    except OSError:
        return None, None
    if not stat.S_ISLNK(lst.st_mode):
        return None, None                      # documented aliases ARE symlinks
    target = os.path.realpath(alias_path)
    shared = (storage_root if storage_root is not None
              else find_permitted_storage_root())
    if not shared:
        return None, None                      # cannot establish trust here
    root_real = os.path.realpath(shared)
    if not (target == root_real or target.startswith(root_real + os.sep)):
        return None, None                      # alias escapes shared storage
    if not os.path.isdir(target):
        return None, None
    if len(parts) > 1:
        resolved = os.path.join(target, *parts[1:])
    else:
        resolved = target
    return resolved, ("trusted Termux storage alias {!r} resolved to {!r}".format(
        os.path.join("~", "storage", parts[0]), target))


def default_registry_path():
    xdg = os.environ.get("XDG_DATA_HOME")
    base = os.path.join(xdg, config.APP_DIR_NAME) if xdg else os.path.join(
        os.path.expanduser("~"), config.DEFAULT_STATE_DIR)
    return os.path.join(base, SCOPE_REGISTRY_FILENAME)


def load_registered_scopes(registry_path=None):
    """Return (set_of_canonical_paths, error_or_None). Missing file is fine."""
    path = registry_path or default_registry_path()
    entries, err = _load_registry_entries(path)
    if err:
        return set(), err
    return {e["canonical"] for e in entries}, None


def _load_registry_entries(path):
    if not os.path.exists(path):
        return [], None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("scopes", []) if isinstance(data, dict) else []
        entries = []
        for e in raw:
            if (isinstance(e, dict) and isinstance(e.get("canonical"), str)
                    and e["canonical"]):
                entries.append({"canonical": e["canonical"],
                                "note": e.get("note", ""),
                                "registered_at": e.get("registered_at", None)})
        return entries, None
    except Exception as exc:
        return [], "cannot read scope registry at {!r}: {}".format(path, exc)


def _save_registry(entries, registry_path=None):
    path = registry_path or default_registry_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    data = {"version": 2, "policy_version": SCOPE_POLICY_VERSION,
            "scopes": sorted(entries, key=lambda e: e["canonical"])}
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def register_scope(path, *, note="", registry_path=None,
                   home=None, storage_root=None):
    """Register a custom user-owned folder after explicit confirmation.

    Prohibited locations (Android/, system, Termux-private, hidden,
    reserved, escapes, cross-boundary) can NEVER be registered. Returns
    (canonical, created, message).
    """
    verdict = validate_scope(path, home=home, storage_root=storage_root,
                             _allow_unrecognized=True)
    prohibited = [r for r in verdict["reasons"]
                  if not r.startswith("recognized_personal")]
    if prohibited:
        raise ScopeRejected(verdict)
    canonical = verdict["canonical"]
    entries, err = _load_registry_entries(registry_path or default_registry_path())
    if err:
        raise ScopeRejected({"ok": False, "canonical": canonical,
                             "requested": path,
                             "reasons": ["registry_unreadable: {}".format(err)],
                             "checks": verdict["checks"],
                             "policy_version": SCOPE_POLICY_VERSION})
    for e in entries:
        if e["canonical"] == canonical:
            return canonical, False, "already registered: {}".format(canonical)
    entries.append({"canonical": canonical, "note": note or "",
                    "registered_at": int(time.time())})
    _save_registry(entries, registry_path)
    return canonical, True, "registered: {}".format(canonical)


def unregister_scope(path, *, registry_path=None):
    canonical = os.path.realpath(os.path.expanduser(path))
    entries, err = _load_registry_entries(registry_path or default_registry_path())
    if err:
        raise ScopeRejected({"ok": False, "canonical": canonical,
                             "requested": path,
                             "reasons": ["registry_unreadable: {}".format(err)],
                             "checks": [],
                             "policy_version": SCOPE_POLICY_VERSION})
    kept = [e for e in entries if e["canonical"] != canonical]
    removed = len(kept) != len(entries)
    _save_registry(kept, registry_path)
    return removed


def list_registered_scopes(registry_path=None):
    scopes, err = load_registered_scopes(registry_path)
    return (sorted(scopes), err)


def _selection_name(canonical, root):
    """First path component below the shared-storage root, else basename."""
    if root:
        rootc = os.path.realpath(root)
        if canonical == rootc:
            return None
        if canonical.startswith(rootc + os.sep):
            rel = os.path.relpath(canonical, rootc)
            return rel.split(os.sep)[0].lower()
    base = os.path.basename(canonical.rstrip(os.sep))
    return base.lower() if base else None
