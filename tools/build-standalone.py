#!/usr/bin/env python3
"""Build standalone .plugin files (file-upload installs) from the marketplace tree.

The marketplace flow needs neither .mcp.json nor plugin.json inside plugin/
(the catalog entries own them). Machines without git access still need the
classic zip packages, so this script generates the per-OS manifests on the fly
-- reading name/version/description from .claude-plugin/marketplace.json so the
two distribution paths can never drift -- and zips plugin/ into dist/.

Usage:  python3 tools/build-standalone.py
"""
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(ROOT, "plugin")
DIST = os.path.join(ROOT, "dist")

_BASH = {"mcpServers": {"prisma-sase": {
    "command": "bash", "args": ["${CLAUDE_PLUGIN_ROOT}/mcp/run.sh"]}}}
_CMD = {"mcpServers": {"prisma-sase": {
    "command": "cmd", "args": ["/c", "${CLAUDE_PLUGIN_ROOT}\\mcp\\run.cmd"]}}}
MCP_CONFIGS = {
    "prisma-sase-mac": _BASH,
    "prisma-sase-linux": _BASH,
    "prisma-sase-windows": _CMD,
}

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
    """Fail if config.PLUGIN_VERSION drifts from marketplace.json versions."""
    cfg = os.path.join(PLUGIN_DIR, "mcp", "config.py")
    with open(cfg, encoding="utf-8") as fh:
        m = re.search(r'^PLUGIN_VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
    code_ver = m.group(1) if m else None
    market_vers = {p.get("version") for p in market["plugins"]}
    market_vers.add(market.get("metadata", {}).get("version"))
    if len(market_vers) != 1 or code_ver not in market_vers:
        sys.exit("ERROR: version mismatch -- config.PLUGIN_VERSION=%s but "
                 "marketplace.json carries %s. Bump them in lockstep "
                 "(see PUBLISHING.md)." % (code_ver, sorted(market_vers)))


# Fields that legitimately differ between the three catalog entries. name/
# description/keywords are per-OS presentation; mcpServers carries the per-OS
# launcher (with the extra invariant that mac and linux share the bash one).
_ENTRY_DIFF_ALLOWED = {"name", "description", "keywords", "mcpServers"}


def _check_entry_sync(market):
    """Fail if the three catalog entries drift outside the allowed fields.

    The three entries are ONE plugin presented per-OS: everything except the
    allowed presentation/launcher fields must be byte-identical, and the
    mac/linux entries must share an identical bash launcher. This turns the
    'keep the entries in lockstep' rule from human discipline into a build
    failure -- important before any future field (e.g. userConfig) lands in
    all three.
    """
    entries = {p["name"]: p for p in market["plugins"]}
    expected = {"prisma-sase-mac", "prisma-sase-linux", "prisma-sase-windows"}
    if set(entries) != expected:
        sys.exit("ERROR: marketplace entries %s != expected %s"
                 % (sorted(entries), sorted(expected)))

    def core(entry):
        return {k: v for k, v in entry.items() if k not in _ENTRY_DIFF_ALLOWED}

    ref_name = "prisma-sase-mac"
    for name in ("prisma-sase-linux", "prisma-sase-windows"):
        if core(entries[name]) != core(entries[ref_name]):
            diff_keys = sorted(
                k for k in set(core(entries[name])) | set(core(entries[ref_name]))
                if core(entries[name]).get(k) != core(entries[ref_name]).get(k))
            sys.exit("ERROR: catalog entry '%s' drifted from '%s' on field(s) "
                     "%s -- entries must stay in lockstep outside %s "
                     "(see PUBLISHING.md)."
                     % (name, ref_name, diff_keys, sorted(_ENTRY_DIFF_ALLOWED)))
    if entries["prisma-sase-mac"]["mcpServers"] != entries["prisma-sase-linux"]["mcpServers"]:
        sys.exit("ERROR: prisma-sase-mac and prisma-sase-linux must share an "
                 "identical bash launcher (mcpServers differs).")


def main():
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"),
              encoding="utf-8") as fh:
        market = json.load(fh)
    _check_version_sync(market)
    _check_entry_sync(market)
    entries = {p["name"]: p for p in market["plugins"]}

    os.makedirs(DIST, exist_ok=True)
    for name, mcp_cfg in MCP_CONFIGS.items():
        entry = entries[name]
        manifest = {
            "name": name,
            "version": entry.get("version", "0.0.0"),
            "description": entry.get("description", ""),
            "author": entry.get("author", {}),
            "keywords": entry.get("keywords", []),
        }
        out = os.path.join(DIST, "%s.plugin" % name)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for full, rel in tree_files():
                zf.write(full, rel)
            zf.writestr(".claude-plugin/plugin.json",
                        json.dumps(manifest, indent=2, ensure_ascii=False))
            zf.writestr(".mcp.json",
                        json.dumps(mcp_cfg, indent=2))
        print("built %s (v%s)" % (out, manifest["version"]))


if __name__ == "__main__":
    main()
