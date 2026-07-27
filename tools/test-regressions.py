#!/usr/bin/env python3
"""Regression tests for the prisma-sase plugin -- stdlib unittest, no network.

Run:  python3 tools/test-regressions.py          (needs Python >= 3.10)

Every test here pins a bug that was real and shipped. Each one names the
symptom a user would have seen, so a future change that reintroduces it fails
with an explanation rather than a bare assertion.

Scope: pure logic + the shell scripts' file handling. No live API calls (the
tool layer runs under PRISMA_MOCK=1), no credentials required.
"""
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 0.9.0 moved the server out of plugin/mcp so uvx can package it. The modules
# still import each other by bare name, so this stays a sys.path entry rather
# than becoming a package import.
MCP = os.path.join(ROOT, "src", "prisma_sase_mcp")
# The shell helpers moved with the server: plugin/ now holds nothing but the
# Skill, and these scripts operate on the server's venv, not on the Skill.
UNINSTALL_SH = os.path.join(MCP, "uninstall.sh")

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


class QueryApiFamilyRouting(unittest.TestCase):
    """Issue #15: the 2.0 query API needs its own HOST, not just its own path.

    Symptom: the first fix changed only the path prefix to
    /api/sase/v2.0/resource/query/ while the client still prepended
    API_BASE (api.sase.paloaltonetworks.com). Every probe came back a bare
    404 -- the 2.0 routes are served from pa-<region>01.api.prismaaccess.com.
    A path-only fix must not pass these tests.
    """

    def test_default_family_is_unchanged(self):
        # Existing callers pass no prefix and must keep hitting 3.0.
        self.assertEqual(
            config.insights_path("applications", "application_list"),
            "/insights/v3.0/resource/query/applications/application_list")
        self.assertEqual(config.query_base(None, "sg"), config.API_BASE)

    def test_sase_v2_uses_the_regional_prismaaccess_host(self):
        base = config.query_base("sase_v2", "sg")
        self.assertEqual(base, "https://pa-sg01.api.prismaaccess.com")
        self.assertNotIn("api.sase.paloaltonetworks.com", base,
                         "the 2.0 family must NOT resolve to the 3.0 host -- "
                         "that is the 404 this issue was about")

    def test_region_is_substituted_per_tenant(self):
        for region in ("us", "eu", "uk", "de", "jp"):
            self.assertEqual(config.query_base("sase_v2", region),
                             "https://pa-%s01.api.prismaaccess.com" % region)

    def test_sase_v2_path_has_no_view_segment(self):
        self.assertEqual(
            config.insights_path("prisma_sase_external_alerts_current",
                                 "", prefix="sase_v2"),
            "/api/sase/v2.0/resource/query/prisma_sase_external_alerts_current")

    def test_probe_candidates_may_carry_a_family(self):
        from tools.discover import CANDIDATES
        v2 = [c for c in CANDIDATES if len(c) > 3 and c[3] == "sase_v2"]
        self.assertTrue(v2, "expected sase_v2 alerts_detail candidates")
        # Mixed 3- and 4-tuples must both survive the unpacking loop.
        self.assertTrue(any(len(c) == 3 for c in CANDIDATES))

    def test_the_2_0_family_has_its_own_control_probe(self):
        """Without a control on the 2.0 host, an all-DATA10003 result cannot
        distinguish 'wrong resource names' from 'this tenant does not serve
        the 2.0 query family at all' -- the two read identically."""
        from tools.discover import CANDIDATES
        ctrl = [c for c in CANDIDATES
                if c[0] == "control_sase_v2" and len(c) > 3
                and c[3] == "sase_v2"]
        self.assertTrue(ctrl, "expected a sase_v2 control probe")
        # It must reuse the documented resource that is known-good on 3.0, so
        # a failure indicts the family rather than the name.
        self.assertEqual((ctrl[0][1], ctrl[0][2]),
                         ("applications", "application_list"))

    def test_controls_are_not_selectable_as_a_kind(self):
        """Controls run alongside every kind; they are not user-facing kinds."""
        from tools.discover import discover_insights
        res = discover_insights(kind="control_sase_v2")
        self.assertFalse(res["ok"])
        self.assertIn("Unknown kind", res["error"])


