"""Scanner: end-to-end fixture scans through the real code paths."""

import os
import shutil
import signal
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_rich_fixture, snapshot_tree

from storage_audit import database
from storage_audit.scanner import run_scan, make_cancel_event


class ScanTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_scan_test_")
        self.fixture = os.path.join(self.tmp, "phone")
        build_rich_fixture(self.fixture)
        self.db = os.path.join(self.tmp, "test.sqlite3")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_fixture(self, fixture=None, **kwargs):
        kwargs.setdefault("progress", False)
        return run_scan(fixture or self.fixture, db_path=self.db,
                        output_dir=self.out, **kwargs)

    def entries(self, run_id):
        conn = database.connect(self.db)
        try:
            rows = conn.execute(
                "SELECT * FROM entries WHERE scan_id = ?", (run_id,)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


class TestRichFixtureScan(ScanTestCase):
    def test_completed_status_and_counts(self):
        result = self.run_fixture()
        self.assertIn(result["status"],
                      (database.STATUS_COMPLETED,
                       database.STATUS_COMPLETED_WITH_GAPS))
        entries = self.entries(result["run_id"])
        kinds = {}
        for e in entries:
            kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1

        files = [e for e in entries if e["kind"] == "file"]
        dirs = [e for e in entries if e["kind"] == "directory"]
        symlinks = [e for e in entries if e["kind"] == "symlink"]

        self.assertGreaterEqual(len(files), 20)
        self.assertGreaterEqual(len(dirs), 15)
        self.assertGreaterEqual(len(symlinks), 2)
        self.assertEqual(result["files_recorded"], len(
            [f for f in files if f["stat_status"] == "ok"]))
        self.assertEqual(result["directories_recorded"], len(dirs))

    def test_hidden_entries_included(self):
        result = self.run_fixture()
        rels = {e["relative_path"] for e in self.entries(result["run_id"])}
        self.assertIn(".hidden_file", rels)
        hidden = [e for e in self.entries(result["run_id"]) if e["is_hidden"]]
        hidden_names = {e["name"] for e in hidden}
        self.assertIn(".hidden_file", hidden_names)
        self.assertIn(".hidden_dir", hidden_names)

    def test_empty_directories_recorded(self):
        result = self.run_fixture()
        conn = database.connect(self.db)
        try:
            empties = {row["relative_path"] for row in conn.execute(
                "SELECT relative_path FROM directory_stats"
                " WHERE scan_id = ? AND is_empty = 1", (result["run_id"],))}
        finally:
            conn.close()
        self.assertIn(os.path.join("EmptyDir", "nested_empty"), empties)
        self.assertNotIn("EmptyDir", empties)  # contains a child dir
        self.assertNotIn("Documents", empties)

    def test_zero_byte_file_recorded(self):
        result = self.run_fixture()
        zeros = [e for e in self.entries(result["run_id"])
                 if e["kind"] == "file" and e["size_bytes"] == 0]
        self.assertTrue(any(e["name"] == "zero.bin" for e in zeros))

    def test_symlink_to_directory_not_followed(self):
        result = self.run_fixture()
        entries = self.entries(result["run_id"])
        link_rows = [e for e in entries if e["is_symlink"]]
        self.assertTrue(any(e["name"] == "docs_dir_link" for e in link_rows))
        # The symlinked dir's contents must NOT appear under the link path.
        under_link = [e for e in entries
                      if e["relative_path"].startswith(
                          os.path.join("Download", "docs_dir_link") + os.sep)]
        self.assertEqual(under_link, [])

    def test_symlink_loop_does_not_hang(self):
        result = self.run_fixture()  # would hang if symlinks were followed
        self.assertIn(result["status"],
                      (database.STATUS_COMPLETED,
                       database.STATUS_COMPLETED_WITH_GAPS))

    def test_deep_nesting(self):
        result = self.run_fixture()
        rels = {e["relative_path"] for e in self.entries(result["run_id"])}
        deep = os.path.join("DCIM", "deep", "a", "b", "c", "d", "e", "f",
                            "deepfile.txt")
        self.assertIn(deep, rels)

    def test_unicode_and_special_names(self):
        result = self.run_fixture()
        entries = self.entries(result["run_id"])
        names = {e["name"] for e in entries}
        self.assertIn("रिपोर्ट.txt", names)
        self.assertIn("emoji 🎉 photo.jpg", names)
        self.assertTrue(any("\n" in n for n in names))
        self.assertTrue(any("\t" in n for n in names))
        self.assertTrue(any("onerror" in n for n in names))

    def test_injection_filename_stored_raw(self):
        result = self.run_fixture()
        names = {e["name"] for e in self.entries(result["run_id"])}
        self.assertIn("<img src=x onerror=alert(1)>.html", names)

    def test_duplicate_size_files_kept_separate(self):
        result = self.run_fixture()
        dups = [e for e in self.entries(result["run_id"])
                if e["name"] in ("dup_a.bin", "dup_b.bin")]
        self.assertEqual(len(dups), 2)

    def test_compound_extension(self):
        result = self.run_fixture()
        rows = [e for e in self.entries(result["run_id"])
                if e["name"] == "data.tar.gz"]
        self.assertEqual(rows[0]["compound_extension"], "tar.gz")
        self.assertEqual(rows[0]["extension"], "gz")

    def test_uppercase_extension_normalized_but_preserved(self):
        result = self.run_fixture()
        rows = [e for e in self.entries(result["run_id"])
                if e["name"] == "IMG_0001.JPG"]
        self.assertEqual(rows[0]["extension"], "jpg")
        self.assertEqual(rows[0]["extension_original"], "JPG")

    def test_source_tree_untouched(self):
        before = snapshot_tree(self.fixture)
        self.run_fixture()
        after = snapshot_tree(self.fixture)
        self.assertEqual(before, after)

    def test_large_sparse_file_logical_size(self):
        result = self.run_fixture()
        rows = [e for e in self.entries(result["run_id"])
                if e["name"] == "sparse_large.bin"]
        self.assertEqual(rows[0]["size_bytes"], 256 * 1024 * 1024)


class TestFailureBranches(ScanTestCase):
    def test_permission_denied_directory_does_not_abort_scan(self):
        target = os.path.join(self.fixture, "Documents", "noraise")
        os.makedirs(target)
        with open(os.path.join(target, "blocked.txt"), "w") as fh:
            fh.write("blocked")

        real_scandir = os.scandir

        def fake_scandir(path):
            if os.path.realpath(path) == os.path.realpath(target):
                raise PermissionError(13, "Permission denied", path)
            return real_scandir(path)

        with mock.patch("storage_audit.filesystem.os.scandir",
                        side_effect=fake_scandir):
            result = self.run_fixture()

        self.assertIn(result["status"],
                      (database.STATUS_COMPLETED_WITH_GAPS, database.STATUS_COMPLETED))
        conn = database.connect(self.db)
        try:
            issues = conn.execute(
                "SELECT * FROM scan_issues WHERE scan_id = ? AND operation = 'list'",
                (result["run_id"],)).fetchall()
        finally:
            conn.close()
        self.assertTrue(any("noraise" in row["path"] for row in issues))
        # Siblings must still be inventoried
        rels = {e["relative_path"] for e in self.entries(result["run_id"])}
        self.assertIn(os.path.join("Documents", "report.txt"), rels)

    def test_disappearing_file_records_issue_not_crash(self):
        gone = os.path.join(self.fixture, "Documents", "report.txt")

        class FakeEntry:
            def __init__(self, real):
                self._real = real
                self.name = real.name
                self.path = real.path

            def is_symlink(self):
                return False

            def is_dir(self, follow_symlinks=False):
                return False

            def is_file(self, follow_symlinks=False):
                return True

            def stat(self, follow_symlinks=False):
                raise FileNotFoundError(2, "No such file or directory", gone)

        real_scandir = os.scandir
        docs_dir = os.path.join(self.fixture, "Documents")

        def fake_scandir(path):
            it = real_scandir(path)
            if os.path.realpath(path) != os.path.realpath(docs_dir):
                return it
            real_entries = list(it)

            class Wrapper:
                def __iter__(self):
                    for entry in real_entries:
                        if entry.path == gone:
                            yield FakeEntry(entry)
                        else:
                            yield entry

                def __next__(self):
                    return next(iter(self))

                def close(self):
                    pass

            return iter(Wrapper())

        with mock.patch("storage_audit.filesystem.os.scandir",
                        side_effect=fake_scandir):
            result = self.run_fixture()

        self.assertIn(result["status"],
                      (database.STATUS_COMPLETED_WITH_GAPS,
                       database.STATUS_COMPLETED))
        entries = self.entries(result["run_id"])
        failed = [e for e in entries if e["relative_path"] == os.path.join(
            "Documents", "report.txt")]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["stat_status"], "failed")
        self.assertIsNone(failed[0]["size_bytes"])


