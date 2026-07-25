#!/usr/bin/env python3
"""Regression tests for the prisma-sase plugin -- stdlib unittest, no network.

Run:  python3 tools/test-regressions.py          (needs Python >= 3.10)

Every test here pins a bug that was real and shipped. Each one names the
symptom a user would have seen, so a future change that reintroduces it fails
with an explanation rather than a bare assertion.

Scope: pure logic + the shell scripts' file handling. No live API calls (the
tool layer runs under PRISMA_MOCK=1), no credentials required.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MCP = os.path.join(ROOT, "plugin", "mcp")
UNINSTALL_SH = os.path.join(ROOT, "plugin", "uninstall.sh")

sys.path.insert(0, MCP)
os.environ["PRISMA_MOCK"] = "1"

import config                                     # noqa: E402
from tools.networks import _state_of              # noqa: E402


class TunnelStateVocabulary(unittest.TestCase):
    """0.8.5: `"up" in state` classified Disrupted/Setup/backup as UP.

    Symptom: get_sase_status said "Healthy: all tunnels up" while a tunnel was
    disrupted -- defeating the 0.8.4 headline-honesty work.
    """

    def test_up_and_down_are_recognized(self):
        for name in ("Up", "up", "ACTIVE", "established", "connected"):
            self.assertEqual(_state_of({"tunnel_state_name": name}), "up", name)
        for name in ("Down", "down", "INACTIVE", "failed", "disconnected"):
            self.assertEqual(_state_of({"tunnel_state_name": name}), "down", name)

    def test_names_containing_up_or_down_are_not_up_or_down(self):
        # The exact strings that used to be misclassified.
        for name in ("Disrupted", "Setup", "backup", "SUPERVISING",
                     "unknown-up-state", "Shutdown-pending"):
            got = _state_of({"tunnel_state_name": name})
            self.assertEqual(got, name.lower(),
                             "%r must fall through to other_states, got %r"
                             % (name, got))

    def test_numeric_state_field(self):
        self.assertEqual(_state_of({"tunnel_state": 1}), "up")
        self.assertEqual(_state_of({"tunnel_state": 0}), "down")
        self.assertEqual(_state_of({"tunnel_state": 2}), "2")

    def test_missing_state_is_unknown(self):
        self.assertEqual(_state_of({}), "unknown")
        self.assertEqual(_state_of({"tunnel_state_name": ""}), "unknown")


class HeadlineHonesty(unittest.TestCase):
    """A not-up tunnel must never yield a "Healthy" headline."""

    def test_disrupted_tunnel_reaches_the_headline(self):
        import mock_data
        from tools.networks import get_remote_networks
        from tools.status import _headline, _tunnels

        original = mock_data._TUNNEL_ROWS
        mock_data._TUNNEL_ROWS = [
            dict(original[0]),
            dict(original[1], tunnel_state_name="Disrupted",
                 tunnel_name="RN-BROKEN"),
        ]
        try:
            rows = get_remote_networks(hours=1)
            self.assertEqual(rows["tunnels_up"], 1)
            self.assertEqual(rows.get("other_states"), {"disrupted": 1})
            self.assertIn("RN-BROKEN", rows.get("not_up_names") or [])

            headline, _ = _headline({
                "alerts": {"total": 0, "by_severity": {}},
                "connectivity": _tunnels(None, None),
                "connected_users": {"total_connected": 5},
                "experience": {"overall_score": 95},
            })
            self.assertNotIn("Healthy", headline)
            self.assertIn("disrupted", headline)
        finally:
            mock_data._TUNNEL_ROWS = original


class ClampLimit(unittest.TestCase):
    """0.8.5: clamp_limit(0) returned DEFAULT_LIMIT (20) instead of 1.

    Symptom: asking for limit=0 ("counts only, no rows") silently returned 20
    rows.
    """

    def test_out_of_range_numbers_are_clamped(self):
        self.assertEqual(config.clamp_limit(0), 1)
        self.assertEqual(config.clamp_limit(-5), 1)
        self.assertEqual(config.clamp_limit(10 ** 6), config.MAX_LIMIT)

    def test_unparseable_falls_back_to_default(self):
        for junk in (None, "abc", object()):
            self.assertEqual(config.clamp_limit(junk), config.DEFAULT_LIMIT)

    def test_in_range_passes_through(self):
        self.assertEqual(config.clamp_limit(7), 7)
        self.assertEqual(config.clamp_limit("7"), 7)


class EnvFileLoading(unittest.TestCase):
    """0.8.5: a missing $PRISMA_ENV_FILE fell back to ~/.prisma-sase.env in
    silence -- worst in cloud sessions, where that variable is the only
    credential path and a typo'd path looked like a working setup."""

    def _load(self, home, env_file=None):
        """Re-import config with a controlled HOME/PRISMA_ENV_FILE."""
        env = dict(os.environ)
        env["HOME"] = home
        env.pop("PRISMA_ENV_FILE", None)
        if env_file:
            env["PRISMA_ENV_FILE"] = env_file
        for key in list(env):
            if key.startswith("PRISMA_") and key != "PRISMA_ENV_FILE":
                del env[key]
        code = ("import sys, json; sys.path.insert(0, %r); import config; "
                "d = config.env_diagnostics(); "
                "print(json.dumps({'used': d['env_file'], "
                "'missing': d['env_file_missing'], "
                "'client_id': config.CLIENT_ID}))" % MCP)
        out = subprocess.run([sys.executable, "-c", code], env=env,
                             stdout=subprocess.PIPE, check=True)
        import json
        return json.loads(out.stdout.decode())

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        with open(os.path.join(self.home, ".prisma-sase.env"), "w") as fh:
            fh.write("PRISMA_CLIENT_ID=from-home\n")
        self.staged = os.path.join(self.tmp, "staged.env")
        with open(self.staged, "w") as fh:
            fh.write("PRISMA_CLIENT_ID=from-staged\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_explicit_file_is_reported(self):
        result = self._load(self.home, os.path.join(self.tmp, "typo.env"))
        self.assertTrue(result["missing"],
                        "a missing PRISMA_ENV_FILE must be recorded, not "
                        "silently ignored")
        self.assertTrue(result["missing"].endswith("typo.env"))

    def test_valid_explicit_file_wins_and_warns_about_nothing(self):
        result = self._load(self.home, self.staged)
        self.assertIsNone(result["missing"])
        self.assertEqual(result["used"], self.staged)
        self.assertEqual(result["client_id"], "from-staged")

    def test_home_file_used_when_no_explicit_path(self):
        result = self._load(self.home)
        self.assertIsNone(result["missing"])
        self.assertEqual(result["client_id"], "from-home")


class CredentialFileAudit(unittest.TestCase):
    """0.8.4 feature -- pinned so it keeps catching loose/stray files."""

    def test_loose_permissions_and_stray_files_are_flagged(self):
        tmp = tempfile.mkdtemp()
        try:
            canonical = os.path.join(tmp, ".prisma-sase.env")
            stray = os.path.join(tmp, ".prisma-sase2.env")
            for path in (canonical, stray):
                with open(path, "w") as fh:
                    fh.write("PRISMA_CLIENT_SECRET=x\n")
            os.chmod(canonical, 0o644)          # world-readable
            os.chmod(stray, 0o600)

            code = ("import sys, json, os; sys.path.insert(0, %r); "
                    "import config; "
                    "print(json.dumps(config.credential_file_audit()))" % MCP)
            env = dict(os.environ, HOME=tmp)
            env.pop("PRISMA_ENV_FILE", None)
            out = subprocess.run([sys.executable, "-c", code], env=env,
                                 stdout=subprocess.PIPE, check=True)
            import json
            findings = json.loads(out.stdout.decode())
            issues = {(os.path.basename(f["path"]), f["issue"])
                      for f in findings}
            self.assertIn((".prisma-sase.env", "loose_permissions"), issues)
            self.assertIn((".prisma-sase2.env", "stray"), issues)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipIf(os.name == "nt", "uninstall.sh is POSIX-only")
class UninstallScript(unittest.TestCase):
    """0.8.5: unquoted word-splitting meant a HOME containing a space left the
    credential file on disk while the script printed "removed ...".

    A deletion tool that reports success without deleting is the worst failure
    mode this script has, so both the happy path and the space-in-path path
    assert on the FILESYSTEM, not on the output.
    """

    def _make_home(self, name):
        home = os.path.join(tempfile.mkdtemp(), name)
        os.makedirs(os.path.join(home, ".prisma-sase-venv"))
        for leaf in (".prisma-sase-launch.log", ".prisma-sase.env",
                     ".prisma-sase2.env"):
            with open(os.path.join(home, leaf), "w") as fh:
                fh.write("x")
        return home

    def _run(self, home, *args):
        return subprocess.run(["bash", UNINSTALL_SH, *args],
                              env=dict(os.environ, HOME=home),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def test_removes_everything_when_home_has_no_space(self):
        home = self._make_home("plain")
        self._run(home, "--yes")
        self.assertEqual(os.listdir(home), [], "nothing should be left")

    def test_removes_everything_when_home_contains_a_space(self):
        home = self._make_home("Eric Chen")
        proc = self._run(home, "--yes")
        self.assertEqual(
            os.listdir(home), [],
            "credential files survived a HOME with a space -- output was:\n%s"
            % proc.stdout.decode())

    def test_dry_run_deletes_nothing(self):
        home = self._make_home("Dry Run")
        self._run(home, "--dry-run")
        self.assertEqual(len(os.listdir(home)), 4)

    def test_keep_credentials_keeps_only_env_files(self):
        home = self._make_home("Keep Creds")
        self._run(home, "--yes", "--keep-credentials")
        self.assertEqual(sorted(os.listdir(home)),
                         [".prisma-sase.env", ".prisma-sase2.env"])

    def test_undeletable_target_fails_loudly(self):
        home = self._make_home("Locked")
        os.chmod(home, 0o500)                     # read-only: rm will fail
        try:
            proc = self._run(home, "--yes")
            self.assertEqual(proc.returncode, 1,
                             "must exit non-zero when a target survives")
            self.assertIn(b"FAILED to remove", proc.stdout)
        finally:
            os.chmod(home, 0o700)


class SecretHandling(unittest.TestCase):
    """Design guarantee: the client secret never reaches tool output or logs."""

    def test_secret_is_never_echoed_by_a_tool(self):
        code = (
            "import sys, io, contextlib; sys.path.insert(0, %r);\n"
            "import config; config.MOCK_MODE = True;\n"
            "config.CLIENT_SECRET = 'CANARY-SECRET-VALUE';\n"
            "from tools.status import get_sase_status;\n"
            "buf = io.StringIO();\n"
            "ctx = contextlib.redirect_stdout(buf);\n"
            "err = contextlib.redirect_stderr(buf);\n"
            "ctx.__enter__(); err.__enter__();\n"
            "res = get_sase_status();\n"
            "err.__exit__(None, None, None); ctx.__exit__(None, None, None);\n"
            "print('LEAK' if 'CANARY-SECRET-VALUE' in repr(res) + buf.getvalue()"
            " else 'CLEAN')" % MCP)
        out = subprocess.run([sys.executable, "-c", code],
                             env=dict(os.environ, PRISMA_MOCK="1"),
                             stdout=subprocess.PIPE, check=True)
        self.assertEqual(out.stdout.decode().strip(), "CLEAN")


class VersionLockstep(unittest.TestCase):
    """PUBLISHING.md requires config.PLUGIN_VERSION == all marketplace entries."""

    def test_versions_match(self):
        import json
        path = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
        with open(path, encoding="utf-8") as fh:
            market = json.load(fh)
        for entry in market["plugins"]:
            self.assertEqual(
                entry["version"], config.PLUGIN_VERSION,
                "%s is v%s but config.PLUGIN_VERSION is v%s -- "
                "PUBLISHING.md requires them in lockstep"
                % (entry["name"], entry["version"], config.PLUGIN_VERSION))


class MockSmokeTest(unittest.TestCase):
    """Every tool returns ok=True offline -- catches import/shape breakage."""

    def test_all_tools_succeed_in_mock_mode(self):
        code = ("import sys; sys.path.insert(0, %r);\n"
                "from tools.status import get_sase_status\n"
                "from tools.alerts import query_alerts\n"
                "from tools.networks import get_remote_networks\n"
                "from tools.users import get_connected_users\n"
                "from tools.adem import get_user_experience\n"
                "from tools.discover import discover_insights\n"
                "bad = [f.__name__ for f in (get_sase_status, query_alerts,\n"
                "        get_remote_networks, get_connected_users,\n"
                "        get_user_experience, discover_insights)\n"
                "       if not f().get('ok')]\n"
                "print(','.join(bad) if bad else 'ALL_OK')" % MCP)
        out = subprocess.run([sys.executable, "-c", code],
                             env=dict(os.environ, PRISMA_MOCK="1"),
                             stdout=subprocess.PIPE, check=True)
        self.assertEqual(out.stdout.decode().strip(), "ALL_OK")


if __name__ == "__main__":
    if sys.version_info < (3, 10):
        sys.stderr.write("These tests need Python >= 3.10 (same floor as the "
                         "server); this is %d.%d.\n" % sys.version_info[:2])
        sys.exit(2)
    unittest.main(verbosity=2)
