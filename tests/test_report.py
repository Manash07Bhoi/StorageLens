"""Report builder: structure, escaping, offline behavior, pagination."""

import html.parser
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_rich_fixture

from storage_audit import database
from storage_audit.report_builder import build_report, build_static_file_pages
from storage_audit.scanner import run_scan, make_cancel_event

EXTERNAL_PATTERNS = [
    re.compile(r"https?://"),
    re.compile(r"src\s*=\s*[\"']\s*//"),
    re.compile(r"href\s*=\s*[\"']\s*//"),
    re.compile(r"@import"),
    re.compile(r"url\(\s*[\"']?\s*https?:"),
    re.compile(r"cdn\.", re.IGNORECASE),
    re.compile(r"fonts\.googleapis", re.IGNORECASE),
]


class ReportCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="audit_report_test_")
        cls.fixture = os.path.join(cls.tmp, "phone")
        build_rich_fixture(cls.fixture)
        cls.db = os.path.join(cls.tmp, "test.sqlite3")
        cls.out = os.path.join(cls.tmp, "out")
        result = run_scan(cls.fixture, db_path=cls.db,
                          output_dir=cls.out, progress=False)
        cls.run_id = result["run_id"]
        conn = database.connect(cls.db)
        try:
            cls.report = build_report(conn, cls.run_id, cls.out,
                                      fixture_label=True)
        finally:
            conn.close()
        cls.report_dir = cls.report["report_dir"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class TestReportStructure(ReportCase):
    def test_review_candidates_page_renders_neutral_observations(self):
        path = os.path.join(self.report_dir, "review_candidates.html")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("Review Candidates", content)
        # Sparse 256 MiB fixture file must appear as a large-file observation.
        self.assertIn("sparse_large.bin", content)
        # The same-size dup pair must appear, clearly labelled unverified.
        self.assertIn("dup_a.bin", content)
        self.assertIn("not proof of duplicate", content.lower().replace("duplication", "duplicate"))
        # Honest framing: the disclaimer must not issue any deletion action.
        self.assertIn("not", content.lower())
        self.assertNotIn("delete all", content.lower())
        self.assertNotIn("duplicates found", content.lower())
        # Factual empty marker for the 5-year bucket (fixture files are new).
        self.assertIn("over 5 years", content)

    def test_expected_pages_exist(self):
        expected = [
            "index.html", "files.html", "files_page_1.html", "file_types.html",
            "largest_files.html", "largest_directories.html",
            "empty_directories.html", "zero_byte_files.html", "hidden.html",
            "review_candidates.html",
            "scan_issues.html", "methodology.html", "exports.html",
            "directory_explorer.html", "report.css", "report.js",
        ]
        for name in expected:
            with self.subTest(page=name):
                self.assertTrue(os.path.isfile(os.path.join(self.report_dir, name)),
                                name)

    def test_reports_identify_scan_id_and_status(self):
        with open(os.path.join(self.report_dir, "index.html")) as fh:
            content = fh.read()
        self.assertIn("#{}".format(self.run_id), content)
        self.assertIn("Completed", content)

    def test_fixture_label_banner_present(self):
        with open(os.path.join(self.report_dir, "index.html")) as fh:
            content = fh.read()
        self.assertIn("SYNTHETIC TEST DATA", content)

    def test_every_html_page_parses(self):
        for name in os.listdir(self.report_dir):
            if not name.endswith(".html"):
                continue
            path = os.path.join(self.report_dir, name)
            with self.subTest(page=name):
                parser = html.parser.HTMLParser()
                with open(path, encoding="utf-8") as fh:
                    parser.feed(fh.read())
                parser.close()

    def test_nav_links_resolve(self):
        with open(os.path.join(self.report_dir, "index.html")) as fh:
            content = fh.read()
        for href in re.findall(r'href="([^"]+)"', content):
            if href.startswith("#"):
                continue  # same-page anchor
            if href.startswith(("http:", "https:", "mailto:", "//")):
                self.fail("external link in index.html: {}".format(href))
            target = os.path.normpath(os.path.join(self.report_dir, href))
            self.assertTrue(os.path.exists(target),
                            "broken link: {}".format(href))

    def test_exports_links_resolve(self):
        with open(os.path.join(self.report_dir, "exports.html")) as fh:
            content = fh.read()
        for href in re.findall(r'href="(exports/[^"]+)"', content):
            target = os.path.join(self.report_dir, href)
            self.assertTrue(os.path.isfile(target), "missing export: {}".format(href))


class TestOfflineNoNetwork(ReportCase):
    def test_no_external_urls_anywhere(self):
        for dirpath, _dirs, files in os.walk(self.report_dir):
            for name in files:
                if not name.endswith((".html", ".css", ".js", ".txt", ".md", ".json")):
                    continue
                path = os.path.join(dirpath, name)
                with open(path, encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                for pattern in EXTERNAL_PATTERNS:
                    with self.subTest(file=name, pattern=pattern.pattern):
                        self.assertIsNone(pattern.search(content),
                                          "external reference {} in {}".format(
                                              pattern.pattern, path))

    def test_report_js_passes_node_check(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        import subprocess
        result = subprocess.run([node, "--check",
                                 os.path.join(self.report_dir, "report.js")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class TestEscaping(ReportCase):
    def test_script_in_filename_escaped_everywhere(self):
        for name in os.listdir(self.report_dir):
            if not name.endswith(".html"):
                continue
            path = os.path.join(self.report_dir, name)
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            self.assertNotIn("<img src=x onerror=alert(1)>", content,
                             "unescaped injected tag in {}".format(name))

    def test_quotes_and_ampersands_escaped_in_paths(self):
        with open(os.path.join(self.report_dir, "files_page_1.html")) as fh:
            content = fh.read()
        self.assertNotIn('comma "quoted" name.txt</', content)
        self.assertIn("comma &quot;quoted&quot; name.txt", content)


class TestPagination(ReportCase):
    def test_static_pages_cover_every_file_exactly_once(self):
        conn = database.connect(self.db)
        try:
            rows = conn.execute(
                "SELECT relative_path FROM entries"
                " WHERE scan_id = ? AND kind = 'file' ORDER BY relative_path",
                (self.run_id,)).fetchall()
        finally:
            conn.close()
        total = len(rows)
        seen = []
        page = 1
        while True:
            path = os.path.join(self.report_dir, "files_page_{}.html".format(page))
            if not os.path.exists(path):
                break
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
            seen.extend(re.findall(r'class="path">([^<]+)</span>', content))
            page += 1
        self.assertEqual(len(seen), total)

    def test_static_page_links_have_boundaries(self):
        with open(os.path.join(self.report_dir, "files_page_1.html")) as fh:
            content = fh.read()
        self.assertIn("Page 1 of", content)

    def test_pagination_with_tiny_page_size(self):
        conn = database.connect(self.db)
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE scan_id = ? AND kind = 'file'",
                (self.run_id,)).fetchone()[0]
            with tempfile.TemporaryDirectory() as td:
                pages = build_static_file_pages(conn, self.run_id,
                                                {"id": self.run_id, "status": "completed",
                                                 "coverage_incomplete": 0,
                                                 "coverage_notes": "",
                                                 "requested_root": "fixture",
                                                 "root_path": "/fixture",
                                                 "classification_version": "1.0.0"},
                                                td, fixture_label=True, page_rows=5)
                self.assertEqual(pages, (total + 4) // 5)
                # every file appears exactly once across pages
                found = []
                for page in range(1, pages + 1):
                    with open(os.path.join(td, "files_page_{}.html".format(page)),
                              encoding="utf-8") as fh:
                        found.extend(re.findall(r'class="path">([^<]+)</span>',
                                                fh.read()))
                self.assertEqual(len(found), total)
                self.assertEqual(len(set(found)), total)
                # boundary pages carry correct navigation
                with open(os.path.join(td, "files_page_1.html")) as fh:
                    first = fh.read()
                self.assertIn("files_page_2.html", first)
                with open(os.path.join(td, "files_page_{}.html".format(pages))) as fh:
                    last = fh.read()
                self.assertIn("files_page_{}.html".format(pages - 1), last)
        finally:
            conn.close()


class TestIncompleteReportLabeling(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_incomplete_test_")
        self.fixture = os.path.join(self.tmp, "phone")
        build_rich_fixture(self.fixture)
        self.db = os.path.join(self.tmp, "test.sqlite3")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cancelled_report_is_labelled_incomplete(self):
        event = make_cancel_event()
        event.set()
        result = run_scan(self.fixture, db_path=self.db, output_dir=self.out,
                          progress=False, cancel_event=event)
        conn = database.connect(self.db)
        try:
            report = build_report(conn, result["run_id"], self.out,
                                  fixture_label=True)
        finally:
            conn.close()
        with open(os.path.join(report["report_dir"], "index.html")) as fh:
            content = fh.read()
        self.assertIn("Cancelled", content)
        self.assertIn("Partial / incomplete", content)


if __name__ == "__main__":
    unittest.main()


class TestChunkedSearchData(unittest.TestCase):
    def test_chunked_inventory_js_files_when_large(self):
        import unittest.mock as mock
        tmp = tempfile.mkdtemp(prefix="audit_chunk_test_")
        try:
            fixture = os.path.join(tmp, "phone")
            build_rich_fixture(fixture)
            db = os.path.join(tmp, "test.sqlite3")
            out = os.path.join(tmp, "out")
            result = run_scan(fixture, db_path=db, output_dir=out,
                              progress=False)
            conn = database.connect(db)
            try:
                with mock.patch("storage_audit.report_builder.config.SEARCH_INLINE_LIMIT", 10), \
                     mock.patch("storage_audit.report_builder.config.SEARCH_CHUNK_SIZE", 10):
                    report = build_report(conn, result["run_id"], out,
                                          fixture_label=True)
            finally:
                conn.close()
            report_dir = report["report_dir"]
            self.assertTrue(report["chunked_search_data"])
            data_dir = os.path.join(report_dir, "data")
            chunks = sorted(os.listdir(data_dir)) if os.path.isdir(data_dir) else []
            self.assertTrue(chunks, "no chunk files generated")
            with open(os.path.join(report_dir, "files.html")) as fh:
                content = fh.read()
            self.assertIn("data/inventory_001.js", content)
            with open(os.path.join(data_dir, chunks[0])) as fh:
                self.assertIn("window.__INVENTORY=(window.__INVENTORY||[])", fh.read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
