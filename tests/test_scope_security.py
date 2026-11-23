"""MANDATORY organization-scope security tests (org-scope-1).

Maps 1:1 to the twenty required cases in ORGANIZATION_SCOPE_SECURITY_TESTS.md.
Every prohibited case demonstrates that NO organization operation is executed
and no file is created/modified/moved/deleted. All fixtures are synthetic.
No real user data, no device required; device-only cases are listed as NOT
TESTED in the document.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage_audit import database
from storage_audit.scanner import run_scan
from storage_audit import organizer
from storage_audit.organizer import executor
from storage_audit.organizer import scope as scope_mod
from storage_audit.organizer.scope import SCOPE_POLICY_VERSION


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


class ScopeTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="scope_sec_test_")
        self.phone = os.path.join(self.tmp, "shared")   # synthetic shared store
        os.makedirs(self.phone)
        # Permitted user-owned content
        _write(self.phone, "Documents/keep.txt")
        _write(self.phone, "Documents/reports/annual.pdf")
        _write(self.phone, "Documents/notes.md")
        # Android reserved tree — must NEVER be touched
        _write(self.phone, "Android/data/com.example.app/files/data.bin")
        _write(self.phone, "Android/obb/com.example.app/main.1.obb")
        _write(self.phone, "Android/media/com.whatsapp/Media/img.jpg")
        # Prohibited children INSIDE an allowed folder
        _write(self.phone, "Documents/Android/nested/app.bin")
        _write(self.phone, "Documents/.hidden_sub/secret.txt")
        # Hidden and reserved top-level dirs
        _write(self.phone, ".hidden_scope/secret.txt")
        _write(self.phone, "LOST.DIR/lost.txt")
        _write(self.phone, ".thumbnails/thumb.jpg")
        # Trash directory
        _write(self.phone, ".Trash-1000/tr.txt")
        # Outside location the scope must not leak into
        self.outside = os.path.join(self.tmp, "outside")
        _write(self.outside, "outside.txt")
        # Symlinks (created inside the scope, pointing outside it)
        try:
            os.symlink(os.path.join(self.phone, "Android"),
                       os.path.join(self.phone, "Documents", "link_to_android"))
            os.symlink(self.outside,
                       os.path.join(self.phone, "Documents", "link_outside"))
        except (OSError, NotImplementedError):
            pass
        self.db = os.path.join(self.tmp, "t.sqlite3")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_scan(self):
        result = run_scan(self.phone, db_path=self.db, output_dir=self.out,
                          progress=False)
        return result["run_id"]

    def conn(self):
        conn = database.connect(self.db)
        database.migrate(conn)
        return conn

    def assert_validate_rejects(self, path, reason_part):
        verdict = scope_mod.validate_scope(path)
        self.assertFalse(verdict["ok"],
                         "expected rejection of {!r}".format(path))
        self.assertTrue(any(reason_part in r for r in verdict["reasons"]),
                        "reasons {!r} lack {!r}".format(verdict["reasons"],
                                                        reason_part))
        return verdict

    def plan_on(self, scope, scan_id=None):
        scan_id = scan_id if scan_id is not None else self.make_scan()
        conn = self.conn()
        try:
            return organizer.build_plan(conn, scan_id, scope)
        finally:
            conn.close()


# ---------------------------------------------------------------- M01–M09
class TestProhibitedTargets(ScopeTestCase):
    def test_m01_selecting_android_root_rejected(self):
        path = os.path.join(self.phone, "Android")
        snap = _tree_snapshot(path)
        self.assert_validate_rejects(path, "protected_android")
        conn = self.conn()
        try:
            with self.assertRaises(organizer.ScopeRejected):
                organizer.build_plan(conn, self.make_scan(), path)
        finally:
            conn.close()
        self.assertEqual(snap, _tree_snapshot(path))  # nothing touched

    def test_m02_selecting_android_data_rejected(self):
        snap = _tree_snapshot(os.path.join(self.phone, "Android", "data"))
        self.assert_validate_rejects(os.path.join(self.phone, "Android",
                                                  "data"), "protected_android")
        self.assertEqual(snap, _tree_snapshot(os.path.join(self.phone,
                                                           "Android", "data")))

    def test_m03_selecting_android_obb_rejected(self):
        p = os.path.join(self.phone, "Android", "obb")
        snap = _tree_snapshot(p)
        self.assert_validate_rejects(p, "protected_android")
        self.assertEqual(snap, _tree_snapshot(p))

    def test_m04_selecting_android_media_rejected(self):
        p = os.path.join(self.phone, "Android", "media")
        snap = _tree_snapshot(p)
        self.assert_validate_rejects(p, "protected_android")
        self.assertEqual(snap, _tree_snapshot(p))

    def test_m05_selecting_nested_application_directory_rejected(self):
        p = os.path.join(self.phone, "Android", "data", "com.example.app",
                         "files")
        snap = _tree_snapshot(p)
        self.assert_validate_rejects(p, "protected_android")
        self.assertEqual(snap, _tree_snapshot(p))

    def test_m06_selecting_termux_private_storage_rejected(self):
        priv = os.path.join(self.tmp, "termux_private")
        os.makedirs(priv)
        _write(priv, "installation_marker.txt")
        with mock.patch.dict(os.environ, {"PREFIX": priv}):
            verdict = scope_mod.validate_scope(priv)
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("termux_private" in r for r in verdict["reasons"]),
                        verdict["reasons"])

    def test_m07_selecting_protected_system_directory_rejected(self):
        # Hermetic synthetic system prefix (tests may not create /system);
        # the real prefixes ship in DEFAULT_PROTECTED_PREFIXES.
        fake_sys = os.path.join(self.tmp, "system_root")
        os.makedirs(fake_sys)
        _write(fake_sys, "build.prop")
        verdict = scope_mod.validate_scope(fake_sys,
                                           protected_prefixes=(fake_sys,))
        self.assertFalse(verdict["ok"])
        self.assertTrue(any("protected_system" in r
                            for r in verdict["reasons"]), verdict["reasons"])
        # And the shipped defaults really do cover the real system roots:
        for pref in ("/system", "/vendor", "/product", "/apex", "/data"):
            self.assertIn(pref, scope_mod.DEFAULT_PROTECTED_PREFIXES)

    def test_m08_selecting_hidden_directory_rejected(self):
        p = os.path.join(self.phone, ".hidden_scope")
        snap = _tree_snapshot(p)
        self.assert_validate_rejects(p, "hidden")
        self.assertEqual(snap, _tree_snapshot(p))

    def test_m09_selecting_unknown_or_reserved_directory_rejected(self):
        for name in ("LOST.DIR", ".thumbnails", ".Trash-1000"):
            p = os.path.join(self.phone, name)
            snap = _tree_snapshot(p)
            verdict = scope_mod.validate_scope(p)
            self.assertFalse(verdict["ok"], name)
            self.assertEqual(snap, _tree_snapshot(p), name)


# ---------------------------------------------------------------- M10–M13
class TestPermittedAndBoundaries(ScopeTestCase):
    def test_m10_selecting_allowed_personal_folder_permitted(self):
        scope = os.path.join(self.phone, "Documents")
        verdict = scope_mod.validate_scope(scope)
        self.assertTrue(verdict["ok"], verdict["reasons"])
        plan_id, stats = self.plan_on(scope)
        self.assertGreater(stats["operations"], 0)
        canonical_scope = os.path.realpath(scope)
        conn = self.conn()
        try:
            ops = [dict(r) for r in conn.execute(
                "SELECT source_abs, dest_abs FROM organization_operations"
                " WHERE plan_id = ?", (plan_id,))]
        finally:
            conn.close()
        for op in ops:
            self.assertTrue(os.path.realpath(op["source_abs"]).startswith(
                canonical_scope + os.sep))
            self.assertTrue(os.path.realpath(op["dest_abs"]).startswith(
                canonical_scope + os.sep))

    def test_m11_allowed_folder_with_prohibited_child_excluded(self):
        scope = os.path.join(self.phone, "Documents")
        plan_id, stats = self.plan_on(scope)
        reasons = {}
        conn = self.conn()
        try:
            excluded = [dict(r) for r in conn.execute(
                "SELECT detail FROM organization_events"
                " WHERE plan_id = ? AND event = 'skipped_source'",
                (plan_id,))]
            op_paths = [dict(r) for r in conn.execute(
                "SELECT source_abs, dest_abs FROM organization_operations"
                " WHERE plan_id = ?", (plan_id,))]
        finally:
            conn.close()
        details = " | ".join(r["detail"] for r in excluded)
        self.assertIn("protected_android", details)
        self.assertIn("hidden", details)
        for op in op_paths:
            norm_src = op["source_abs"].replace("\\", "/")
            self.assertNotIn("/Android/", norm_src)
            self.assertNotIn("/.hidden_sub/", norm_src)
            self.assertNotIn("/link_to_android/", norm_src)
        self.assertGreaterEqual(stats["excluded_entries"], 4)  # android+hidden+3 links

    def test_m12_symlink_into_android_never_followed(self):
        scope = os.path.join(self.phone, "Documents")
        plan_id, _stats = self.plan_on(scope)
        conn = self.conn()
        try:
            ops = [dict(r) for r in conn.execute(
                "SELECT source_abs FROM organization_operations"
                " WHERE plan_id = ?", (plan_id,))]
        finally:
            conn.close()
        for op in ops:
            rel = os.path.relpath(op["source_abs"], scope)
            self.assertNotIn("link_to_android", rel.split(os.sep))
        # Target selection via a symlink is rejected outright
        link = os.path.join(self.phone, "Documents", "link_to_android")
        if os.path.islink(link):
            verdict = scope_mod.validate_scope(link)
            self.assertFalse(verdict["ok"])

    def test_m13_symlink_outside_selected_root_excluded(self):
        scope = os.path.join(self.phone, "Documents")
        plan_id, _stats = self.plan_on(scope)
        conn = self.conn()
        try:
            ops = [dict(r) for r in conn.execute(
                "SELECT source_abs FROM organization_operations"
                " WHERE plan_id = ?", (plan_id,))]
            details = [r[0] for r in conn.execute(
                "SELECT detail FROM organization_events"
                " WHERE plan_id = ? AND event='skipped_source'",
                (plan_id,))]
        finally:
            conn.close()
        for op in ops:
            self.assertTrue(os.path.realpath(op["source_abs"]).startswith(
                os.path.realpath(scope) + os.sep))
        self.assertTrue(any("link_outside" in d for d in details))


# ---------------------------------------------------------------- M14–M20
class TestExecutionTimeEnforcement(ScopeTestCase):
    def _approved_plan(self):
        scope = os.path.join(self.phone, "Documents")
        plan_id, _ = self.plan_on(scope)
        conn = self.conn()
        try:
            executor.approve_plan(conn, plan_id, note="scope test approval")
        finally:
            conn.close()
        return plan_id

    def _first_op_id(self, plan_id):
        conn = self.conn()
        try:
            row = conn.execute(
                "SELECT id FROM organization_operations"
                " WHERE plan_id = ? ORDER BY seq LIMIT 1", (plan_id,)
            ).fetchone()
        finally:
            conn.close()
        return row["id"]

    def _apply(self, plan_id, **kwargs):
        conn = self.conn()
        try:
            return executor.apply_plan(conn, plan_id, **kwargs)
        finally:
            conn.close()

    def test_m14_destination_inside_android_refused(self):
        plan_id = self._approved_plan()
        op_id = self._first_op_id(plan_id)
        android_dest = os.path.join(self.phone, "Documents", "Android",
                                    "evil.jpg")
        conn = self.conn()
        try:
            conn.execute(
                "UPDATE organization_operations"
                " SET dest_abs = ?, dest_rel = ? WHERE id = ?",
                (android_dest, os.path.join("Android", "evil.jpg"), op_id))
            conn.commit()
            executor.apply_plan(conn, plan_id)
            row = conn.execute(
                "SELECT status, error FROM organization_operations"
                " WHERE id = ?", (op_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "failed")
        self.assertIn("scope", row["error"].lower() + "prohibited")
        self.assertFalse(os.path.exists(android_dest))

    def test_m15_destination_outside_selected_root_refused(self):
        plan_id = self._approved_plan()
        op_id = self._first_op_id(plan_id)
        outside_dest = os.path.join(self.outside, "evil.jpg")
        conn = self.conn()
        try:
            conn.execute(
                "UPDATE organization_operations"
                " SET dest_abs = ?, dest_rel = ? WHERE id = ?",
                (outside_dest, "../../outside/evil.jpg", op_id))
            conn.commit()
            executor.apply_plan(conn, plan_id)
            row = conn.execute(
                "SELECT status FROM organization_operations"
                " WHERE id = ?", (op_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "failed")
        self.assertFalse(os.path.exists(outside_dest))

    def test_m16_path_changing_after_plan_creation_refused(self):
        plan_id = self._approved_plan()
        scope = os.path.join(self.phone, "Documents")
        moved_scope = os.path.join(self.phone, "Documents_moved")
        os.rename(scope, moved_scope)
        conn = self.conn()
        try:
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        # Nothing organized anywhere
        self.assertFalse(os.path.exists(
            os.path.join(moved_scope, "Images")))
        self.assertFalse(os.path.exists(
            os.path.join(moved_scope, "Documents")))

    def test_m17a_scope_subdirectory_swapped_to_symlink_refused(self):
        plan_id = self._approved_plan()
        scope = os.path.join(self.phone, "Documents")
        sub = os.path.join(scope, "reports")
        moved = os.path.join(self.tmp, "reports_real")
        os.rename(sub, moved)
        os.symlink(moved, sub)
        conn = self.conn()
        try:
            result = executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        # The planned op under reports/ resolved outside the scope at
        # execution time and must have failed — nothing executed from it.
        conn = self.conn()
        try:
            failed = [dict(r) for r in conn.execute(
                "SELECT source_abs, status, error FROM organization_operations"
                " WHERE plan_id = ? AND source_abs LIKE ?",
                (plan_id, os.path.join(scope, "reports") + "%"))]
        finally:
            conn.close()
        self.assertTrue(failed)
        for row in failed:
            self.assertEqual(row["status"], "failed")
            self.assertIn("scope", row["error"])

    def test_m17b_scope_root_replaced_by_symlink_refused(self):
        plan_id = self._approved_plan()
        scope = os.path.join(self.phone, "Documents")
        moved = os.path.join(self.phone, "Documents_real")
        os.rename(scope, moved)
        os.symlink(moved, scope)
        conn = self.conn()
        try:
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
        finally:
            conn.close()

    def test_m18_batch_mixed_allowed_and_prohibited_only_allowed_runs(self):
        scope = os.path.join(self.phone, "Documents")
        plan_id, stats = self.plan_on(scope)
        self.assertGreater(stats["operations"], 0)
        before = _tree_snapshot(scope)
        # Verify the plan contains NO prohibited source at all
        conn = self.conn()
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT source_abs FROM organization_operations"
                " WHERE plan_id = ?", (plan_id,))]
            executor.approve_plan(conn, plan_id, note="m18")
            result = executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        for row in rows:
            rel = row["source_abs"].replace("\\", "/")
            self.assertNotIn("/Android/", rel)
            self.assertNotIn("/.hidden_sub/", rel)
        self.assertEqual(result["failed"], 0)
        # Files CREATED by the apply never carry a prohibited component
        after = _tree_snapshot(scope)
        created = [rel for rel in after if rel not in before]
        self.assertTrue(created)
        for rel in created:
            parts = rel.replace("\\", "/").split("/")
            self.assertNotIn("Android", parts)
            self.assertNotIn(".hidden_sub", parts)

    def test_m19_rule_output_crossing_scope_refused(self):
        plan_id = self._approved_plan()
        op_id = self._first_op_id(plan_id)
        conn = self.conn()
        try:
            row = conn.execute(
                "SELECT dest_abs FROM organization_operations"
                " WHERE id = ?", (op_id,)).fetchone()
            # Simulate a rule that tried to place the destination outside the
            # approved scope (no override exists in code either).
            escaped = os.path.join(self.tmp, "escaped.jpg")
            conn.execute(
                "UPDATE organization_operations"
                " SET dest_abs = ?, dest_rel = ? WHERE id = ?",
                (escaped, "../escaped.jpg", op_id))
            conn.commit()
            executor.apply_plan(conn, plan_id)
            row_after = conn.execute(
                "SELECT status FROM organization_operations WHERE id = ?",
                (op_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(row_after["status"], "failed")
        self.assertFalse(os.path.exists(escaped))

    def test_m20_interrupted_plan_cannot_resume_outside_original_scope(self):
        plan_id = self._approved_plan()
        op_id = self._first_op_id(plan_id)
        # Simulate a crashed apply: plan + op left in-flight, then tampered
        # by a hypothetical buggy resume attempt to write elsewhere.
        conn = self.conn()
        try:
            conn.execute(
                "UPDATE organization_plans SET status='executing'"
                " WHERE id = ?", (plan_id,))
            conn.execute(
                "UPDATE organization_operations SET status='in_progress',"
                " dest_abs = ? WHERE id = ?",
                (os.path.join(self.outside, "resumed.jpg"), op_id))
            conn.commit()
            n = executor.reconcile_interrupted(conn, plan_id=plan_id)
            result = executor.apply_plan(conn, plan_id)
            row = conn.execute(
                "SELECT status FROM organization_operations WHERE id = ?",
                (op_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(n, 1)          # honest interruption handling
        self.assertEqual(row["status"], "interrupted")  # never assumed done
        self.assertFalse(os.path.exists(os.path.join(self.outside,
                                                     "resumed.jpg")))


if __name__ == "__main__":
    unittest.main()
