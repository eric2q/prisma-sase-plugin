#!/usr/bin/env python3
"""Build the standalone .plugin file (file-upload install) from plugin/.

Since 0.9.0 the plugin ships the Skill and nothing else -- the MCP server is
installed separately via uvx, so there is no launcher to vary and no per-OS
build. What used to be three zips differing only in their `mcpServers` block
is now one zip that runs anywhere.

The zip is for hosts that cannot reach the GitHub marketplace. Everyone else
should add the marketplace, because the plugin cache is version-pinned and a
zip install goes stale the moment you build it.

Usage:  python3 tools/build-standalone.py
"""
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(ROOT, "plugin")
MCP_DIR = os.path.join(ROOT, "src", "prisma_sase_mcp")
DIST = os.path.join(ROOT, "dist")

PLUGIN_NAME = "prisma-sase"

EXCLUDE_DIRS = {"__pycache__", ".git"}
EXCLUDE_SUFFIX = (".pyc", ".DS_Store")


def tree_files():
    for base, dirs, files in os.walk(PLUGIN_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            if f.endswith(EXCLUDE_SUFFIX):
                continue
            full = os.path.join(base, f)
            yield full, os.path.relpath(full, PLUGIN_DIR)


def _check_version_sync(market):
    """Fail if the version drifts between its four declaration points.

    Since 0.8.7 the plugin entry carries no version of its own: Claude Code
    always prefers plugin.json's value, so an entry version can only go stale
    unnoticed. The four that must agree are plugin.json (what the host reads),
    config.PLUGIN_VERSION (what the server reports), marketplace metadata, and
    -- since 0.9.0 -- pyproject.toml, which is what uvx actually builds.
    """
    with open(os.path.join(MCP_DIR, "config.py"), encoding="utf-8") as fh:
        m = re.search(r'^PLUGIN_VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
    code_ver = m.group(1) if m else None

    manifest_path = os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json")
    if not os.path.exists(manifest_path):
        sys.exit("ERROR: %s is missing -- without it the Skill has no manifest "
                 "and neither install path can load it."
                 % os.path.relpath(manifest_path, ROOT))
    with open(manifest_path, encoding="utf-8") as fh:
        manifest_ver = json.load(fh).get("version")

    with open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8") as fh:
        m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
    proj_ver = m.group(1) if m else None

    meta_ver = market.get("metadata", {}).get("version")
    if len({code_ver, manifest_ver, meta_ver, proj_ver}) != 1:
        sys.exit("ERROR: version mismatch -- config.PLUGIN_VERSION=%s, "
                 "plugin.json=%s, marketplace metadata=%s, pyproject=%s. Bump "
                 "them in lockstep (see PUBLISHING.md)."
                 % (code_ver, manifest_ver, meta_ver, proj_ver))

    stale = sorted(p["name"] for p in market["plugins"] if "version" in p)
    if stale:
        sys.exit("ERROR: %s declare their own version. plugin.json always "
                 "wins, so an entry version can only drift out of sight -- "
                 "remove it (see PUBLISHING.md)." % ", ".join(stale))


def _check_no_server_declared(market, manifest):
    """Fail if anything reintroduces an MCP server into the plugin.

    0.9.0 split the two halves apart: the plugin is a Skill, the server is a
    Local MCP entry that uvx keeps current. A `mcpServers` block here would
    quietly launch a *second*, version-pinned copy of the server alongside the
    uvx one -- two servers claiming the same tool names, one of them stale.
    """
    for where, obj in (("plugin.json", manifest),) + tuple(
            ("marketplace entry '%s'" % p["name"], p) for p in market["plugins"]):
        for key in ("mcpServers", "userConfig"):
            if key in obj:
                sys.exit("ERROR: %s declares %s. Since 0.9.0 the plugin ships "
                         "the Skill only -- the server installs via uvx as a "
                         "Local MCP entry. Remove it." % (where, key))


def main():
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"),
              encoding="utf-8") as fh:
        market = json.load(fh)
    _check_version_sync(market)

    with open(os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json"),
              encoding="utf-8") as fh:
        manifest = json.load(fh)
    _check_no_server_declared(market, manifest)

    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, "%s.plugin" % PLUGIN_NAME)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for full, rel in tree_files():
            zf.write(full, rel)
    print("built %s (v%s)" % (out, manifest["version"]))
    print("note: a zip install cannot update itself. Prefer the marketplace.")


if __name__ == "__main__":
    main()
