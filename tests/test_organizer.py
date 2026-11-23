"""V2 organization engine: planner, gating, execution safety, undo, migration.

All fixtures are synthetic (tests/helpers.py). Nothing here touches real
user data. The engine's core invariants are tested directly.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_rich_fixture

from storage_audit import database
from storage_audit.scanner import run_scan, make_cancel_event
from storage_audit import organizer
from storage_audit.organizer import executor
from storage_audit.organizer import scope as scope_mod
from storage_audit import classifier


class OrganizerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_org_test_")
        self.fixture = os.path.join(self.tmp, "phone")
        build_rich_fixture(self.fixture)
        self.db = os.path.join(self.tmp, "test.sqlite3")
        self.out = os.path.join(self.tmp, "out")
        # Under org-scope-1 the organization scope is the selected folder
        # itself: operations stay inside it. Use the synthetic fixture as the
        # user-owned folder to organize (never real user data).
        self.target = self.fixture
        result = run_scan(self.fixture, db_path=self.db, output_dir=self.out,
                          progress=False)
        self.scan_id = result["run_id"]
        self._scope_snapshot = sorted(os.listdir(self.fixture))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conn(self):
        conn = database.connect(self.db)
        database.migrate(conn)
        return conn

    def make_plan(self, **kwargs):
        conn = self.conn()
        try:
            return organizer.build_plan(conn, self.scan_id, self.target, **kwargs)
        finally:
            conn.close()

    def approve(self, plan_id):
        conn = self.conn()
        try:
            executor.approve_plan(conn, plan_id, note="test approval")
        finally:
            conn.close()

    def plan_ops(self, plan_id, status=None):
        conn = self.conn()
        try:
            sql = "SELECT * FROM organization_operations WHERE plan_id = ?"
            params = [plan_id]
            if status:
                sql += " AND status = ?"
                params.append(status)
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()


class TestMigrationToV2(OrganizerTestCase):
    def test_fresh_db_has_v2_tables(self):
        conn = self.conn()
        try:
            conn.execute("SELECT id FROM organization_plans LIMIT 1")
            conn.execute("SELECT id FROM organization_operations LIMIT 1")
            conn.execute("SELECT id FROM organization_events LIMIT 1")
            v = conn.execute("PRAGMA user_version").fetchone()[0]
            mig = [r[0] for r in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version")]
        finally:
            conn.close()
        self.assertEqual(v, database.SCHEMA_VERSION)
        self.assertEqual(v, 3)
        self.assertEqual(mig, [1, 2, 3])

    def test_v1_database_migrates_and_preserves_data(self):
        # Build a v1-shaped database by hand, then migrate.
        path = os.path.join(self.tmp, "v1.sqlite3")
        import sqlite3, time
        conn = sqlite3.connect(path)
        conn.executescript(database.SCHEMA_SQL)
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at)"
                     " VALUES (1, ?)", (int(time.time()),))
        conn.execute("PRAGMA user_version = 1")
        conn.execute(
            "INSERT INTO scan_runs (tool_version, schema_version, requested_root,"
            " root_path, started_at_epoch, status, pid, classification_version,"
            " environment_json, exclusions_json, batch_size, scan_mode)"
            " VALUES ('1.0.0', 1, '/x', '/x', 1, 'completed', 1, '1.0.0',"
            " '{}', '[]', 500, 'metadata_only')")
        conn.commit()
        conn.close()

        conn = database.connect(path)
        try:
            database.migrate(conn)
            v = conn.execute("PRAGMA user_version").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM scan_runs").fetchone()[0]
            conn.execute("SELECT COUNT(*) FROM organization_operations")
        finally:
            conn.close()
        self.assertEqual(v, database.SCHEMA_VERSION)
        self.assertEqual(runs, 1)  # history preserved


class TestPlanner(OrganizerTestCase):
    def test_plan_is_draft_and_counts_files_only(self):
        plan_id, stats = self.make_plan()
        self.assertGreater(stats["operations"], 0)
        ops = self.plan_ops(plan_id)
        self.assertEqual(len(ops), stats["operations"])
        expected_eligible = len(scope_mod.walk_eligible(
            os.path.realpath(self.target))[0])
        self.assertEqual(stats["eligible_files"], expected_eligible)
        # ops + (skips that consumed an eligible file) == eligible files
        self.assertLessEqual(stats["operations"], stats["eligible_files"])
        conn = self.conn()
        try:
            plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                                (plan_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(plan["action"], "copy-keep")
        self.assertEqual(plan["scope_policy_version"], "org-scope-1")
        self.assertEqual(plan["scope_canonical"],
                         os.path.realpath(self.target))
        self.assertGreaterEqual(plan["excluded_entries"], 1)  # hidden + links
        # every destination is inside the approved scope
        scope = os.path.realpath(self.target)
        for op in ops:
            dest = os.path.realpath(op["dest_abs"])
            self.assertTrue(dest == scope or dest.startswith(scope + os.sep))
            # and every source is inside the scope too
            src = os.path.realpath(op["source_abs"])
            self.assertTrue(src == scope or src.startswith(scope + os.sep))

    def test_category_folders_and_unsorted(self):
        plan_id, _ = self.make_plan()
        ops = self.plan_ops(plan_id)
        for op in ops:
            top = op["dest_rel"].split(os.sep)[0]
            self.assertIn(top, {"Images", "Videos", "Audio", "Documents",
                                "Archives", "Packages", "Databases", "Code",
                                "Fonts", "Backups", "System", "Unsorted", "Other"})
        names = [op["source_rel"] for op in ops]
        self.assertTrue(any(n.endswith(".jpg") or n.endswith(".JPG") for n in names))

    def test_symlinks_are_never_planned(self):
        plan_id, stats = self.make_plan()
        ops = self.plan_ops(plan_id)
        names = [o["source_rel"] for o in ops]
        # fixture symlinks live in Download/ and point elsewhere/broken
        self.assertNotIn(os.path.join("Download", "report_link.txt"), names)
        self.assertNotIn(os.path.join("Download", "docs_dir_link"), names)
        self.assertNotIn(os.path.join("Download", "broken_link"), names)
        # excluded with an explicit reason, never followed
        conn = self.conn()
        try:
            events = [r[0] for r in conn.execute(
                "SELECT detail FROM organization_events"
                " WHERE plan_id = ? AND event = 'skipped_source'", (plan_id,))]
        finally:
            conn.close()
        self.assertTrue(any("symlink" in e for e in events))

    def test_filesystem_root_target_refused(self):
        conn = self.conn()
        try:
            with self.assertRaises(organizer.ScopeRejected):
                organizer.build_plan(conn, self.scan_id, "/")
        finally:
            conn.close()

    def test_malicious_stored_dest_outside_scope_is_refused_at_apply(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        outside = os.path.join(self.tmp, "outside.txt")
        conn = self.conn()
        try:
            op = conn.execute(
                "SELECT id FROM organization_operations"
                " WHERE plan_id = ? ORDER BY seq LIMIT 1", (plan_id,)).fetchone()
            conn.execute(
                "UPDATE organization_operations SET dest_abs = ? WHERE id = ?",
                (outside, op["id"]))
            conn.commit()
            result = executor.apply_plan(conn, plan_id)
            row = conn.execute(
                "SELECT status, error FROM organization_operations"
                " WHERE id = ?", (op["id"],)).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "failed")
        self.assertIn("scope", row["error"] or "")
        self.assertFalse(os.path.exists(outside))
        self.assertEqual(result["failed"], 1)

    def test_non_completed_scan_refused(self):
        conn = self.conn()
        try:
            conn.execute("UPDATE scan_runs SET status='failed' WHERE id = ?",
                         (self.scan_id,))
            conn.commit()
            with self.assertRaises(organizer.PlanError):
                organizer.build_plan(conn, self.scan_id, self.target)
        finally:
            conn.close()

    def test_conflict_with_existing_destination_flagged(self):
        # Pre-create one colliding destination: <target>/Documents/... for the
        # first document-like file in the fixture.
        eligible, _ex, _al = scope_mod.walk_eligible(os.path.realpath(self.target))
        candidate = None
        for item in eligible:
            ext, _c, _o = classifier.split_extension(os.path.basename(item["source_rel"]))
            cat = classifier.classify_extension(ext) if ext else "unknown"
            if cat == "document":
                candidate = (item["source_rel"], cat)
                break
        self.assertIsNotNone(candidate)
        rel, cat = candidate
        dest_rel = os.path.normpath(os.path.join(
            organizer.planner.category_folder(cat),
            *[p for p in rel.replace("\\", "/").split("/")
              if p not in ("", ".", "..")]))
        dest_abs = os.path.join(self.target, dest_rel)
        os.makedirs(os.path.dirname(dest_abs), exist_ok=True)
        with open(dest_abs, "wb") as fh:
            fh.write(b"PRE-EXISTING - MUST NOT BE OVERWRITTEN")
        plan_id, stats = self.make_plan()
        self.assertGreaterEqual(stats["conflicts"], 1)
        ops = [o for o in self.plan_ops(plan_id) if o["status"] == "conflict"]
        self.assertTrue(any(o["dest_abs"] == os.path.normpath(dest_abs) for o in ops))


class TestExecutionGating(OrganizerTestCase):
    def test_apply_requires_approved_plan(self):
        plan_id, _ = self.make_plan()
        conn = self.conn()
        try:
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        # nothing copied/created — scope is exactly as it was at setUp
        self.assertEqual(sorted(os.listdir(self.target)), self._scope_snapshot)
        conn = self.conn()
        try:
            done = conn.execute(
                "SELECT COUNT(*) FROM organization_operations"
                " WHERE plan_id = ? AND status = 'completed'", (plan_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(done, 0)

    def test_move_plan_requires_source_removal_ack(self):
        plan_id, _ = self.make_plan(action="move")
        self.approve(plan_id)
        conn = self.conn()
        try:
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        # nothing copied/created — scope is exactly as it was at setUp
        self.assertEqual(sorted(os.listdir(self.target)), self._scope_snapshot)
        conn = self.conn()
        try:
            done = conn.execute(
                "SELECT COUNT(*) FROM organization_operations"
                " WHERE plan_id = ? AND status = 'completed'", (plan_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(done, 0)  # nothing copied at all

    def test_copy_keep_end_to_end(self):
        plan_id, stats = self.make_plan()
        self.approve(plan_id)
        conn = self.conn()
        try:
            result = executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["status"], "completed")
        ops = self.plan_ops(plan_id)
        checked = 0
        for op in ops:
            self.assertTrue(os.path.isfile(op["source_abs"]))     # source kept
            self.assertTrue(os.path.isfile(op["dest_abs"]))       # copy written
            self.assertEqual(os.stat(op["source_abs"]).st_size,
                             os.stat(op["dest_abs"]).st_size)
            checked += 1
        self.assertGreater(checked, 5)

    def test_move_end_to_end_with_ack(self):
        plan_id, _ = self.make_plan(action="move")
        self.approve(plan_id)
        conn = self.conn()
        try:
            result = executor.apply_plan(conn, plan_id,
                                         acknowledge_source_removal=True)
        finally:
            conn.close()
        self.assertEqual(result["failed"], 0)
        for op in self.plan_ops(plan_id):
            self.assertFalse(os.path.exists(op["source_abs"]))
            self.assertTrue(os.path.isfile(op["dest_abs"]))

    def test_hash_verify_detects_corruption(self):
        plan_id, _ = self.make_plan(hash_verify=True)
        self.approve(plan_id)
        conn = self.conn()
        real_copy = executor._copy_file
        def corrupting_copy(src, dst):
            real_copy(src, dst)
            with open(dst, "ab") as fh:            # append a byte AFTER copy
                fh.write(b"\x00")
        with mock.patch.object(executor, "_copy_file", corrupting_copy):
            try:
                result = executor.apply_plan(conn, plan_id)
            finally:
                conn.close()
        self.assertGreater(result["failed"], 0)
        # every source must still exist — failure must not destroy data
        for op in self.plan_ops(plan_id, status="failed"):
            self.assertTrue(os.path.isfile(op["source_abs"]))

    def test_destination_appearing_mid_run_is_not_overwritten(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        ops = self.plan_ops(plan_id, status="planned")
        victim = ops[0]
        os.makedirs(os.path.dirname(victim["dest_abs"]), exist_ok=True)
        with open(victim["dest_abs"], "wb") as fh:
            fh.write(b"SENTINEL")
        conn = self.conn()
        try:
            result = executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        with open(victim["dest_abs"], "rb") as fh:
            self.assertEqual(fh.read(), b"SENTINEL")   # untouched
        self.assertTrue(os.path.isfile(victim["source_abs"]))
        self.assertEqual(result["failed"], 1)          # that op failed, others ran

    def test_source_disappearing_fails_op_not_crash(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        ops = self.plan_ops(plan_id, status="planned")
        os.remove(ops[0]["source_abs"])
        conn = self.conn()
        try:
            result = executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        self.assertGreaterEqual(result["failed"], 1)
        self.assertEqual(result["status"], "completed_with_errors")

    def test_cancel_event_leaves_plan_cancelled(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        event = make_cancel_event()
        event.set()
        conn = self.conn()
        try:
            result = executor.apply_plan(conn, plan_id, cancel_event=event)
        finally:
            conn.close()
        self.assertEqual(result["status"], "cancelled")

    def test_stop_on_error_marks_recovery_required(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        ops = self.plan_ops(plan_id, status="planned")
        os.remove(ops[0]["source_abs"])
        conn = self.conn()
        try:
            executor.apply_plan(conn, plan_id, stop_on_error=True)
            plan = conn.execute("SELECT status FROM organization_plans"
                                " WHERE id = ?", (plan_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(plan["status"], "recovery_required")

    def test_insufficient_space_refuses_before_copying(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        conn = self.conn()
        try:
            with mock.patch.object(executor.shutil, "disk_usage") as du:
                du.return_value = mock.Mock(free=1)
                with self.assertRaises(executor.ExecutionError):
                    executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        # nothing copied/created — scope is exactly as it was at setUp
        self.assertEqual(sorted(os.listdir(self.target)), self._scope_snapshot)
        conn = self.conn()
        try:
            done = conn.execute(
                "SELECT COUNT(*) FROM organization_operations"
                " WHERE plan_id = ? AND status = 'completed'", (plan_id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(done, 0)

    def test_reconcile_marks_in_progress_interrupted(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        ops = self.plan_ops(plan_id, status="planned")
        conn = self.conn()
        try:
            conn.execute("UPDATE organization_operations SET status='in_progress'"
                         " WHERE id = ?", (ops[0]["id"],))
            conn.commit()
            n = executor.reconcile_interrupted(conn, plan_id=plan_id)
            row = conn.execute("SELECT status FROM organization_operations"
                               " WHERE id = ?", (ops[0]["id"],)).fetchone()
        finally:
            conn.close()
        self.assertEqual(n, 1)
        self.assertEqual(row["status"], "interrupted")


class TestUndo(OrganizerTestCase):
    def test_undo_move_restores_original(self):
        plan_id, _ = self.make_plan(action="move")
        self.approve(plan_id)
        conn = self.conn()
        try:
            executor.apply_plan(conn, plan_id, acknowledge_source_removal=True)
        finally:
            conn.close()
        op = [o for o in self.plan_ops(plan_id) if o["status"] == "completed"][0]
        conn = self.conn()
        try:
            result = executor.undo_operation(conn, op["id"])
        finally:
            conn.close()
        self.assertEqual(result, "restored")
        self.assertTrue(os.path.isfile(op["source_abs"]))
        self.assertFalse(os.path.exists(op["dest_abs"]))

    def test_undo_copy_keep_requires_approve_delete(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        conn = self.conn()
        try:
            executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        op = self.plan_ops(plan_id)[0]
        conn = self.conn()
        try:
            with self.assertRaises(executor.ExecutionError):
                executor.undo_operation(conn, op["id"])  # no approval
            result = executor.undo_operation(conn, op["id"],
                                             approve_delete_copy=True)
        finally:
            conn.close()
        self.assertEqual(result, "copy-deleted")
        self.assertTrue(os.path.isfile(op["source_abs"]))

    def test_undo_refuses_when_dest_changed(self):
        plan_id, _ = self.make_plan()
        self.approve(plan_id)
        conn = self.conn()
        try:
            executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        op = self.plan_ops(plan_id)[0]
        with open(op["dest_abs"], "ab") as fh:
            fh.write(b"changed by someone else")
        conn = self.conn()
        try:
            with self.assertRaises(executor.ExecutionError):
                executor.undo_operation(conn, op["id"], approve_delete_copy=True)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