class TestCancellationAndRecovery(ScanTestCase):
    def test_pre_set_cancel_event_marks_run_cancelled(self):
        event = make_cancel_event()
        event.set()
        result = self.run_fixture(cancel_event=event)
        self.assertEqual(result["status"], database.STATUS_CANCELLED)
        conn = database.connect(self.db)
        try:
            run = database.get_run(conn, result["run_id"])
        finally:
            conn.close()
        self.assertEqual(run["status"], database.STATUS_CANCELLED)
        self.assertEqual(run["coverage_incomplete"], 1)

    def test_cancelled_run_never_shows_complete(self):
        event = make_cancel_event()
        event.set()
        result = self.run_fixture(cancel_event=event)
        self.assertNotEqual(result["status"], database.STATUS_COMPLETED)
        self.assertNotEqual(result["status"], database.STATUS_COMPLETED_WITH_GAPS)


class TestOutputExclusion(ScanTestCase):
    def test_output_inside_root_is_excluded(self):
        out = os.path.join(self.fixture, "out")
        result = run_scan(self.fixture, db_path=self.db, output_dir=out,
                          progress=False)
        conn = database.connect(self.db)
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE scan_id = ?"
                " AND relative_path LIKE 'out%'", (result["run_id"],)).fetchone()[0]
            run = database.get_run(conn, result["run_id"])
        finally:
            conn.close()
        self.assertEqual(rows, 0)
        self.assertGreaterEqual(run["excluded_count"], 1)


