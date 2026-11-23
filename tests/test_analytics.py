"""Analytics: recursive totals, grand total, empty detection."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from storage_audit import analytics, database
from storage_audit.scanner import run_scan


class AnalyticsTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_analytics_test_")
        self.root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(self.root, "a", "b"))
        os.makedirs(os.path.join(self.root, "empty"))

        def write(rel, size, fill=b"x"):
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(fill * size)

        write("top.txt", 10)
        write("a/mid.txt", 20)
        write("a/b/deep.txt", 40)
        write("a/b/zero.txt", 0)
        write("a/dup30_a.bin", 30, fill=b"A")
        write("a/dup30_b.bin", 30, fill=b"B")

        self.db = os.path.join(self.tmp, "test.sqlite3")
        self.out = os.path.join(self.tmp, "out")
        self.result = run_scan(self.root, db_path=self.db, output_dir=self.out,
                               progress=False)
        self.run_id = self.result["run_id"]

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conn(self):
        conn = database.connect(self.db)
        database.migrate(conn)
        return conn


class TestRecursiveTotals(AnalyticsTestCase):
    def test_directory_rollups_bottom_up(self):
        conn = self.conn()
        try:
            stats = {row["relative_path"]: dict(row) for row in conn.execute(
                "SELECT * FROM directory_stats WHERE scan_id = ?",
                (self.run_id,))}
        finally:
            conn.close()

        sep = os.sep
        deep = stats[os.path.join("a", "b")]
        self.assertEqual(deep["direct_files"], 2)
        self.assertEqual(deep["recursive_files"], 2)
        self.assertEqual(deep["recursive_file_bytes"], 40)

        mid = stats["a"]
        self.assertEqual(mid["direct_files"], 3)
        self.assertEqual(mid["recursive_files"], 5)
        self.assertEqual(mid["recursive_file_bytes"], 120)

        top = stats["."]
        self.assertEqual(top["direct_files"], 1)
        self.assertEqual(top["recursive_files"], 6)
        self.assertEqual(top["recursive_file_bytes"], 130)
        self.assertEqual(top["recursive_dirs"], 3)  # a, a/b, empty

    def test_grand_total_from_files_only(self):
        conn = self.conn()
        try:
            overview = analytics.run_overview(conn, self.run_id)
        finally:
            conn.close()
        self.assertEqual(overview["inventoried_file_bytes"], 130)
        self.assertEqual(overview["files_inventoried"], 6)
        self.assertEqual(overview["zero_byte_files"], 1)

    def test_empty_directory_detection(self):
        conn = self.conn()
        try:
            empties = set(analytics.empty_directories(conn, self.run_id))
        finally:
            conn.close()
        self.assertIn("empty", empties)
        self.assertNotIn("a", empties)

    def test_grand_total_not_double_counted(self):
        """Sum of directory recursive bytes must exceed, not equal, the grand total."""
        conn = self.conn()
        try:
            stats = list(conn.execute(
                "SELECT recursive_file_bytes FROM directory_stats WHERE scan_id = ?",
                (self.run_id,)))
            overview = analytics.run_overview(conn, self.run_id)
        finally:
            conn.close()
        self.assertGreater(sum(s["recursive_file_bytes"] for s in stats),
                           overview["inventoried_file_bytes"])

    def test_synthesis_on_empty_tree(self):
        empty_root = os.path.join(self.tmp, "only_dirs")
        os.makedirs(empty_root)
        result = run_scan(empty_root, db_path=os.path.join(self.tmp, "e.sqlite3"),
                          output_dir=os.path.join(self.tmp, "eout"),
                          progress=False)
        conn = database.connect(result["db_path"])
        try:
            database.migrate(conn)
            overview = analytics.run_overview(conn, result["run_id"])
        finally:
            conn.close()
        self.assertEqual(overview["files_inventoried"], 0)
        self.assertEqual(overview["inventoried_file_bytes"], 0)
        self.assertEqual(overview["directories"], 1)  # the root itself

    def test_same_size_candidates(self):
        conn = self.conn()
        try:
            groups = analytics.same_size_candidates(conn, self.run_id)
        finally:
            conn.close()
        sizes = {g["size_bytes"] for g in groups}
        self.assertIn(30, sizes)
        self.assertNotIn(0, sizes)
        group30 = next(g for g in groups if g["size_bytes"] == 30)
        self.assertEqual(group30["count"], 2)


if __name__ == "__main__":
    unittest.main()
