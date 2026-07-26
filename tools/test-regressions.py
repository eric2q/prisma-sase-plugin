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
import re
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


class UserConfigBinding(unittest.TestCase):
    """Every ${user_config.KEY} must resolve against a declared userConfig key.

    0.8.0-0.8.6 declared userConfig in marketplace.json only. A sideloaded
    session (`claude --plugin-dir ./plugin`) reads plugin.json and never sees
    marketplace.json, so all four placeholders stayed literal and the server
    started with no credentials at all. The declaration now lives in the
    manifest; these tests keep it there.
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

    def _placeholders_in(self, blob):
        import json
        return set(self.PLACEHOLDER.findall(json.dumps(blob)))

    def test_manifest_declares_user_config(self):
        """Without this the sideload path has nothing to bind to."""
        self.assertTrue(
            self._manifest().get("userConfig"),
            "plugin.json must declare userConfig -- marketplace.json is not "
            "read when the plugin is loaded with --plugin-dir")

    def test_manifest_placeholders_are_declared(self):
        manifest = self._manifest()
        declared = set(manifest.get("userConfig", {}))
        for key in self._placeholders_in(manifest.get("mcpServers", {})):
            self.assertIn(
                key, declared,
                "manifest uses ${user_config.%s} but does not declare it; it "
                "would reach the server as a literal placeholder" % key)

    def test_marketplace_overrides_bind_to_the_manifest(self):
        """An entry may override mcpServers, but it inherits the declaration."""
        declared = set(self._manifest().get("userConfig", {}))
        for entry in self._marketplace()["plugins"]:
            for key in self._placeholders_in(entry.get("mcpServers", {})):
                self.assertIn(
                    key, declared,
                    "%s uses ${user_config.%s} but the manifest does not "
                    "declare it" % (entry["name"], key))

    def test_every_credential_var_is_wired(self):
        env = self._manifest()["mcpServers"]["prisma-sase"]["env"]
        for var in ("PRISMA_CLIENT_ID", "PRISMA_CLIENT_SECRET",
                    "PRISMA_TSG_ID", "PRISMA_REGION"):
            self.assertIn(var, env, "%s is not passed to the server" % var)

    def test_the_secret_is_marked_sensitive(self):
        """sensitive:true keeps it out of settings.json and in secure storage."""
        spec = self._manifest()["userConfig"]["client_secret"]
        self.assertTrue(
            spec.get("sensitive"),
            "client_secret must be sensitive:true or it lands in plaintext "
            "settings.json")


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

    def test_diagnosis_attributes_the_fault_to_the_host(self):
        result = self._diagnose(self.ENABLED_NO_CONFIG,
                                PRISMA_CLIENT_ID="", PRISMA_CLIENT_SECRET="",
                                PRISMA_TSG_ID="", PRISMA_REGION="sg")
        self.assertIn("HOST issue", result["msg"])
        self.assertIn("enable dialog never collected", result["msg"])
        # It must also offer a way out, not just an attribution.
        self.assertIn(".prisma-sase.env", result["msg"])

    def test_enabled_with_no_config_entry_is_detected(self):
        result = self._diagnose(self.ENABLED_NO_CONFIG)
        self.assertEqual(result["kind"], "never_configured")

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
        """Credentials absent but no settings.json -- not the host's fault."""
        result = self._diagnose(None)
        self.assertIsNone(result["kind"])

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
        self.assertIn("ENABLED but has NO configuration entry", text)
        self.assertIn("expanded_empty", text)

    def test_status_tool_blames_the_host_not_the_tenant(self):
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
        self.assertEqual(result["cns"]["whose_fault"], "host")
        self.assertIn("host configuration problem", result["headline"])


@unittest.skipIf(os.name == "nt", "setup-keychain.sh is POSIX-only")
class KeychainSetupScript(unittest.TestCase):
    """0.8.8 -- the recommended stopgap when the enable dialog is unavailable.

    Its whole point is that the secret never lands in a file, so the test that
    matters is: whatever it writes, the secret is not in it.
    """

    SCRIPT = os.path.join(ROOT, "plugin", "setup-keychain.sh")
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
