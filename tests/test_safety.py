"""Safety primitives: canonicalization, containment, exclusions."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import os
import tempfile
import unittest

from storage_audit.safety import (
    RootValidationError,
    canonicalize,
    check_output_location,
    is_within,
    safe_relpath,
    validate_scan_root,
)
from storage_audit.filesystem import build_exclusion_checker


class TestCanonicalize(unittest.TestCase):
    def test_absolute_and_stable(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(canonicalize(td), os.path.realpath(td))

    def test_dotdot_collapse(self):
        with tempfile.TemporaryDirectory() as td:
            sub = os.path.join(td, "a", "b")
            os.makedirs(sub)
            self.assertEqual(canonicalize(os.path.join(td, "a", "..", "a", "b")),
                             os.path.realpath(sub))


class TestValidateScanRoot(unittest.TestCase):
    def test_missing_root_rejected(self):
        with self.assertRaises(RootValidationError) as ctx:
            validate_scan_root("/definitely/not/here/xyz")
        self.assertIn("does not exist", str(ctx.exception))

    def test_file_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "file.txt")
            with open(path, "w") as fh:
                fh.write("x")
            with self.assertRaises(RootValidationError) as ctx:
                validate_scan_root(path)
            self.assertIn("not a directory", str(ctx.exception))

    def test_valid_root_accepted(self):
        with tempfile.TemporaryDirectory() as td:
            canonical, info = validate_scan_root(td)
            self.assertEqual(canonical, os.path.realpath(td))
            self.assertTrue(info["root_listed"])

    def test_empty_string_rejected(self):
        with self.assertRaises(RootValidationError):
            validate_scan_root("   ")


class TestContainment(unittest.TestCase):
    def test_component_boundary_respected(self):
        self.assertTrue(is_within("/a/b", "/a"))
        self.assertTrue(is_within("/a/b", "/a/b"))
        self.assertFalse(is_within("/a/bc", "/a/b"))
        self.assertFalse(is_within("/a", "/a/b"))

    def test_safe_relpath(self):
        self.assertEqual(safe_relpath("/a/b", "/a"), "b")
        self.assertEqual(safe_relpath("/a", "/a"), ".")
        self.assertIsNone(safe_relpath("/x", "/a"))


class TestOutputLocation(unittest.TestCase):
    def test_output_outside_root_ok(self):
        with tempfile.TemporaryDirectory() as td:
            root = os.path.join(td, "root")
            out = os.path.join(td, "out")
            os.makedirs(root)
            ok, message, exclusion = check_output_location(out, root)
            self.assertTrue(ok)
            self.assertIsNone(exclusion)

    def test_output_inside_root_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root = os.path.join(td, "root")
            out = os.path.join(root, "reports")
            os.makedirs(out)
            ok, message, exclusion = check_output_location(out, root)
            self.assertTrue(ok)
            self.assertEqual(os.path.normpath(exclusion), os.path.normpath("reports"))

    def test_output_equal_root_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            ok, message, _ = check_output_location(td, td)
            self.assertFalse(ok)

    def test_root_inside_output_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "wrap")
            root = os.path.join(out, "inner_root")
            os.makedirs(root)
            ok, message, _ = check_output_location(out, root)
            self.assertFalse(ok)

    def test_dotdot_in_output_collapses(self):
        with tempfile.TemporaryDirectory() as td:
            root = os.path.join(td, "root")
            os.makedirs(root)
            sneaky = os.path.join(root, "..", "other")
            ok, message, exclusion = check_output_location(sneaky, root)
            self.assertTrue(ok)  # resolves outside root — fine
            self.assertIsNone(exclusion)


class TestExclusionChecker(unittest.TestCase):
    def test_exact_subtree_only(self):
        check = build_exclusion_checker(["reports"])
        self.assertTrue(check("reports"))
        self.assertTrue(check(os.path.join("reports", "a.html")))
        self.assertFalse(check("reports2"))
        self.assertFalse(check(os.path.join("reports2", "a.html")))
        self.assertFalse(check("report"))

    def test_escaping_exclusion_refused(self):
        check = build_exclusion_checker(["../outside", "/abs"])
        self.assertFalse(check("../outside"))
        self.assertFalse(check("/abs"))

    def test_dot_exclusion_refused(self):
        check = build_exclusion_checker(["."])
        self.assertFalse(check("."))
        self.assertFalse(check("anything"))


if __name__ == "__main__":
    unittest.main()
