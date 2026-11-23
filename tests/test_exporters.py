"""Exporters: escaping, formula injection, reconciliation, tree chunking."""

import csv
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_rich_fixture

from storage_audit import analytics, database, exporters
from storage_audit.exporters import (
    csv_safe_cell,
    export_entries_jsonl,
    export_files_csv,
    generate_exports,
    write_tree,
)
from storage_audit.report_builder import build_report
from storage_audit.scanner import run_scan


class ExporterCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_export_test_")
        self.fixture = os.path.join(self.tmp, "phone")
        build_rich_fixture(self.fixture)
        self.db = os.path.join(self.tmp, "test.sqlite3")
        self.out = os.path.join(self.tmp, "out")
        self.result = run_scan(self.fixture, db_path=self.db,
                               output_dir=self.out, progress=False)
        self.run_id = self.result["run_id"]
        self.exports_dir = os.path.join(self.tmp, "exports")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def conn(self):
        conn = database.connect(self.db)
        database.migrate(conn)
        return conn


class TestCSVInjection(ExporterCase):
    def test_formula_prefixes_neutralized(self):
        for raw, expected in [
            ("=1+1", "'=1+1"),
            ("+cmd", "'+cmd"),
            ("-10+20", "'-10+20"),
            ("@SUM(A1)", "'@SUM(A1)"),
            ("\t=1", "'\t=1"),
            ("\r=1", "'\r=1"),
            ("normal", "normal"),
            ("", ""),
        ]:
            self.assertEqual(csv_safe_cell(raw), expected)

    def test_numeric_passthrough(self):
        self.assertEqual(csv_safe_cell(42), 42)
        self.assertEqual(csv_safe_cell(None), "")

    def test_hostile_names_roundtrip_safely(self):
        conn = self.conn()
        try:
            content = export_files_csv(conn, self.run_id)
        finally:
            conn.close()
        rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
        for row in rows[1:]:
            self.assertNotRegex(row[2], r"^[=+\-@\t\r]")


class TestCSVShape(ExporterCase):
    def test_files_csv_parseable_and_complete(self):
        conn = self.conn()
        try:
            content = export_files_csv(conn, self.run_id)
            db_count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind = 'file'",
                (self.run_id,)).fetchone()[0]
        finally:
            conn.close()
        rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
        self.assertEqual(rows[0][0:3], ["relative_path", "absolute_path", "name"])
        self.assertEqual(len(rows) - 1, db_count)

    def test_utf8_bom_present_for_spreadsheets(self):
        conn = self.conn()
        try:
            generate_exports(conn, self.run_id, self.exports_dir)
        finally:
            conn.close()
        with open(os.path.join(self.exports_dir, "files.csv"), "rb") as fh:
            self.assertEqual(fh.read(3), b"\xef\xbb\xbf")

    def test_comma_quote_newline_names_roundtrip(self):
        conn = self.conn()
        try:
            content = export_files_csv(conn, self.run_id)
        finally:
            conn.close()
        rows = list(csv.reader(io.StringIO(content.lstrip("﻿"))))
        names = {row[2] for row in rows[1:]}
        self.assertTrue(any("comma" in n for n in names))
        self.assertTrue(any("\n" in n for n in names))
        self.assertTrue(any('"' in n for n in names))


class TestJSONL(ExporterCase):
    def test_every_line_parses_and_counts_match(self):
        conn = self.conn()
        try:
            content = export_entries_jsonl(conn, self.run_id)
            db_count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE scan_id = ?",
                (self.run_id,)).fetchone()[0]
        finally:
            conn.close()
        lines = [l for l in content.splitlines() if l.strip()]
        self.assertEqual(len(lines), db_count)
        for line in lines:
            obj = json.loads(line)
            self.assertIn("relative_path", obj)
            self.assertIn("kind", obj)
            self.assertIn("classification_version", obj)

    def test_raw_values_not_csv_escaped(self):
        conn = self.conn()
        try:
            content = export_entries_jsonl(conn, self.run_id)
        finally:
            conn.close()
        raw = json.loads(next(l for l in content.splitlines()
                               if "<img" in l))
        self.assertIn("<img src=x onerror=alert(1)>", raw["name"])

    def test_manifest_reconciles(self):
        conn = self.conn()
        try:
            files = generate_exports(conn, self.run_id, self.exports_dir)
        finally:
            conn.close()
        with open(os.path.join(self.exports_dir, "manifest.json")) as fh:
            manifest = json.load(fh)
        conn = self.conn()
        try:
            db_count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind='file'"
                " AND stat_status='ok'", (self.run_id,)).fetchone()[0]
        finally:
            conn.close()
        counters = manifest["counters"]
        self.assertEqual(counters["files_inventoried"], db_count)
        # manifest exports must cover every generated file
        for name, info in files.items():
            if name == "manifest.json":
                continue  # manifest cannot contain its own hash
            self.assertIn(name, manifest["exports"])
            self.assertEqual(info["bytes"], os.path.getsize(
                os.path.join(self.exports_dir, name)))
        with open(os.path.join(self.exports_dir, "directory_tree.txt")) as fh:
            tree = fh.read()
        self.assertIn("./  (scan root)", tree)
        self.assertIn("emoji 🎉 photo.jpg", tree)


