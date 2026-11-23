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


class OrganizerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_org_test_")
        self.fixture = os.path.join(self.tmp, "phone")
        build_rich_fixture(self.fixture)
        self.db = os.path.join(self.tmp, "test.sqlite3")
        self.out = os.path.join(self.tmp, "out")
        self.target = os.path.join(self.tmp, "Organized")
        result = run_scan(self.fixture, db_path=self.db, output_dir=self.out,
                          progress=False)
        self.scan_id = result["run_id"]

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
        finally:
            conn.close()
        self.assertEqual(v, database.SCHEMA_VERSION)

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
        conn = self.conn()
        try:
            file_count = conn.execute(
                "SELECT COUNT(*) FROM entries"
                " WHERE scan_id = ? AND kind='file' AND stat_status='ok'",
                (self.scan_id,)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(len(ops), file_count)
        plan = conn_plan = None
        conn = self.conn()
        try:
            plan = conn.execute("SELECT * FROM organization_plans WHERE id = ?",
                                (plan_id,)).fetchone()
        finally:
            conn.close()
        self.assertEqual(plan["status"], "draft")
        self.assertEqual(plan["action"], "copy-keep")
        # every destination is inside the target root
        for op in ops:
            self.assertTrue(os.path.realpath(op["dest_abs"]).startswith(
                os.path.realpath(self.target) + os.sep) or
                os.path.realpath(op["dest_abs"]) == os.path.realpath(self.target))

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
        link = os.path.join(self.fixture, "linked_file.txt")
        if not os.path.islink(link):
            os.symlink("README", link)
        result = run_scan(self.fixture, db_path=self.db, output_dir=self.out,
                          progress=False)
        conn = self.conn()
        try:
            plan_id, _ = organizer.build_plan(conn, result["run_id"], self.target)
            ops = [dict(r) for r in conn.execute(
                "SELECT source_rel FROM organization_operations"
                " WHERE plan_id = ?", (plan_id,)).fetchall()]
        finally:
            conn.close()
        self.assertNotIn("linked_file.txt", [o["source_rel"] for o in ops])

    def test_filesystem_root_target_refused(self):
        conn = self.conn()
        try:
            with self.assertRaises(organizer.PlanError):
                organizer.build_plan(conn, self.scan_id, "/")
        finally:
            conn.close()

    def test_malicious_stored_path_stays_contained(self):
        conn = self.conn()
        try:
            conn.execute(
                "INSERT INTO entries(scan_id, relative_path, absolute_path, name,"
                " normalized_name, parent_relative_path, depth, kind, category,"
                " stat_status, observation_epoch, classification_version, device_id)"
                " VALUES (?, '../../../etc/evil.txt', '/x/evil.txt', 'evil.txt',"
                " 'evil.txt', '../../..', 3, 'file', 'document', 'ok', 0, '1.0.0', 1)",
                (self.scan_id,))
            conn.commit()
            plan_id, _ = organizer.build_plan(conn, self.scan_id, self.target)
            op = conn.execute(
                "SELECT dest_rel FROM organization_operations"
                " WHERE plan_id = ? AND source_rel = '../../../etc/evil.txt'",
                (plan_id,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(op)
        self.assertFalse(op["dest_rel"].startswith(".."))
        self.assertNotIn("..", op["dest_rel"].split(os.sep))

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
        conn = self.conn()
        try:
            row = conn.execute(
                "SELECT relative_path, category FROM entries"
                " WHERE scan_id = ? AND kind='file' AND category='document'"
                " ORDER BY relative_path LIMIT 1", (self.scan_id,)).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row)
        dest_rel = os.path.normpath(os.path.join(
            organizer.planner.category_folder(row["category"]),
            *[p for p in row["relative_path"].replace("\\", "/").split("/")
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
        self.assertFalse(os.path.exists(self.target))

    def test_move_plan_requires_source_removal_ack(self):
        plan_id, _ = self.make_plan(action="move")
        self.approve(plan_id)
        conn = self.conn()
        try:
            with self.assertRaises(executor.ExecutionError):
                executor.apply_plan(conn, plan_id)
        finally:
            conn.close()
        self.assertFalse(os.path.exists(self.target))  # nothing copied at all

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
        self.assertFalse(os.path.exists(self.target))

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
