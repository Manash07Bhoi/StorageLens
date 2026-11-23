"""org-scope-2 hardening regression tests.

Covers the defects found in the 2026-11-23 independent review of v2.1.0:

  1. validate_scope() must propagate a CANONICAL path into the organization
     plan — regression test for the nested-closure bug that stored the raw
     (possibly unnormalized) argument in "canonical".
  2. The documented Termux ~/storage/<alias> symlink layout must be resolved
     ONLY through a strict trusted-alias check; arbitrary symlinks and
     escapes stay rejected.
  3. Ownership is never inferred from visibility: only recognized personal
     folders validate out of the box; every other folder requires explicit
     user registration, and registration can never clear Android/, system,
     Termux-private, hidden, reserved or cross-boundary locations.
  4. Branch-level checks: storage-boundary stat, registry fail-closed
     behaviour, post-plan scope change, registry revocation before apply,
     and zero filesystem changes + zero new plan rows on rejection.

All fixtures are synthetic. No real user data, no device, no network.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_rich_fixture

from storage_audit import database
from storage_audit.scanner import run_scan
from storage_audit import organizer
from storage_audit.organizer import executor
from storage_audit.organizer import scope as scope_mod


def _write(root, rel, data=b"x"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, bytes) else data.encode())
    return path


def _tree_snapshot(root):
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames + dirnames:
            full = os.path.join(dirpath, name)
            try:
                st = os.lstat(full)
                snap[os.path.relpath(full, root)] = (st.st_mode, st.st_size)
            except OSError:
                pass
    return snap


class HardeningTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scope_hardening_test_")
        self._old_xdg = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp, "xdg")
        # Synthetic Android-like shared store
        self.phone = os.path.join(self.tmp, "shared")
        os.makedirs(self.phone)
        _write(self.phone, "Documents/keep.txt")
        _write(self.phone, "Documents/notes.md")
        _write(self.phone, "My Study Files/chapter1.pdf")
        _write(self.phone, "My Study Files/chapter2.pdf")
        _write(self.phone, "Android/data/com.example.app/files/data.bin")
        self.outside = os.path.join(self.tmp, "outside")
        _write(self.outside, "outside.txt")
        self.db = os.path.join(self.tmp, "t.sqlite3")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        if self._old_xdg is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._old_xdg
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_scan(self):
        return run_scan(self.phone, db_path=self.db,
                        output_dir=self.out, progress=False)["run_id"]

    def conn(self):
        conn = database.connect(self.db)
        database.migrate(conn)
        return conn

    def plan_count(self, conn):
        return conn.execute(
            "SELECT COUNT(*) FROM organization_plans").fetchone()[0]


# ------------------------------------------------------- 1. canonical path
class TestCanonicalPropagation(HardeningTestCase):
    """Regression for the nested-closure bug: validation['canonical'] was the
    raw argv string, and the planner stored that in the plan manifest."""

    def _verdict(self, arg, **kwargs):
        return scope_mod.validate_scope(arg, **kwargs)

    def test_unnormalized_dotdot_input_yields_canonical(self):
        arg = os.path.join(self.phone, "Documents", "..", "Documents")
        verdict = self._verdict(arg, storage_root=self.phone)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertEqual(verdict["canonical"],
                         os.path.realpath(os.path.join(self.phone, "Documents")))
        self.assertNotEqual(verdict["canonical"], arg)   # raw argv had /../

    def test_double_slashes_and_dot_components(self):
        arg = self.phone + os.sep + "." + os.sep + "Documents" + os.sep
        arg = arg.replace(os.sep + os.sep, os.sep)
        verdict = self._verdict(arg, storage_root=self.phone)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertEqual(verdict["canonical"],
                         os.path.realpath(os.path.join(self.phone, "Documents")))

    def test_expanded_home_input(self):
        home = os.path.join(self.tmp, "home")
        os.makedirs(home)
        os.symlink(self.phone, os.path.join(home, "shared"))
        storage_dir = os.path.join(home, "storage")
        os.makedirs(storage_dir)
        os.symlink(self.phone, os.path.join(storage_dir, "shared"))
        with mock.patch.dict(os.environ, {"HOME": home}):
            verdict = scope_mod.validate_scope(
                "~/storage/shared/Documents", home=home,
                storage_root=self.phone)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertEqual(verdict["canonical"],
                         os.path.realpath(os.path.join(self.phone, "Documents")))

    def test_relative_input_from_cwd(self):
        old = os.getcwd()
        try:
            os.chdir(self.phone)
            verdict = self._verdict("Documents", storage_root=self.phone)
        finally:
            os.chdir(old)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertEqual(verdict["canonical"],
                         os.path.realpath(os.path.join(self.phone, "Documents")))

    def test_already_canonical_input_unchanged(self):
        canon = os.path.realpath(os.path.join(self.phone, "Documents"))
        verdict = self._verdict(canon, storage_root=self.phone)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertEqual(verdict["canonical"], canon)

    def test_nonexistent_path_still_fails_closed_with_canonical(self):
        arg = os.path.join(self.phone, "Documents", "..", "NoSuchDir")
        verdict = self._verdict(arg, storage_root=self.phone)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("missing" in r for r in verdict["reasons"]))
        # Even on failure the reported canonical is a realpath, never the raw arg
        self.assertEqual(verdict["canonical"],
                         os.path.realpath(os.path.join(self.phone, "NoSuchDir")))

    def test_plan_manifest_stores_canonical_not_raw_argument(self):
        arg = os.path.join(self.phone, "Documents", "..", "Documents")
        conn = self.conn()
        try:
            scan_id = self.make_scan()
            plan_id, stats = organizer.build_plan(conn, scan_id, arg,
                                                  storage_root=self.phone)
            row = conn.execute(
                "SELECT target_root, scope_canonical, scope_validation_json"
                " FROM organization_plans WHERE id = ?", (plan_id,)).fetchone()
            canon = os.path.realpath(os.path.join(self.phone, "Documents"))
            self.assertEqual(row["target_root"], canon)
            self.assertEqual(row["scope_canonical"], canon)
            manifest = json.loads(row["scope_validation_json"])
            self.assertEqual(manifest["canonical"], canon)
            self.assertEqual(stats["target_root"], canon)
        finally:
            conn.close()


# -------------------------------------------------- 2. Termux storage aliases
class TestTrustedStorageAliases(HardeningTestCase):
    """The documented termux-setup-storage layout: ~/storage/shared is a
    symlink to the shared-storage root. Only that layout is resolvable."""

    def setUp(self):
        super().setUp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(os.path.join(self.home, "storage"))
        # documented aliases (all symlinks on a real device)
        for alias, target in [("shared", self.phone),
                              ("documents", os.path.join(self.phone, "Documents")),
                              ("downloads", os.path.join(self.phone, "Documents"))]:
            try:
                os.symlink(target, os.path.join(self.home, "storage", alias))
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unsupported")

    def _v(self, arg, **kw):
        kw.setdefault("home", self.home)
        kw.setdefault("storage_root", self.phone)
        return scope_mod.validate_scope(arg, **kw)

    def test_documented_alias_documents_accepted(self):
        verdict = self._v(os.path.join(self.home, "storage", "shared", "Documents"))
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertEqual(verdict["canonical"],
                         os.path.realpath(os.path.join(self.phone, "Documents")))

    def test_documented_alias_documents_direct(self):
        verdict = self._v(os.path.join(self.home, "storage", "documents"))
        self.assertTrue(verdict["ok"], verdict["reasons"])

    def test_trusted_alias_check_recorded(self):
        verdict = self._v(os.path.join(self.home, "storage", "shared", "Documents"))
        checks = {c["check"]: c for c in verdict["checks"]}
        self.assertIn("trusted_storage_alias", checks)
        self.assertEqual(checks["trusted_storage_alias"]["result"], "pass")

    def test_alias_to_shared_root_itself_rejected_as_too_broad(self):
        verdict = self._v(os.path.join(self.home, "storage", "shared"))
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("not_entire_shared_storage" in r
                            for r in verdict["reasons"]), verdict["reasons"])

    def test_undocumented_name_in_storage_rejected(self):
        try:
            os.symlink(self.phone, os.path.join(self.home, "storage", "backups"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported")
        verdict = self._v(os.path.join(self.home, "storage", "backups", "Documents"))
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("symlink_escape" in r for r in verdict["reasons"]),
                        verdict["reasons"])

    def test_known_alias_name_pointing_outside_root_rejected(self):
        # An attacker/emulator swaps downloads -> ~/outside: never resolve.
        try:
            os.unlink(os.path.join(self.home, "storage", "downloads"))
            os.symlink(self.outside, os.path.join(self.home, "storage", "downloads"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported")
        verdict = self._v(os.path.join(self.home, "storage", "downloads"))
        self.assertFalse(verdict["ok"])
        # strict fallback: the selection itself is a symlink → rejected
        self.assertTrue(any("not_a_symlink" in r or "symlink_escape" in r
                            for r in verdict["reasons"]), verdict["reasons"])
        # and it was NOT resolved through the trusted-alias mechanism
        alias_passes = [c for c in verdict["checks"]
                        if c["check"] == "trusted_storage_alias"]
        self.assertFalse(alias_passes)

    def test_alias_pointing_at_android_stays_rejected(self):
        try:
            os.symlink(os.path.join(self.phone, "Android"),
                       os.path.join(self.home, "storage", "alarms"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported")
        verdict = self._v(os.path.join(self.home, "storage", "alarms"))
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("protected_android" in r for r in verdict["reasons"]),
                        verdict["reasons"])

    def test_symlink_inside_alias_resolved_scope_still_excluded(self):
        try:
            os.symlink(self.outside,
                       os.path.join(self.phone, "Documents", "evil_link"))
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported")
        canon = os.path.realpath(os.path.join(self.phone, "Documents"))
        eligible, exclusions, _allowed = scope_mod.walk_eligible(canon)
        eligible_names = [os.path.basename(e["source_abs"]) for e in eligible]
        self.assertIn("keep.txt", eligible_names)
        excluded_symlinks = [e for e in exclusions if e["reason"] == "symlink"]
        self.assertTrue(any("evil_link" in e["path"] for e in excluded_symlinks),
                        exclusions)


# ------------------------------ 3. recognition / explicit registration flow
class TestRecognitionAndRegistration(HardeningTestCase):

    def test_unrecognized_visible_folder_rejected(self):
        snap = _tree_snapshot(os.path.join(self.phone, "My Study Files"))
        conn = self.conn()
        try:
            before = self.plan_count(conn)
            verdict = scope_mod.validate_scope(
                os.path.join(self.phone, "My Study Files"),
                storage_root=self.phone)
            self.assertFalse(verdict["ok"])
            self.assertTrue(any("recognized_personal" in r
                                for r in verdict["reasons"]), verdict["reasons"])
            with self.assertRaises(organizer.ScopeRejected):
                organizer.build_plan(conn, self.make_scan(),
                                     os.path.join(self.phone, "My Study Files"),
                                     storage_root=self.phone)
            self.assertEqual(self.plan_count(conn), before)   # no plan row
        finally:
            conn.close()
        self.assertEqual(snap, _tree_snapshot(
            os.path.join(self.phone, "My Study Files")))       # no FS change

    def test_recognized_folder_needs_no_registration(self):
        verdict = scope_mod.validate_scope(
            os.path.join(self.phone, "Documents"), storage_root=self.phone)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        # and no registry file was created implicitly
        self.assertFalse(os.path.exists(
            os.path.join(os.environ["XDG_DATA_HOME"],
                         "android-storage-audit", "scope_registry.json")))

    def test_register_custom_folder_then_plan_then_unregister(self):
        custom = os.path.join(self.phone, "My Study Files")
        canonical, created, message = scope_mod.register_scope(
            custom, note="my own notes folder", storage_root=self.phone)
        self.assertTrue(created)
        self.assertEqual(canonical, os.path.realpath(custom))
        verdict = scope_mod.validate_scope(custom, storage_root=self.phone)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        self.assertTrue(any(c["check"] == "registered_custom_scope"
                            and c["result"] == "pass"
                            for c in verdict["checks"]), verdict["checks"])
        # plan can be created
        conn = self.conn()
        try:
            scan_id = self.make_scan()
            plan_id, stats = organizer.build_plan(conn, scan_id, custom,
                                                  storage_root=self.phone)
            self.assertGreater(stats["operations"], 0)
        finally:
            conn.close()
        # unregister → rejected again
        self.assertTrue(scope_mod.unregister_scope(custom))
        verdict = scope_mod.validate_scope(custom, storage_root=self.phone)
        self.assertFalse(verdict["ok"])

    def test_registration_refused_for_prohibited_locations(self):
        hidden_dir = os.path.join(self.phone, ".hidden_x")
        os.makedirs(hidden_dir)
        for arg in (os.path.join(self.phone, "Android", "data"),
                    hidden_dir,
                    "/"):
            with self.assertRaises(scope_mod.ScopeRejected, msg=arg):
                scope_mod.register_scope(arg, storage_root=self.phone)

    def test_registration_file_is_private_and_roundtrips(self):
        custom = os.path.join(self.phone, "My Study Files")
        scope_mod.register_scope(custom, storage_root=self.phone)
        reg = os.path.join(os.environ["XDG_DATA_HOME"],
                           "android-storage-audit", "scope_registry.json")
        self.assertTrue(os.path.exists(reg))
        mode = os.stat(reg).st_mode & 0o777
        self.assertEqual(mode, 0o600)
        scopes, err = scope_mod.list_registered_scopes()
        self.assertIsNone(err)
        self.assertIn(os.path.realpath(custom), scopes)

    def test_tampered_registry_fails_closed_for_custom_folder(self):
        custom = os.path.join(self.phone, "My Study Files")
        scope_mod.register_scope(custom, storage_root=self.phone)
        reg = os.path.join(os.environ["XDG_DATA_HOME"],
                           "android-storage-audit", "scope_registry.json")
        with open(reg, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json !!")
        verdict = scope_mod.validate_scope(custom, storage_root=self.phone)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("registry" in r for r in verdict["reasons"]),
                        verdict["reasons"])

    def test_tampered_registry_does_not_break_recognized_folder(self):
        reg = os.path.join(os.environ["XDG_DATA_HOME"],
                           "android-storage-audit", "scope_registry.json")
        os.makedirs(os.path.dirname(reg), exist_ok=True)
        with open(reg, "w", encoding="utf-8") as fh:
            fh.write("{ not valid json !!")
        verdict = scope_mod.validate_scope(
            os.path.join(self.phone, "Documents"), storage_root=self.phone)
        self.assertTrue(verdict["ok"], verdict["reasons"])

    def test_registry_revocation_blocks_approved_plan_at_apply(self):
        custom = os.path.join(self.phone, "My Study Files")
        scope_mod.register_scope(custom, storage_root=self.phone)
        conn = self.conn()
        try:
            scan_id = self.make_scan()
            plan_id, stats = organizer.build_plan(conn, scan_id, custom,
                                                  storage_root=self.phone)
            executor.approve_plan(conn, plan_id, note="approved in test")
            before = _tree_snapshot(custom)
            # user revokes the registration before apply
            scope_mod.unregister_scope(custom)
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
            self.assertEqual(before, _tree_snapshot(custom))
            # refused plan left no completed operations behind
            done = conn.execute(
                "SELECT COUNT(*) FROM organization_operations"
                " WHERE plan_id = ? AND status = 'completed'",
                (plan_id,)).fetchone()[0]
            self.assertEqual(done, 0)
        finally:
            conn.close()

    def test_zero_rows_and_zero_fs_changes_on_rejected_plan(self):
        for arg in (os.path.join(self.phone, "Android", "data"),
                    os.path.join(self.phone, "My Study Files")):
            snap = _tree_snapshot(self.phone)
            conn = self.conn()
            try:
                before = self.plan_count(conn)
                with self.assertRaises(organizer.ScopeRejected):
                    organizer.build_plan(conn, self.make_scan(), arg,
                                         storage_root=self.phone)
                self.assertEqual(self.plan_count(conn), before)
            finally:
                conn.close()
            self.assertEqual(snap, _tree_snapshot(self.phone), arg)


# ------------------------------------- 4. boundary + closed-world branch audit
class TestBoundaryBranches(HardeningTestCase):

    def test_scope_deleted_after_approval_fails_revalidation(self):
        scope = os.path.join(self.phone, "Documents")
        conn = self.conn()
        try:
            scan_id = self.make_scan()
            plan_id, _ = organizer.build_plan(conn, scan_id, scope,
                                              storage_root=self.phone)
            executor.approve_plan(conn, plan_id, note="test")
            shutil.rmtree(scope)
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
        finally:
            conn.close()

    def test_scope_replaced_by_symlink_after_approval_fails(self):
        scope = os.path.join(self.phone, "Documents")
        conn = self.conn()
        try:
            scan_id = self.make_scan()
            plan_id, _ = organizer.build_plan(conn, scan_id, scope,
                                              storage_root=self.phone)
            executor.approve_plan(conn, plan_id, note="test")
            saved = scope + "_real"
            os.rename(scope, saved)
            os.symlink(os.path.join(self.phone, "Android"), scope)
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
        finally:
            shutil.rmtree(saved, ignore_errors=True)
            try:
                os.unlink(scope)
            except OSError:
                pass
            conn.close()

    def test_validate_scope_never_returns_ok_for_empty_path(self):
        for bad in ("", None, "   "):
            verdict = scope_mod.validate_scope(bad, storage_root=self.phone)
            self.assertFalse(verdict["ok"], bad)

    def test_protected_prefix_boundary_is_path_aware(self):
        # A sibling whose name merely STARTS WITH a protected prefix must NOT
        # be rejected by it; a genuine child must be.
        fake_sys = os.path.join(self.tmp, "sysroot")
        sibling = os.path.join(self.tmp, "sysroot_backup")
        child = os.path.join(fake_sys, "payload")
        os.makedirs(sibling)
        os.makedirs(child)
        verdict = scope_mod.validate_scope(
            sibling, storage_root=None, protected_prefixes=(fake_sys,))
        self.assertFalse(any("protected_system" in r
                             for r in verdict["reasons"]),
                         verdict["reasons"])
        verdict = scope_mod.validate_scope(
            child, storage_root=None, protected_prefixes=(fake_sys,))
        self.assertTrue(any("protected_system" in r
                            for r in verdict["reasons"]),
                        verdict["reasons"])


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------ 4b. branch audit: discovery,
# ------------------------------------------ mount boundary, op-level checks
class TestStorageRootDiscovery(HardeningTestCase):

    def test_env_var_candidate_wins(self):
        with mock.patch.dict(os.environ,
                             {"STORAGE_AUDIT_SHARED_ROOT": self.phone}):
            self.assertEqual(scope_mod.find_permitted_storage_root(),
                             os.path.realpath(self.phone))

    def test_env_var_candidate_must_exist(self):
        with mock.patch.dict(
                os.environ,
                {"STORAGE_AUDIT_SHARED_ROOT":
                 os.path.join(self.tmp, "does_not_exist")}):
            # no /storage/emulated/0 on the dev host; HOME-less fallback fails
            with mock.patch.dict(os.environ, {"HOME": self.tmp}):
                result = scope_mod.find_permitted_storage_root()
            self.assertTrue(result is None or os.path.isdir(result))

    def test_home_storage_shared_candidate_used(self):
        home = os.path.join(self.tmp, "home2")
        os.makedirs(os.path.join(home, "storage"))
        os.symlink(self.phone, os.path.join(home, "storage", "shared"))
        env = {"HOME": home}
        env.pop("STORAGE_AUDIT_SHARED_ROOT", None)
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("STORAGE_AUDIT_SHARED_ROOT", None)
            result = scope_mod.find_permitted_storage_root()
        self.assertEqual(result, os.path.realpath(self.phone))


class TestMountBoundaryBranch(HardeningTestCase):

    def test_cross_boundary_scope_rejected(self):
        scope = os.path.realpath(os.path.join(self.phone, "Documents"))
        parent = os.path.dirname(scope)
        real_stat = os.stat

        class FakeSt(object):
            def __init__(self, dev):
                self.st_dev = dev

        def fake_stat(path, *args, **kwargs):
            if os.path.realpath(path) == scope:
                return FakeSt(100)
            if os.path.realpath(path) == os.path.realpath(parent):
                return FakeSt(200)
            return real_stat(path)

        with mock.patch.object(scope_mod.os, "stat", side_effect=fake_stat):
            verdict = scope_mod.validate_scope(scope, storage_root=self.phone)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("mount_boundary" in r for r in verdict["reasons"]),
                        verdict["reasons"])

    def test_unstatable_parent_fails_closed(self):
        scope = os.path.realpath(os.path.join(self.phone, "Documents"))

        _real_stat = os.stat

        def fake_stat(path, *args, **kwargs):
            if os.path.realpath(path) == os.path.dirname(scope):
                raise OSError("simulated stat failure")
            return _real_stat(path, *args, **kwargs)

        with mock.patch.object(scope_mod.os, "stat", side_effect=fake_stat):
            verdict = scope_mod.validate_scope(scope, storage_root=self.phone)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("mount_boundary" in r for r in verdict["reasons"]),
                        verdict["reasons"])


class TestOpPathCheck(HardeningTestCase):

    def setUp(self):
        super().setUp()
        self.scope = os.path.realpath(os.path.join(self.phone, "Documents"))

    def test_source_outside_scope_rejected(self):
        outside_file = os.path.join(self.outside, "outside.txt")
        ok, reason = scope_mod.op_path_check(outside_file,
                                             os.path.join(self.scope, "x.txt"),
                                             self.scope)
        self.assertFalse(ok)
        self.assertIn("escapes", reason)

    def test_destination_outside_scope_rejected(self):
        ok, reason = scope_mod.op_path_check(
            os.path.join(self.scope, "keep.txt"),
            os.path.join(self.outside, "copied.txt"),
            self.scope)
        self.assertFalse(ok)
        self.assertIn("escapes", reason)

    def test_destination_with_android_component_rejected(self):
        ok, reason = scope_mod.op_path_check(
            os.path.join(self.scope, "keep.txt"),
            os.path.join(self.scope, "Android", "x.txt"),
            self.scope)
        self.assertFalse(ok)
        self.assertIn("prohibited component", reason)

    def test_symlink_source_rejected(self):
        link = os.path.join(self.scope, "linkfile")
        try:
            os.symlink(os.path.join(self.scope, "keep.txt"), link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported")
        ok, reason = scope_mod.op_path_check(link,
                                             os.path.join(self.scope, "x.txt"),
                                             self.scope)
        self.assertFalse(ok)
        self.assertIn("symlink", reason)

    def test_ordinary_in_scope_pair_accepted(self):
        ok, reason = scope_mod.op_path_check(
            os.path.join(self.scope, "keep.txt"),
            os.path.join(self.scope, "Documents", "keep.txt"),
            self.scope)
        self.assertTrue(ok, reason)


class TestApplyUndoBranchAudit(HardeningTestCase):
    """Scope drift between plan creation and apply/undo must fail closed."""

    def _approved_plan(self, scope):
        conn = self.conn()
        scan_id = self.make_scan()
        plan_id, _ = organizer.build_plan(conn, scan_id, scope,
                                          storage_root=self.phone)
        executor.approve_plan(conn, plan_id, note="audit")
        return conn, plan_id

    def test_undo_refused_after_scope_deleted(self):
        scope = os.path.join(self.phone, "Documents")
        conn, plan_id = self._approved_plan(scope)
        try:
            result = executor.apply_plan(conn, plan_id)
            self.assertIn(result["status"], ("completed",))
            done = conn.execute(
                "SELECT id FROM organization_operations"
                " WHERE plan_id = ? AND status='completed' LIMIT 1",
                (plan_id,)).fetchone()
            self.assertIsNotNone(done)
            shutil.rmtree(scope)
            with self.assertRaises(executor.ExecutionError):
                executor.undo_operation(conn, done["id"],
                                        approve_delete_copy=True)
        finally:
            conn.close()

    def test_undo_refused_after_registry_revocation(self):
        custom = os.path.join(self.phone, "My Study Files")
        scope_mod.register_scope(custom, storage_root=self.phone)
        conn, plan_id = self._approved_plan(custom)
        try:
            executor.apply_plan(conn, plan_id)
            done = conn.execute(
                "SELECT id FROM organization_operations"
                " WHERE plan_id = ? AND status='completed' LIMIT 1",
                (plan_id,)).fetchone()
            scope_mod.unregister_scope(custom)
            with self.assertRaises(executor.ExecutionError):
                executor.undo_operation(conn, done["id"],
                                        approve_delete_copy=True)
        finally:
            conn.close()

    def test_policy_version_drift_is_journalled_not_widened(self):
        scope = os.path.join(self.phone, "Documents")
        conn, plan_id = self._approved_plan(scope)
        try:
            conn.execute(
                "UPDATE organization_plans SET scope_policy_version='org-scope-1'"
                " WHERE id = ?", (plan_id,))
            conn.commit()
            executor.apply_plan(conn, plan_id)   # current policy still enforced
            drift = conn.execute(
                "SELECT COUNT(*) FROM organization_events"
                " WHERE plan_id = ? AND event='scope_policy_mismatch'",
                (plan_id,)).fetchone()[0]
            self.assertEqual(drift, 1)
        finally:
            conn.close()