class TestTree(ExporterCase):
    def test_tree_contains_hidden_and_empty(self):
        conn = self.conn()
        try:
            lines = list(exporters.build_tree_lines(conn, self.run_id))
        finally:
            conn.close()
        text = "\n".join(lines)
        self.assertIn(".hidden_file", text)
        self.assertIn("EmptyDir", text)
        self.assertIn("nested_empty", text)

    def test_tree_chunking_splits_and_indexes(self):
        lines = ["line {:04d} {}".format(i, "x" * 40) for i in range(500)]
        with tempfile.TemporaryDirectory() as td:
            files = write_tree(lines, td, max_bytes=2048, max_lines=100)
            self.assertIn("directory_tree_index.txt", files)
            parts = [f for f in files if f.startswith("directory_tree_part_")]
            self.assertGreater(len(parts), 1)
            with open(os.path.join(td, "directory_tree_index.txt")) as fh:
                index = fh.read()
            self.assertIn("Total chunks: {}".format(len(parts)), index)
            self.assertIn("Total lines: 500", index)
            total = 0
            for part in parts:
                with open(os.path.join(td, part)) as fh:
                    total += sum(1 for _ in fh)
            self.assertEqual(total, 500)

    def test_control_characters_escaped_in_tree(self):
        conn = self.conn()
        try:
            lines = list(exporters.build_tree_lines(conn, self.run_id))
        finally:
            conn.close()
        text = "\n".join(lines)
        self.assertNotIn("\tname.txt", text)  # literal tab must be escaped
        self.assertIn("\\tname.txt", text)
        self.assertNotIn("new\nline", text)
        self.assertIn("new\\nline", text)


class TestReconciliation(ExporterCase):
    def test_exports_all_same_scan_and_totals_agree(self):
        conn = self.conn()
        try:
            generate_exports(conn, self.run_id, self.exports_dir)
            db_files = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes),0) FROM entries"
                " WHERE scan_id = ? AND kind='file' AND size_status='observed'",
                (self.run_id,)).fetchone()
        finally:
            conn.close()

        with open(os.path.join(self.exports_dir, "entries.jsonl")) as fh:
            jsonl_files = [json.loads(l) for l in fh if l.strip()]
        jsonl_file_count = sum(1 for e in jsonl_files if e["kind"] == "file")
        jsonl_bytes = sum(e["size_bytes"] or 0 for e in jsonl_files
                          if e["kind"] == "file")

        with open(os.path.join(self.exports_dir, "files.csv"),
                  encoding="utf-8-sig") as fh:
            csv_files = list(csv.DictReader(fh))

        with open(os.path.join(self.exports_dir, "manifest.json")) as fh:
            manifest = json.load(fh)

        self.assertEqual(jsonl_file_count, db_files[0])
        self.assertEqual(jsonl_bytes, db_files[1])
        self.assertEqual(len(csv_files), db_files[0])
        self.assertEqual(sum(int(r["size_bytes"]) for r in csv_files
                             if r["size_status"] == "observed"), db_files[1])
        self.assertEqual(manifest["counters"]["files_inventoried"], db_files[0])
        self.assertEqual(manifest["counters"]["inventoried_file_bytes"],
                         db_files[1])
        scan_ids = {e["scan_id"] for e in jsonl_files}
        self.assertEqual(scan_ids, {self.run_id})

    def test_report_regeneration_keeps_run_and_totals(self):
        conn = self.conn()
        try:
            first = build_report(conn, self.run_id, self.out,
                                 fixture_label=True)
            second = build_report(conn, self.run_id, self.out,
                                  fixture_label=True)
        finally:
            conn.close()
        self.assertEqual(first["report_dir"], second["report_dir"])
        self.assertEqual(first["inventory_records"], second["inventory_records"])


if __name__ == "__main__":
    unittest.main()