class VersionLockstep(unittest.TestCase):
    """PUBLISHING.md requires one version, declared once, everywhere it shows.

    Since 0.8.7 the version lives in plugin/.claude-plugin/plugin.json only.
    Claude Code always prefers the manifest value over a marketplace entry's,
    so a per-entry version cannot win -- it can only go stale and mislead.
    """

    def _manifest(self):
        import json
        path = os.path.join(ROOT, "plugin", ".claude-plugin", "plugin.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _marketplace(self):
        import json
        path = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_manifest_matches_config(self):
        self.assertEqual(
            self._manifest()["version"], config.PLUGIN_VERSION,
            "plugin.json is v%s but config.PLUGIN_VERSION is v%s -- "
            "PUBLISHING.md requires them in lockstep"
            % (self._manifest()["version"], config.PLUGIN_VERSION))

    def test_marketplace_metadata_matches_config(self):
        meta = self._marketplace()["metadata"]["version"]
        self.assertEqual(
            meta, config.PLUGIN_VERSION,
            "marketplace metadata is v%s but config.PLUGIN_VERSION is v%s -- "
            "PUBLISHING.md requires them in lockstep"
            % (meta, config.PLUGIN_VERSION))

    def test_entries_do_not_redeclare_version(self):
        for entry in self._marketplace()["plugins"]:
            self.assertNotIn(
                "version", entry,
                "%s declares its own version; the manifest always wins, so "
                "this one can only drift out of sight" % entry["name"])


class PluginShipsTheSkillOnly(unittest.TestCase):
    """The plugin must not declare an MCP server. 0.9.0 split them apart.

    Through 0.8.8 the plugin carried both the Skill and the MCP server, with
    credentials arriving via ${user_config.*}. That path never worked
    reliably: 0.8.6 forgot to declare userConfig in the manifest, so sideloads
    got literal placeholders; 0.8.8 documented a host that enables the plugin
    without ever showing the dialog, so the same vars arrived empty. Both
    failures were silent and neither was ours to fix.

    0.9.0 stops fighting it. The MCP server installs as a Local MCP server
    (uvx, credentials as ordinary env vars); the plugin ships the Skill alone.
    If a manifest ever declares mcpServers again, the host would launch a
    second copy of the server alongside the panel's -- duplicate tools, and
    the broken credential path back with them.
    """

    PLACEHOLDER = re.compile(r"\$\{user_config\.([A-Za-z0-9_]+)\}")

    def _manifest(self):
        import json
        path = os.path.join(ROOT, "plugin", ".claude-plugin", "plugin.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def _marketplace(self):
        import json
        path = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)

    def test_manifest_declares_no_mcp_server(self):
        self.assertNotIn(
            "mcpServers", self._manifest(),
            "the plugin ships the Skill only; declaring mcpServers here would "
            "start a second server next to the Local MCP one")

    def test_manifest_declares_no_user_config(self):
        self.assertNotIn(
            "userConfig", self._manifest(),
            "userConfig only means anything alongside an mcpServers block; "
            "leaving it behind would prompt for credentials nothing reads")

    def test_no_entry_reintroduces_a_server(self):
        for entry in self._marketplace()["plugins"]:
            self.assertNotIn(
                "mcpServers", entry,
                "%s overrides mcpServers -- entries inherit the manifest, and "
                "the manifest no longer ships a server" % entry["name"])

    def test_no_user_config_placeholders_survive_anywhere(self):
        import json
        for label, blob in (("plugin.json", self._manifest()),
                            ("marketplace.json", self._marketplace())):
            left = set(self.PLACEHOLDER.findall(json.dumps(blob)))
            self.assertFalse(
                left,
                "%s still references %s; nothing expands those now, so they "
                "would reach a server as literal text"
                % (label, ", ".join(sorted(left))))

    def test_the_skill_is_present(self):
        """It is the plugin's entire payload now."""
        skill = os.path.join(ROOT, "plugin", "skills", "prisma-sase-ops",
                             "SKILL.md")
        self.assertTrue(os.path.isfile(skill),
                        "the plugin has nothing left to ship without %s" % skill)


class UvxPackaging(unittest.TestCase):
    """The Local MCP path is `uvx --from git+... prisma-sase-mcp`.

    uvx resolves the git ref on every launch, which is what makes "push to
    main" reach users without an install step. That only holds while the
    package metadata stays consistent with the code: a stale entry point or a
    dependency that is declared in one place and not the other fails at the
    user's launch, not in CI.
    """

    def _pyproject(self):
        try:
            import tomllib
        except ModuleNotFoundError:                    # Python 3.10
            self.skipTest("tomllib needs Python >= 3.11")
        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
            return tomllib.load(fh)

    def test_version_matches_config(self):
        ver = self._pyproject()["project"]["version"]
        self.assertEqual(
            ver, config.PLUGIN_VERSION,
            "pyproject is v%s but config.PLUGIN_VERSION is v%s -- uvx would "
            "install a build whose own logs disagree with it"
            % (ver, config.PLUGIN_VERSION))

    def test_entry_points_resolve(self):
        scripts = self._pyproject()["project"]["scripts"]
        for name, target in (("prisma-sase-mcp",
                              "prisma_sase_mcp.__main__:main"),
                             ("prisma-sase-setup",
                              "prisma_sase_mcp.__main__:setup")):
            self.assertEqual(
                scripts.get(name), target,
                "%s must point at %s -- the README and the setup wizard both "
                "emit that exact console script" % (name, target))
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_pkg_main", os.path.join(MCP, "__main__.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for attr in ("main", "setup"):
            self.assertTrue(callable(getattr(mod, attr, None)),
                            "__main__.%s is not callable" % attr)

    def test_dependencies_match_requirements_txt(self):
        """run.sh installs from requirements.txt; uvx installs from pyproject."""
        declared = set(self._pyproject()["project"]["dependencies"])
        req = set()
        with open(os.path.join(MCP, "requirements.txt"), encoding="utf-8") as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    req.add(line)
        self.assertEqual(
            declared, req,
            "pyproject and requirements.txt disagree; the two launch paths "
            "would resolve different versions.\n  pyproject only: %s\n  "
            "requirements only: %s"
            % (sorted(declared - req), sorted(req - declared)))

    def test_the_package_is_importable_as_a_package(self):
        """__init__ must not drag in fastmcp -- setup runs before deps exist."""
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r); "
             "import prisma_sase_mcp; "
             "assert not [m for m in ('fastmcp', 'httpx') if m in sys.modules],"
             " 'importing the package pulled in a heavy dependency'; "
             "print(prisma_sase_mcp.__name__)"
             % os.path.join(ROOT, "src")],
            capture_output=True, text=True)
        self.assertEqual(out.returncode, 0,
                         "importing the package failed:\n%s" % out.stderr)

    def test_tools_are_importable_by_package_path(self):
        """0.9.0 -- SKILL.md calls this the MCP-free escape hatch.

        The Skill tells the assistant it can always fall back to
        `from prisma_sase_mcp.tools.status import get_sase_status` when the
        MCP layer is unavailable, and calls that a design guarantee. But every
        tool module opens with a flat `import config`, and the sys.path shim
        that makes those resolve lived in __main__ -- so the documented import
        raised ModuleNotFoundError unless you had gone through the console
        script. The one path a broken install is supposed to fall back to was
        the one path that did not work.
        """
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r);\n"
             "from prisma_sase_mcp.tools.status import get_sase_status\n"
             "from prisma_sase_mcp.tools.alerts import query_alerts\n"
             "print(get_sase_status()['ok'])" % os.path.join(ROOT, "src")],
            capture_output=True, text=True,
            env=dict(os.environ, PRISMA_MOCK="1"))
        self.assertEqual(out.returncode, 0,
                         "the fallback SKILL.md documents does not work:\n%s"
                         % out.stderr)
        self.assertIn("True", out.stdout)


