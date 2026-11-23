"""Database layer: schema, migrations, transitions, isolation, integrity."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import os
import tempfile
import unittest

from storage_audit import database
from storage_audit.database import (
    STATUS_COMPLETED,
    STATUS_COMPLETED_WITH_GAPS,
    STATUS_RUNNING,
    InvalidStateTransition,
    DatabaseError,
)


def _fresh_db(tmpdir, name="test.sqlite3"):
    path = os.path.join(tmpdir, name)
    conn = database.connect(path)
    database.migrate(conn)
    return conn, path


def _make_run(conn, root="/fixture/root"):
    return database.create_run(
        conn, requested_root=root, root_path=root,
        tool_version="1.0.0-test", environment={"test": True},
        exclusions=[], batch_size=500)


class TestSchema(unittest.TestCase):
    def test_fresh_database_gets_schema_version(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(version, database.SCHEMA_VERSION)
            applied = conn.execute(
                "SELECT version FROM schema_migrations").fetchall()
            self.assertEqual([row[0] for row in applied], [1, 2, 3])
            conn.close()

    def test_migration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            database.migrate(conn)  # second run must not fail or duplicate
            rows = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
            self.assertEqual(rows, 3)
            conn.close()

    def test_foreign_keys_enabled(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            mode = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(mode, 1)
            conn.close()

    def test_newer_schema_refused(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            conn.execute("PRAGMA user_version = 99")
            with self.assertRaises(DatabaseError):
                database.migrate(conn)
            conn.close()


class TestRunLifecycle(unittest.TestCase):
    def test_status_transitions_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            run_id = _make_run(conn)
            database.transition_run(conn, run_id, STATUS_COMPLETED)
            with self.assertRaises(InvalidStateTransition):
                database.transition_run(conn, run_id, STATUS_RUNNING)
            conn.close()

    def test_completed_run_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            run_id = _make_run(conn)
            database.transition_run(conn, run_id, STATUS_COMPLETED)
            with self.assertRaises(InvalidStateTransition):
                database.transition_run(conn, run_id, STATUS_COMPLETED_WITH_GAPS)
            conn.close()

    def test_terminal_run_report_state_update_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            run_id = _make_run(conn)
            database.transition_run(conn, run_id, STATUS_COMPLETED)
            database.set_report_state(conn, run_id, "built", "/tmp/report")
            run = database.get_run(conn, run_id)
            self.assertEqual(run["report_state"], "built")
            conn.close()

    def test_entries_require_existing_run(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            with self.assertRaises(Exception):
                with conn:
                    conn.execute(
                        "INSERT INTO entries(scan_id, relative_path, absolute_path,"
                        " name, normalized_name, parent_relative_path, depth, kind,"
                        " category, observation_epoch, classification_version)"
                        " VALUES (999, 'x', '/x', 'x', 'x', '.', 1, 'file',"
                        " 'unknown', 0, '1.0.0')")
            conn.close()

    def test_duplicate_relative_path_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            run_id = _make_run(conn)
            row = dict(scan_id=run_id, relative_path="a.txt", absolute_path="/r/a.txt",
                       name="a.txt", normalized_name="a.txt",
                       parent_relative_path=".", depth=1, kind="file",
                       entry_subtype=None, extension="txt", extension_original="txt",
                       compound_extension=None, mime_guess="text/plain",
                       category="document", size_bytes=1, size_status="observed",
                       mtime_epoch=1, mtime_iso="2024-01-01 00:00:01+00:00",
                       timestamp_status="observed", birthtime_epoch=None,
                       birthtime_status="unavailable", is_hidden=0, is_symlink=0,
                       symlink_target=None, symlink_target_status=None,
                       is_readable=None, stat_status="ok", observation_epoch=1,
                       classification_version="1.0.0", device_id=1,
                       skip_reason=None, error_category=None, error_message=None)
            database.insert_entries(conn, [row])
            with self.assertRaises(Exception):
                database.insert_entries(conn, [row])
            conn.close()

    def test_run_isolation(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            r1 = _make_run(conn, "/root/one")
            r2 = _make_run(conn, "/root/two")
            database.transition_run(conn, r1, STATUS_COMPLETED)
            database.transition_run(conn, r2, STATUS_COMPLETED)
            for run_id in (r1, r2):
                row = database.get_run(conn, run_id)
                self.assertEqual(row["status"], STATUS_COMPLETED)
            latest = database.latest_run(conn)
            self.assertEqual(latest["id"], r2)
            conn.close()


class TestStaleRunRecovery(unittest.TestCase):
    def test_dead_pid_marked_interrupted(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            run_id = _make_run(conn)
            # Point the run at a pid that cannot exist.
            with conn:
                conn.execute("UPDATE scan_runs SET pid = ? WHERE id = ?",
                             (2 ** 22 + 12345, run_id))
            marked, uncertain = database.mark_interrupted_runs(conn)
            self.assertIn(run_id, marked)
            run = database.get_run(conn, run_id)
            self.assertEqual(run["status"], database.STATUS_INTERRUPTED)
            self.assertEqual(run["coverage_incomplete"], 1)
            conn.close()

    def test_alive_pid_left_running(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            run_id = _make_run(conn)
            with conn:
                conn.execute("UPDATE scan_runs SET pid = ? WHERE id = ?",
                             (os.getpid(), run_id))  # our own process is alive
            marked, uncertain = database.mark_interrupted_runs(conn)
            self.assertNotIn(run_id, marked)
            run = database.get_run(conn, run_id)
            self.assertEqual(run["status"], STATUS_RUNNING)
            conn.close()


class TestIntegrity(unittest.TestCase):
    def test_integrity_check_ok(self):
        with tempfile.TemporaryDirectory() as td:
            conn, _ = _fresh_db(td)
            ok, messages = database.integrity_check(conn)
            self.assertTrue(ok)
            self.assertEqual(messages, ["ok"])
            conn.close()


if __name__ == "__main__":
    unittest.main()