class TestBatching(ScanTestCase):
    def test_small_batches_flush_correctly(self):
        # Small batches exercise the flush path without corruption.
        result = self.run_fixture(batch_size=50)
        entries = self.entries(result["run_id"])
        self.assertGreater(len(entries), 0)


if __name__ == "__main__":
    unittest.main()


class TestDatabaseInsideRoot(ScanTestCase):
    def test_db_inside_scan_root_is_excluded(self):
        db_inside = os.path.join(self.fixture, "audit.sqlite3")
        result = run_scan(self.fixture, db_path=db_inside, output_dir=self.out,
                          progress=False)
        conn = database.connect(db_inside)
        try:
            rows = conn.execute(
                "SELECT relative_path FROM entries WHERE scan_id = ?"
                " AND (relative_path = 'audit.sqlite3'"
                "      OR relative_path LIKE 'audit.sqlite3-%')",
                (result["run_id"],)).fetchall()
            run = database.get_run(conn, result["run_id"])
        finally:
            conn.close()
        self.assertEqual(rows, [])
        self.assertIn("audit.sqlite3", run["exclusions_json"])


class TestCoverageNotesWording(unittest.TestCase):
    """_coverage_notes must label mount-boundary issues precisely (V1.0.1)."""

    def _db_with_issues(self, issues):
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE scan_issues (
                id INTEGER PRIMARY KEY,
                scan_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                operation TEXT NOT NULL,
                error_category TEXT NOT NULL,
                error_code INTEGER,
                error_message TEXT NOT NULL,
                occurred_at_epoch INTEGER NOT NULL
            )""")
        for i, (operation, code) in enumerate(issues, start=1):
            conn.execute(
                "INSERT INTO scan_issues(scan_id, path, operation, error_category,"
                " error_code, error_message, occurred_at_epoch)"
                " VALUES (1, 'fixture/p%d', ?, 'mount_boundary', ?, 'msg', 0)" % i,
                (operation, code))
        return conn

    def test_mount_boundary_wording(self):
        from storage_audit.scanner import _coverage_notes
        conn = self._db_with_issues([("mount_boundary", None),
                                     ("mount_boundary", None)])
        notes = _coverage_notes(conn, 1, issue_count=2, skipped=2,
                                excluded=0, status="completed_with_gaps",
                                failure_note=None)
        self.assertIn("2 mount_boundary", notes)
        self.assertIn("mount boundary", notes)
        self.assertNotIn("containment", notes)
        conn.close()

    def test_root_escape_still_labelled_containment(self):
        from storage_audit.scanner import _coverage_notes
        conn = self._db_with_issues([("containment", None)])
        notes = _coverage_notes(conn, 1, issue_count=1, skipped=1,
                                excluded=0, status="completed_with_gaps",
                                failure_note=None)
        self.assertIn("1 containment", notes)
        conn.close()

    def test_no_issues_message(self):
        from storage_audit.scanner import _coverage_notes
        conn = self._db_with_issues([])
        notes = _coverage_notes(conn, 1, issue_count=0, skipped=0,
                                excluded=0, status="completed",
                                failure_note=None)
        self.assertEqual(notes, "No issues observed within the accessible tree.")
        conn.close()