class SetupWizard(unittest.TestCase):
    """The guided setup replaces the enable dialog the panel does not have.

    Its whole reason to exist is that panel values are plaintext: it puts the
    secret in the keychain and emits PRISMA_SECRET_CMD instead. A regression
    that quietly writes the secret into the panel block would look fine and
    undo the point.
    """

    def _wizard(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_setup_wizard", os.path.join(MCP, "setup_wizard.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_entry_uses_secret_cmd_not_a_plaintext_secret(self):
        w = self._wizard()
        entry = w._panel_entry("apikey@123.iam.panserviceaccount.com", "123",
                               "americas", "printf secret")
        env = entry["env"]
        self.assertIn("PRISMA_SECRET_CMD", env)
        self.assertNotIn(
            "PRISMA_CLIENT_SECRET", env,
            "the whole point is that the secret is not in the panel")

    def test_entry_without_a_keychain_is_visibly_a_placeholder(self):
        """No keychain is a real case; it must not look like a working config."""
        w = self._wizard()
        env = w._panel_entry("id", "123", "americas", None)["env"]
        self.assertIn("<paste", env.get("PRISMA_CLIENT_SECRET", ""),
                      "a blank value would start a server that fails later "
                      "with no clue why")

    def test_entry_launches_through_uvx_from_git(self):
        """Anything else loses the auto-update this architecture exists for."""
        w = self._wizard()
        entry = w._panel_entry("id", "123", "americas", "cmd")
        self.assertTrue(entry["command"].endswith("uvx"), entry["command"])
        self.assertIn("--from", entry["args"])
        self.assertTrue(any(a.startswith("git+") for a in entry["args"]),
                        "args must pin a git URL: %s" % entry["args"])
        self.assertIn("prisma-sase-mcp", entry["args"])

    def test_written_config_is_owner_only_and_keeps_other_servers(self):
        w = self._wizard()
        home = tempfile.mkdtemp()
        try:
            path = os.path.join(home, "claude_desktop_config.json")
            import json
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"mcpServers": {"someone-else": {"command": "x"}}}, fh)
            w._panel_config_path = lambda: path
            written, action = w._write_panel_config(
                w._panel_entry("id", "123", "americas", "cmd"))
            self.assertEqual(action, "added")
            with open(written, encoding="utf-8") as fh:
                got = json.load(fh)
            self.assertIn("someone-else", got["mcpServers"],
                          "clobbered an unrelated server")
            self.assertIn("prisma-sase", got["mcpServers"])
            self.assertEqual(oct(os.stat(written).st_mode & 0o777), "0o600")
            self.assertTrue(os.path.exists(written + ".bak"),
                            "no backup was left behind")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_broken_config_is_not_overwritten(self):
        """Better to fail than to silently discard someone's servers."""
        w = self._wizard()
        home = tempfile.mkdtemp()
        try:
            path = os.path.join(home, "claude_desktop_config.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ this is not json")
            w._panel_config_path = lambda: path
            with self.assertRaises(Exception):
                w._write_panel_config(w._panel_entry("id", "1", "a", "c"))
            with open(path, encoding="utf-8") as fh:
                self.assertIn("not json", fh.read())
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_no_secret_is_ever_passed_where_ps_can_read_it(self):
        """argv is world-readable; only the macOS backend has no stdin mode."""
        src = open(os.path.join(MCP, "setup_wizard.py"), encoding="utf-8").read()
        body = src.split("def _store_secret", 1)[1].split("\ndef ", 1)[0]
        for backend in ("secret-tool", "pass"):
            chunk = body.split('"%s"' % backend, 1)[1].split("elif", 1)[0]
            self.assertIn("input=", chunk,
                          "the %s backend must receive the secret on stdin, "
                          "not in argv" % backend)

    # -- which config file gets written (field report, 2026-07-27) ----------
    #
    # The app directory is not always "Claude": a third-party/enterprise build
    # uses a suffix (Claude-3p). Writing blindly to "Claude" on such a machine
    # reports success into a file the running app never reads -- credentials
    # present, no tools, and nothing anywhere says why.

    def _fake_home(self, *dirnames):
        """Build a Library/Application Support tree with the given app dirs."""
        home = tempfile.mkdtemp()
        base = os.path.join(home, "Library", "Application Support")
        made = []
        for name in dirnames:
            d = os.path.join(base, name)
            os.makedirs(d)
            p = os.path.join(d, "claude_desktop_config.json")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('{"mcpServers": {}}\n')
            made.append(p)
        return home, made

    def _with_home(self, w, home, env=None):
        """Point the wizard at a fake home, undoing it when the test ends.

        w.os and w.platform are the real shared modules, so these patches must
        be reverted or they leak into every test that runs afterwards.
        """
        import unittest.mock as mock
        for p in (mock.patch.object(
                      w.os.path, "expanduser",
                      lambda q: q.replace("~", home, 1)
                      if q.startswith("~") else q),
                  mock.patch.object(w.platform, "system", lambda: "Darwin"),
                  # patch.dict snapshots and restores the whole mapping on
                  # stop, so edits made after start() are undone too.
                  mock.patch.dict(w.os.environ, env or {})):
            p.start()
            self.addCleanup(p.stop)
        if not env:
            w.os.environ.pop("PRISMA_PANEL_CONFIG", None)

    def test_suffixed_app_dir_is_found_when_it_is_the_only_one(self):
        w = self._wizard()
        home, (three_p,) = self._fake_home("Claude-3p")
        try:
            self._with_home(w, home)
            self.assertEqual(
                w._panel_config_path(), three_p,
                "only Claude-3p exists, so writing to Claude/ would land in a "
                "file no app reads")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_with_several_installs_the_most_recent_one_wins(self):
        w = self._wizard()
        home, (plain, three_p) = self._fake_home("Claude", "Claude-3p")
        try:
            os.utime(plain, (1_600_000_000, 1_600_000_000))
            os.utime(three_p, (1_700_000_000, 1_700_000_000))
            self._with_home(w, home)
            self.assertEqual(w._panel_config_path(), three_p,
                             "the recently-touched config is the app in use")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_an_explicit_override_beats_the_guess(self):
        """The heuristic can be wrong; there must be a way to say so."""
        w = self._wizard()
        home, _ = self._fake_home("Claude", "Claude-3p")
        try:
            chosen = os.path.join(home, "somewhere-else.json")
            self._with_home(w, home, env={"PRISMA_PANEL_CONFIG": chosen})
            self.assertEqual(w._panel_config_path(), chosen)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_fresh_machine_still_gets_the_plain_path(self):
        w = self._wizard()
        home, _ = self._fake_home()
        try:
            self._with_home(w, home)
            self.assertTrue(
                w._panel_config_path().endswith(
                    os.path.join("Claude", "claude_desktop_config.json")),
                w._panel_config_path())
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def _choose(self, w, answer):
        """Run the interactive chooser with `answer` typed at the prompt."""
        import io
        import unittest.mock as mock
        out = io.StringIO()
        with mock.patch.object(w, "input", create=True,
                               side_effect=lambda _="": answer), \
                contextlib.redirect_stdout(out):
            return w._choose_panel_config(), out.getvalue()

    def test_several_installs_are_offered_as_a_choice(self):
        """The heuristic must not decide this silently.

        Picking wrong is invisible -- the write succeeds and no tools appear
        -- so the user has to see the alternatives and be able to say which.
        """
        w = self._wizard()
        home, (plain, three_p) = self._fake_home("Claude", "Claude-3p")
        try:
            os.utime(plain, (1_600_000_000, 1_600_000_000))
            os.utime(three_p, (1_700_000_000, 1_700_000_000))
            self._with_home(w, home)

            chosen, shown = self._choose(w, "")        # bare Enter
            self.assertEqual(chosen, three_p, "default is the recent one")
            self.assertIn(plain, shown,
                          "the alternative must be listed, not hidden")

            chosen, _ = self._choose(w, "2")           # override the default
            self.assertEqual(chosen, plain,
                             "an explicit answer must be honoured")
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_a_single_install_is_not_turned_into_a_question(self):
        """Asking when there is nothing to choose is just noise."""
        w = self._wizard()
        home, (three_p,) = self._fake_home("Claude-3p")
        try:
            self._with_home(w, home)
            chosen, shown = self._choose(w, "")
            self.assertEqual(chosen, three_p)
            self.assertNotIn("which one", shown.lower())
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_the_listing_names_servers_but_never_values(self):
        """The chooser reads other people's configs to describe them.

        Those hold API tokens. Printing a value to help someone tell two
        configs apart would leak a credential to the terminal and the scroll
        buffer -- names are enough to identify a file.
        """
        w = self._wizard()
        home, (plain,) = self._fake_home("Claude")
        try:
            with open(plain, "w", encoding="utf-8") as fh:
                json.dump({"mcpServers": {"other": {
                    "env": {"API_TOKEN": "s3cr3t-do-not-print"}}}}, fh)
            self._with_home(w, home)
            desc = w._describe_config(plain)
            self.assertIn("other", desc)
            self.assertNotIn("s3cr3t", desc)
            self.assertNotIn("API_TOKEN", desc)
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_an_unreadable_config_is_described_not_crashed_on(self):
        w = self._wizard()
        home, (plain,) = self._fake_home("Claude")
        try:
            with open(plain, "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            self._with_home(w, home)
            self.assertIn("JSON", w._describe_config(plain))
        finally:
            shutil.rmtree(home, ignore_errors=True)

    def test_no_terminal_falls_back_instead_of_dying(self):
        """Piped stdin is a real case (CI, a wrapper script)."""
        w = self._wizard()
        home, (plain, three_p) = self._fake_home("Claude", "Claude-3p")
        try:
            os.utime(plain, (1_600_000_000, 1_600_000_000))
            os.utime(three_p, (1_700_000_000, 1_700_000_000))
            self._with_home(w, home)
            import io
            import unittest.mock as mock
            out = io.StringIO()
            with mock.patch.object(w, "input", create=True,
                                   side_effect=EOFError), \
                    contextlib.redirect_stdout(out):
                chosen = w._choose_panel_config()
            self.assertEqual(chosen, three_p)
            self.assertIn(three_p, out.getvalue(),
                          "a silent fallback is the bug this fixes")
        finally:
            shutil.rmtree(home, ignore_errors=True)


class CrossPlatform(unittest.TestCase):
    """0.9.0 -- the wizard has to behave on the two systems it is not being
    developed on.

    Every one of these runs on macOS against a patched platform.system(), so
    they pin the *shape* of what would be emitted, not that it works. What
    they can catch is the class of bug that put this class here: Windows had
    no secret backend at all, so the wizard's whole purpose -- keeping the
    secret out of the plaintext config -- quietly did not apply there, and
    nothing failed to say so.
    """

    def _wizard(self, osname, **env):
        """Load setup_wizard as `osname`, with a clean PRISMA_* environment."""
        import importlib.util
        import unittest.mock as mock
        spec = importlib.util.spec_from_file_location(
            "wiz_%s" % osname, os.path.join(MCP, "setup_wizard.py"))
        w = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(w)
        p = mock.patch.object(w.platform, "system", lambda: osname)
        p.start()
        self.addCleanup(p.stop)
        d = mock.patch.dict(w.os.environ, env)
        d.start()
        self.addCleanup(d.stop)
        return w

    def _fake_powershell(self, w, path=r"C:\Windows\System32\powershell.exe"):
        import unittest.mock as mock
        p = mock.patch.object(w.shutil, "which",
                              lambda n: path if n == "powershell" else None)
        p.start()
        self.addCleanup(p.stop)

    # -- the bug this class exists for ------------------------------------

    def test_windows_has_a_secret_backend(self):
        """Without one the wizard delivers less than it advertises.

        Its stated purpose is keeping the secret out of the plaintext config.
        On Windows it used to find no backend, emit a
        PRISMA_CLIENT_SECRET placeholder, and tell the user to paste the
        secret into the very file the wizard exists to keep it out of.
        """
        w = self._wizard("Windows")
        self._fake_powershell(w)
        name, fetch = w._backend()
        self.assertEqual(name, "dpapi")
        self.assertTrue(fetch)

        entry = w._panel_entry("cid@1", "1", "sg", w._quote(fetch))
        self.assertIn("PRISMA_SECRET_CMD", entry["env"])
        self.assertNotIn("PRISMA_CLIENT_SECRET", entry["env"],
                         "a plaintext secret field is what dpapi replaces")

    def test_windows_secret_command_survives_cmd_exe(self):
        """PRISMA_SECRET_CMD is run with shell=True -- cmd.exe on Windows.

        shlex.quote emits POSIX single quotes, which cmd.exe passes through
        as literal characters; PowerShell would then see an argument starting
        with a stray quote. cmd.exe also eats bare double quotes and expands
        %VAR% even inside them.
        """
        w = self._wizard("Windows")
        self._fake_powershell(w)
        cmd = w._quote(w._backend()[1])
        self.assertNotIn("'C:", cmd, "POSIX quoting leaked into a cmd.exe line")
        self.assertNotIn("%", cmd, "cmd.exe would expand this as a variable")
        self.assertEqual(cmd.count('"') % 2, 0, "unbalanced double quotes")

    def test_windows_quoting_refuses_what_it_cannot_express(self):
        """cmd.exe cannot escape a double quote inside a quoted argument.

        Emitting a mangled command would fail at launch with no clue why, so
        the quoting raises instead.
        """
        w = self._wizard("Windows")
        with self.assertRaises(ValueError):
            w._quote(['say "hi"'])

    def test_a_path_with_a_space_is_quoted(self):
        """Program Files is the default install location for a lot of this."""
        w = self._wizard("Windows")
        self.assertEqual(w._quote([r"C:\Program Files\ps.exe", "-x"]),
                         r'"C:\Program Files\ps.exe" -x')

    def test_a_metacharacter_without_a_space_is_still_quoted(self):
        """`&` splits a cmd.exe line on its own -- quoting only on
        whitespace would let the tail of an argument run as a command."""
        w = self._wizard("Windows")
        self.assertEqual(w._quote(["a&calc"]), '"a&calc"')

    def test_a_percent_sign_is_refused(self):
        """cmd.exe expands %VAR% even inside double quotes, and nothing
        available here escapes it."""
        w = self._wizard("Windows")
        with self.assertRaises(ValueError):
            w._quote(["%USERPROFILE%"])

    def test_the_blob_path_is_backslashed(self):
        """It is interpolated into PowerShell and read by Windows. Built with
        os.path.join it comes out mixed-separator when this runs elsewhere."""
        w = self._wizard("Windows", LOCALAPPDATA=r"C:\Users\e\AppData\Local")
        self.assertNotIn("/", w._dpapi_blob_path())

    # -- PATH --------------------------------------------------------------

    def test_the_panel_path_is_not_macos_shaped_on_linux(self):
        """uvx needs git and its interpreter findable, and the app supplies
        no PATH. ~/.local/bin is where the official uv installer puts them."""
        w = self._wizard("Linux")
        path = w._panel_path()
        self.assertIn(".local/bin", path)
        self.assertIn(":", path)
        self.assertNotIn(";", path)

    def test_the_panel_path_uses_windows_separators(self):
        w = self._wizard("Windows", SystemRoot=r"C:\Windows")
        path = w._panel_path()
        self.assertIn(";", path)
        self.assertIn(r"C:\Windows\System32", path)

    def test_windows_keeps_its_path(self):
        """It used to be popped, on the theory that Windows resolves .exe
        without help. uvx still has to find git."""
        w = self._wizard("Windows")
        self._fake_powershell(w)
        self.assertIn("PATH", w._panel_entry("c", "1", "sg", None)["env"])

    def test_the_directory_uvx_lives_in_is_on_the_path(self):
        """A non-standard install location has to work without an edit here."""
        import unittest.mock as mock
        w = self._wizard("Linux")
        with mock.patch.object(w.shutil, "which",
                               lambda n: "/opt/weird/bin/uvx"
                               if n == "uvx" else None):
            self.assertTrue(w._panel_path().startswith("/opt/weird/bin:"))

    # -- config location ---------------------------------------------------

    def test_windows_config_lives_under_appdata(self):
        import unittest.mock as mock
        w = self._wizard("Windows", APPDATA=r"C:\Users\e\AppData\Roaming")
        with mock.patch.object(w.os, "listdir", lambda _: []):
            self.assertEqual(w._panel_config_dirs()[0],
                             os.path.join(r"C:\Users\e\AppData\Roaming",
                                          "Claude"))

    def test_the_dpapi_blob_is_local_not_roaming(self):
        """DPAPI ties the blob to this user on this machine, so roaming it
        would only propagate a file the other machine cannot decrypt."""
        w = self._wizard("Windows", LOCALAPPDATA=r"C:\Users\e\AppData\Local")
        self.assertTrue(w._dpapi_blob_path().startswith(
            r"C:\Users\e\AppData\Local"))

    # -- the PowerShell itself ---------------------------------------------

    def test_the_powershell_never_puts_the_secret_on_a_command_line(self):
        """argv is readable by every process running as this user."""
        w = self._wizard("Windows")
        store = w._dpapi_store_script(r"C:\x\secret.bin")
        self.assertIn("[Console]::In.ReadLine()", store)
        self.assertNotIn("-AsPlainText $s", store)

    def test_the_powershell_is_inline_so_execution_policy_cannot_block_it(self):
        """Execution policy applies to script files, not -Command."""
        w = self._wizard("Windows")
        self._fake_powershell(w)
        argv = w._backend()[1]
        self.assertIn("-Command", argv)
        self.assertNotIn("-File", argv)
        self.assertIn("-NoProfile", argv,
                      "a user profile could print banners into stdout")

    def test_a_path_with_a_quote_in_it_cannot_break_out_of_the_script(self):
        w = self._wizard("Windows")
        self.assertEqual(w._ps_quote("it's"), "'it''s'")

    def test_dpapi_encrypts_with_no_key_so_it_binds_to_the_user(self):
        """ConvertFrom-SecureString -Key would use a key we would then have
        to store somewhere, defeating the point."""
        w = self._wizard("Windows")
        self.assertNotIn("-Key", w._dpapi_store_script(r"C:\x"))

    # -- ARM64 Windows: cryptography has no win_arm64 wheel ------------------

    def _arch(self, w, machine):
        import unittest.mock as mock
        p = mock.patch.object(w.platform, "machine", lambda: machine)
        p.start()
        self.addCleanup(p.stop)

    def test_arm64_windows_asks_for_an_x64_interpreter(self):
        """Verified on a real ARM64 Windows VM: the native interpreter sends uv
        off to build cryptography==49.0.0 from source, because its authors
        publish no win_arm64 wheel for the current version. That needs Rust and
        MSVC, and the failure names cargo rather than anything to do with this
        plugin. x64 is emulated on ARM Windows and its wheels exist."""
        w = self._wizard("Windows")
        self._arch(w, "ARM64")
        args = w._uvx_args()
        self.assertIn("--python", args)
        self.assertEqual("cpython-3.12-windows-x86_64",
                         args[args.index("--python") + 1])

    def test_the_interpreter_is_pinned_only_where_it_is_needed(self):
        """Choosing uv's interpreter for it is a liberty, justified only by the
        missing wheel. Everywhere else uv should decide."""
        for osname, machine in (("Windows", "AMD64"), ("Darwin", "arm64"),
                                ("Darwin", "x86_64"), ("Linux", "aarch64"),
                                ("Linux", "x86_64")):
            with self.subTest(os=osname, machine=machine):
                w = self._wizard(osname)
                self._arch(w, machine)
                self.assertEqual(["--from", w.GIT_URL, "prisma-sase-mcp"],
                                 w._uvx_args())

    def test_the_from_argument_still_comes_last(self):
        """uvx reads everything before --from as its own. A flag appended after
        the package would be passed to the server instead, which would take it
        for an unknown option."""
        w = self._wizard("Windows")
        self._arch(w, "ARM64")
        args = w._uvx_args()
        self.assertEqual(["--from", w.GIT_URL, "prisma-sase-mcp"], args[-3:])

    def test_the_panel_entry_carries_the_interpreter_through(self):
        """_uvx_args being right is no use if the entry does not use it."""
        w = self._wizard("Windows")
        self._arch(w, "ARM64")
        self._fake_powershell(w)
        entry = w._panel_entry("cid", "tsg", "de", "cmd")
        self.assertIn("--managed-python", entry["args"])


class WindowsVerifierScript(unittest.TestCase):
    """0.9.0 -- tools/verify-windows.ps1 is written on macOS and only ever runs
    on Windows, so a syntax error in it is not discovered until someone is
    sitting at a VM waiting for an answer.

    That happened: a `\\"` escape, correct in C and sh, is not an escape in
    PowerShell. The file failed to parse and none of the ten checks ran. These
    tests are the cheap half of the guard -- a parser is better, and
    test_it_parses runs one when pwsh is available."""

    PS1 = os.path.join(ROOT, "tools", "verify-windows.ps1")

    def setUp(self):
        with open(self.PS1, "r", encoding="utf-8") as fh:
            self.src = fh.read()

    def test_no_backslash_escaped_quotes(self):
        r"""PowerShell escapes a double quote as `" or "", never \". Writing
        \" is the C/sh habit and produces a parse error, not a quote."""
        bad = [(i, l) for i, l in enumerate(self.src.splitlines(), 1)
               if '\\"' in l]
        self.assertEqual([], bad,
                         "backslash-escaped quotes are not PowerShell:\n" +
                         "\n".join("  L%d: %s" % (i, l.strip()) for i, l in bad))

    def test_no_powershell_7_only_syntax(self):
        """Windows ships Windows PowerShell 5.1. ??, && and ?. are 7.0+, and
        this script has to run on a stock machine."""
        code = "\n".join(l for l in self.src.splitlines()
                         if not l.lstrip().startswith("#"))
        for tok in ("??", "&&", "?."):
            self.assertNotIn(tok, code, "%r needs PowerShell 7" % tok)

    def test_args_is_not_assigned(self):
        """$args is an automatic variable; assigning to it works until it
        does not."""
        self.assertNotRegex(self.src, r"\$args\s*=")

    def test_it_parses(self):
        """The real check, when a parser is to hand. Skipped rather than
        failed when it is not, so this suite still runs anywhere."""
        pwsh = shutil.which("pwsh") or "/tmp/psdl/pwsh"
        if not os.path.exists(pwsh):
            self.skipTest("no pwsh available to parse with")
        script = (
            '$e=$null;'
            '[System.Management.Automation.Language.Parser]::ParseFile('
            '"%s",[ref]$null,[ref]$e)|Out-Null;'
            'if($e){$e|%%{"L$($_.Extent.StartLineNumber): $($_.Message)"}}'
            % self.PS1)
        out = subprocess.run([pwsh, "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=120)
        self.assertEqual("", out.stdout.strip(), "parse errors:\n" + out.stdout)


class HostSuppliedNothing(unittest.TestCase):
    """0.8.8 -- the host enables the plugin without ever running the
    userConfig dialog, then expands ${user_config.*} to EMPTY STRINGS.

    Field-verified on the Cowork marketplace-cache surface: settings.json
    listed the plugin under enabledPlugins with no pluginConfigs entry, and
    every tool failed with a bare "missing credentials". The plugin blamed
    itself -- its placeholder guard could not fire, because the values were
    not literal ${...}, they were "".

    These tests pin the distinction the diagnosis rests on: absent, empty and
    literal-placeholder are three different states with three different fixes.
    """

    ENABLED_NO_CONFIG = ('{"enabledPlugins": {"prisma-sase-mac@prisma-sase": '
                         'true}, "pluginConfigs": {"other@x": {"options": '
                         '{"a": "b"}}}}')

    def _diagnose(self, settings_json=None, **env_overrides):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        if settings_json is not None:
            os.makedirs(os.path.join(home, ".claude"))
            with open(os.path.join(home, ".claude", "settings.json"), "w") as fh:
                fh.write(settings_json)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PRISMA_")}
        env["HOME"] = home
        env.update(env_overrides)
        code = ("import sys, json; sys.path.insert(0, %r); import config;\n"
                "d = config.userconfig_diagnosis();\n"
                "print(json.dumps({'kind': (d or {}).get('kind'),\n"
                "  'vars': (d or {}).get('vars'),\n"
                "  'empty': config.EMPTY_VARS,\n"
                "  'msg': (d or {}).get('message', '')}))" % MCP)
        out = subprocess.run([sys.executable, "-c", code], env=env,
                             stdout=subprocess.PIPE, check=True)
        import json
        return json.loads(out.stdout.decode())

    def test_empty_string_is_not_treated_as_absent(self):
        result = self._diagnose(self.ENABLED_NO_CONFIG,
                                PRISMA_CLIENT_ID="", PRISMA_TSG_ID="",
                                PRISMA_REGION="sg")
        self.assertIn("PRISMA_CLIENT_ID", result["empty"])
        self.assertIn("PRISMA_TSG_ID", result["empty"])
        self.assertEqual(result["kind"], "expanded_empty")

    def test_diagnosis_attributes_the_fault_away_from_the_plugin(self):
        """Empty-not-absent must still exonerate the tenant and the plugin.

        0.9.0 changed WHO gets named -- the Local MCP entry rather than the
        enable dialog -- but not the property that matters: the user must not
        be sent to debug their tenant, and must be given a way out.
        """
        result = self._diagnose(self.ENABLED_NO_CONFIG,
                                PRISMA_CLIENT_ID="", PRISMA_CLIENT_SECRET="",
                                PRISMA_TSG_ID="", PRISMA_REGION="sg")
        self.assertIn("EMPTY string(s)", result["msg"])
        self.assertIn("nothing you change in the plugin", result["msg"])
        # It must also offer a way out, not just an attribution.
        self.assertIn("prisma-sase-setup", result["msg"])

    def test_enabled_with_no_config_entry_is_no_longer_a_diagnosis(self):
        """0.9.0 -- the inverse regression of the one above.

        Through 0.8.x, "enabled but no pluginConfigs entry" meant the enable
        dialog never ran, because the plugin declared userConfig and so a
        configured install always had an entry. 0.9.0 removed userConfig: the
        plugin is a Skill and credentials arrive via the Local MCP entry,
        which settings.json knows nothing about. That state is now what a
        CORRECT install looks like, so claiming "this is a HOST issue" here
        told every new user their working setup was broken and sent them
        looking for a dialog that no longer exists.
        """
        result = self._diagnose(self.ENABLED_NO_CONFIG)
        self.assertIsNone(
            result["kind"],
            "a Skill-only install with no credentials yet is ordinary, not a "
            "host fault -- got: %s" % result["msg"])

    def test_literal_placeholders_outrank_settings_json(self):
        """Direct evidence from this process beats what settings.json implies."""
        result = self._diagnose(self.ENABLED_NO_CONFIG,
                                PRISMA_CLIENT_ID="${user_config.client_id}")
        self.assertEqual(result["kind"], "unexpanded")

    def test_no_false_alarm_when_credentials_are_present(self):
        result = self._diagnose(self.ENABLED_NO_CONFIG,
                                PRISMA_CLIENT_ID="id", PRISMA_CLIENT_SECRET="s",
                                PRISMA_TSG_ID="1", PRISMA_REGION="sg")
        self.assertIsNone(result["kind"])

    def test_no_diagnosis_without_host_evidence(self):
        """Credentials simply absent -- nobody has run setup yet, no fault."""
        result = self._diagnose(None)
        self.assertIsNone(result["kind"])

    def test_selfcheck_points_a_fresh_install_at_setup(self):
        """The no-credentials-yet path must offer the fix, not an accusation.

        Pairs with the diagnosis test above: having stopped calling this a
        host fault, selfcheck still has to tell the user what to actually do.
        """
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, ".claude"))
        with open(os.path.join(home, ".claude", "settings.json"), "w") as fh:
            fh.write(self.ENABLED_NO_CONFIG)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PRISMA_")}
        env["HOME"] = home
        proc = subprocess.run(
            [sys.executable, os.path.join(MCP, "server.py"), "--selfcheck"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = proc.stdout.decode()
        self.assertIn("prisma-sase-setup", text,
                      "must name the setup command:\n" + text)
        for accusation in ("HOST issue", "enable dialog never",
                           "ENABLED but has NO configuration entry"):
            self.assertNotIn(accusation, text,
                             "must not blame the host on a fresh install:\n"
                             + text)

    def test_selfcheck_does_not_claim_the_plugin_is_configured(self):
        """The reassuring 'IS configured' branch must not fire here.

        That branch exits 0 and tells the user everything is fine -- the same
        false positive the settings UI gives with its fixed-width masked dots.
        """
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, ".claude"))
        with open(os.path.join(home, ".claude", "settings.json"), "w") as fh:
            fh.write(self.ENABLED_NO_CONFIG)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PRISMA_")}
        env.update({"HOME": home, "PRISMA_CLIENT_ID": "",
                    "PRISMA_CLIENT_SECRET": "", "PRISMA_TSG_ID": "",
                    "PRISMA_REGION": "sg"})
        proc = subprocess.run(
            [sys.executable, os.path.join(MCP, "server.py"), "--selfcheck"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        text = proc.stdout.decode()
        self.assertEqual(proc.returncode, 1,
                         "must exit non-zero:\n" + text)
        self.assertNotIn("The plugin IS configured", text)
        self.assertIn("expanded_empty", text)

    def test_status_tool_blames_the_config_not_the_tenant(self):
        """Desktop users only reach the tools -- the verdict must be there."""
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        os.makedirs(os.path.join(home, ".claude"))
        with open(os.path.join(home, ".claude", "settings.json"), "w") as fh:
            fh.write(self.ENABLED_NO_CONFIG)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith("PRISMA_")}
        env.update({"HOME": home, "PRISMA_CLIENT_ID": "",
                    "PRISMA_CLIENT_SECRET": "", "PRISMA_TSG_ID": "",
                    "PRISMA_REGION": "sg"})
        code = ("import sys, json; sys.path.insert(0, %r);\n"
                "from tools.status import get_sase_status;\n"
                "r = get_sase_status();\n"
                "print(json.dumps({'headline': r['headline'],\n"
                "  'cns': r.get('credentials_not_supplied')}))" % MCP)
        out = subprocess.run([sys.executable, "-c", code], env=env,
                             stdout=subprocess.PIPE, check=True)
        import json
        result = json.loads(out.stdout.decode())
        self.assertIsNotNone(result["cns"],
                             "get_sase_status must carry the verdict")
        self.assertEqual(result["cns"]["whose_fault"], "configuration")
        self.assertIn("configuration problem", result["headline"])
        self.assertNotIn("tenant problem.", result["headline"].split("not a")[0])


@unittest.skipIf(os.name == "nt", "setup-keychain.sh is POSIX-only")
class KeychainSetupScript(unittest.TestCase):
    """0.8.8 -- the recommended stopgap when the enable dialog is unavailable.

    Its whole point is that the secret never lands in a file, so the test that
    matters is: whatever it writes, the secret is not in it.
    """

    SCRIPT = os.path.join(MCP, "setup-keychain.sh")
    SECRET = "CANARY-KEYCHAIN-SECRET"

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        # A fake `security` on PATH: the real one needs a GUI authorization
        # prompt that no test environment can answer.
        binn = os.path.join(self.home, "bin")
        os.makedirs(binn)
        fake = os.path.join(binn, "security")
        with open(fake, "w") as fh:
            fh.write(
                "#!/usr/bin/env bash\n"
                "store=%s/store\n"
                'case "$1" in\n'
                '  add-generic-password) printf "%%s" "${!#}" > "$store" ;;\n'
                '  find-generic-password) cat "$store" 2>/dev/null ;;\n'
                '  delete-generic-password) rm -f "$store" ;;\n'
                "esac\n" % self.home)
        os.chmod(fake, 0o755)
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith("PRISMA_")}
        self.env.update({"HOME": self.home,
                         "PATH": binn + os.pathsep + os.environ["PATH"]})
        self.envf = os.path.join(self.home, ".prisma-sase.env")

    def _run(self, *args, stdin=None):
        return subprocess.run(["bash", self.SCRIPT, *args], env=self.env,
                              input=stdin.encode() if stdin else None,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def test_script_is_syntactically_valid(self):
        proc = subprocess.run(["bash", "-n", self.SCRIPT],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode())

    def test_written_env_file_contains_no_plaintext_secret(self):
        self._run("--stdin", stdin=self.SECRET)
        with open(self.envf) as fh:
            content = fh.read()
        self.assertNotIn(self.SECRET, content,
                         "the whole point of this script is that the secret "
                         "does not land in the file")
        self.assertIn("PRISMA_SECRET_CMD=", content)

    def test_env_file_is_owner_only(self):
        self._run("--stdin", stdin=self.SECRET)
        self.assertEqual(os.stat(self.envf).st_mode & 0o777, 0o600)

    def test_tuning_variables_survive(self):
        """The dialog does not cover these, so the file is their only home."""
        with open(self.envf, "w") as fh:
            fh.write('PRISMA_INSIGHTS_MAP={"alerts":{"resource":"a"}}\n'
                     "PRISMA_CLIENT_ID=keep-me\n")
        self._run("--stdin", stdin=self.SECRET)
        with open(self.envf) as fh:
            content = fh.read()
        self.assertIn("PRISMA_INSIGHTS_MAP=", content)
        self.assertIn("keep-me", content)

    def test_migrating_from_plaintext_warns_about_rotation(self):
        with open(self.envf, "w") as fh:
            fh.write("PRISMA_CLIENT_SECRET=OLD-PLAINTEXT\n"
                     "PRISMA_CLIENT_ID=x\nPRISMA_TSG_ID=1\n")
        out = self._run("--stdin", stdin=self.SECRET).stdout.decode()
        self.assertIn("ROTATE", out,
                      "removing a plaintext secret does not un-expose it")
        with open(self.envf) as fh:
            self.assertNotIn("OLD-PLAINTEXT", fh.read())

    def test_incomplete_unattended_run_warns(self):
        out = self._run("--stdin", stdin=self.SECRET).stdout.decode()
        self.assertIn("still empty", out,
                      "a file missing client_id/tsg_id must not look complete")

    def test_the_server_resolves_the_secret_through_the_written_file(self):
        """End to end: script -> env file -> config picks the secret up."""
        self._run("--stdin", stdin=self.SECRET)
        code = ("import sys; sys.path.insert(0, %r); import config;\n"
                "print(config.SECRET_SOURCE, config.CLIENT_SECRET == %r)"
                % (MCP, self.SECRET))
        out = subprocess.run([sys.executable, "-c", code], env=self.env,
                             stdout=subprocess.PIPE, check=True)
        self.assertEqual(out.stdout.decode().strip(), "secret_cmd True")

    def test_show_and_remove_do_not_crash(self):
        self._run("--stdin", stdin=self.SECRET)
        self.assertEqual(self._run("--show").returncode, 0)
        self.assertEqual(self._run("--remove").returncode, 0)


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
