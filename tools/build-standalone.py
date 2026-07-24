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
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(ROOT, "plugin")
DIST = os.path.join(ROOT, "dist")

MCP_CONFIGS = {
    "prisma-sase": {
        "mcpServers": {"prisma-sase": {
            "command": "bash",
            "args": ["${CLAUDE_PLUGIN_ROOT}/mcp/run.sh"]}}},
    "prisma-sase-windows": {
        "mcpServers": {"prisma-sase": {
            "command": "cmd",
            "args": ["/c", "${CLAUDE_PLUGIN_ROOT}\\mcp\\run.cmd"]}}},
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


def main():
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"),
              encoding="utf-8") as fh:
        market = json.load(fh)
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
