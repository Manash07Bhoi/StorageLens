"""CLI end-to-end tests via subprocess (real interpreter, real exit codes)."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import build_rich_fixture

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENTRY = os.path.join(REPO, "storage_audit.py")


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="audit_cli_test_")
        self.fixture = os.path.join(self.tmp, "phone")
        build_rich_fixture(self.fixture)
        self.db = os.path.join(self.tmp, "test.sqlite3")
        self.out = os.path.join(self.tmp, "out")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_cli(self, *args, env=None, timeout=120):
        cmd = [sys.executable, ENTRY, "--db", self.db, "--output-dir", self.out]
        cmd += list(args)
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=timeout, env=full_env)


class TestHelpAndVersion(CliCase):
    def test_help(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("check", result.stdout)
        self.assertIn("scan", result.stdout)
        self.assertIn("report", result.stdout)
        self.assertIn("list-runs", result.stdout)

    def test_version(self):
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("2.2.0", result.stdout)

    def test_no_command_prints_help(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0)
        self.assertIn("usage", result.stdout.lower())


class TestCheck(CliCase):
    def test_check_missing_root_exits_2(self):
        result = self.run_cli("check", "--root", os.path.join(self.tmp, "nope"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("NOT ready", result.stdout)

    def test_check_valid_fixture_exits_0(self):
        result = self.run_cli("check", "--root", self.fixture)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("termux-setup-storage" if "NOT a Termux" in result.stdout
                      else "ready", result.stdout)


class TestScanReportFlow(CliCase):
    def test_scan_then_report_then_list(self):
        result = self.run_cli("scan", "--root", self.fixture,
                              "--batch-size", "50")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Scan run #1", result.stdout)
        self.assertIn("READ-ONLY", result.stdout)

        result = self.run_cli("list-runs")
        self.assertEqual(result.returncode, 0)
        self.assertIn("#1" if "#1" in result.stdout else "1", result.stdout)

        result = self.run_cli("report", "--latest")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Report built", result.stdout)
        index = None
        for dirpath, _dirs, files in os.walk(self.out):
            if "index.html" in files:
                index = os.path.join(dirpath, "index.html")
        self.assertIsNotNone(index)

        result = self.run_cli("show-run", "1")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Status:", result.stdout)

    def test_scan_refuses_filesystem_root(self):
        result = self.run_cli("scan", "--root", "/")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--i-know-this-is-broad", result.stderr)

    def test_report_missing_scan_id_errors_without_fallback(self):
        result = self.run_cli("scan", "--root", self.fixture)
        self.assertEqual(result.returncode, 0)
        result = self.run_cli("report", "--scan-id", "999")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not found", result.stderr.lower())

    def test_report_latest_with_no_runs_errors(self):
        result = self.run_cli("report", "--latest")
        self.assertEqual(result.returncode, 2)


class TestEnvironmentRootOverride(CliCase):
    def test_env_var_root_used_when_no_flag(self):
        result = self.run_cli("scan", env={"STORAGE_AUDIT_ROOT": self.fixture})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(self.fixture, result.stdout)


if __name__ == "__main__":
    unittest.main()


class TestCliScopeRegistration(CliCase):
    """End-to-end CLI flow for org-scope-2 custom-folder registration."""

    def _xdg(self):
        return os.path.join(self.tmp, "xdg")

    def test_custom_folder_registration_flow(self):
        custom = os.path.join(self.tmp, "My Study Files")
        os.makedirs(custom)
        with open(os.path.join(custom, "chapter1.txt"), "w") as fh:
            fh.write("hello")
        env = {"XDG_DATA_HOME": self._xdg()}

        # scan once (provenance only)
        result = self.run_cli("scan", "--root", self.fixture,
                              "--batch-size", "50", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        # unregistered custom folder: plan refused (exit 2)
        result = self.run_cli("organize-plan", "--scope", custom, env=env)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("not a recognized personal folder", result.stderr)
        self.assertIn("organize-register-scope", result.stderr)

        # registration requires explicit confirmation (no --yes, no tty)
        result = self.run_cli("organize-register-scope", "--scope", custom,
                              env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--yes", result.stderr)

        # explicit confirmation registers it
        result = self.run_cli("organize-register-scope", "--scope", custom,
                              "--note", "my own folder", "--yes", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("registered", result.stdout)

        # now visible in the registry listing
        result = self.run_cli("organize-scopes", env=env)
        self.assertEqual(result.returncode, 0)
        self.assertIn(os.path.realpath(custom), result.stdout)

        # and a plan can be built
        result = self.run_cli("organize-plan", "--scope", custom, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        # unregistering revokes it
        result = self.run_cli("organize-unregister-scope", "--scope", custom,
                              env=env)
        self.assertEqual(result.returncode, 0)
        result = self.run_cli("organize-plan", "--scope", custom, env=env)
        self.assertEqual(result.returncode, 2)

    def test_registration_of_prohibited_folder_refused(self):
        android = os.path.join(self.fixture, "Android", "data")
        os.makedirs(android, exist_ok=True)
        env = {"XDG_DATA_HOME": self._xdg()}
        result = self.run_cli("organize-register-scope", "--scope", android,
                              "--yes", env=env)
        self.assertEqual(result.returncode, 2)
        self.assertIn("protected_android", result.stderr)

    def test_recognized_folder_needs_no_registration(self):
        documents = os.path.join(self.fixture, "Documents")
        os.makedirs(documents, exist_ok=True)
        with open(os.path.join(documents, "note.txt"), "w") as fh:
            fh.write("keep")
        env = {"XDG_DATA_HOME": self._xdg()}
        result = self.run_cli("scan", "--root", self.fixture,
                              "--batch-size", "50", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.run_cli("organize-plan", "--scope", documents, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
