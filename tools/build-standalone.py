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

# Since v0.8.0 the launcher config (incl. the userConfig env substitutions)
# is taken verbatim from each marketplace entry -- one source of truth, the
# two install paths cannot drift.
PLUGIN_NAMES = ("prisma-sase-mac", "prisma-sase-linux", "prisma-sase-windows")

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
    """Fail if the version drifts between its three declaration points.

    Since 0.8.7 the plugin entries carry no version of their own: Claude Code
    always prefers plugin.json's value, so an entry version can only go stale
    unnoticed. The three that must agree are plugin.json (what the host reads),
    config.PLUGIN_VERSION (what the server reports), and marketplace metadata.
    """
    cfg = os.path.join(PLUGIN_DIR, "mcp", "config.py")
    with open(cfg, encoding="utf-8") as fh:
        m = re.search(r'^PLUGIN_VERSION\s*=\s*"([^"]+)"', fh.read(), re.M)
    code_ver = m.group(1) if m else None

    manifest_path = os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json")
    if not os.path.exists(manifest_path):
        sys.exit("ERROR: %s is missing. Without it a sideloaded session "
                 "(--plugin-dir) sees no userConfig and the credential "
                 "placeholders never bind (see CHANGELOG 0.8.7)."
                 % os.path.relpath(manifest_path, ROOT))
    with open(manifest_path, encoding="utf-8") as fh:
        manifest_ver = json.load(fh).get("version")

    meta_ver = market.get("metadata", {}).get("version")
    if len({code_ver, manifest_ver, meta_ver}) != 1:
        sys.exit("ERROR: version mismatch -- config.PLUGIN_VERSION=%s, "
                 "plugin.json=%s, marketplace metadata=%s. Bump them in "
                 "lockstep (see PUBLISHING.md)."
                 % (code_ver, manifest_ver, meta_ver))

    stale = sorted(p["name"] for p in market["plugins"] if "version" in p)
    if stale:
        sys.exit("ERROR: %s declare their own version. plugin.json always "
                 "wins, so an entry version can only drift out of sight -- "
                 "remove it (see PUBLISHING.md)." % ", ".join(stale))


# Fields that legitimately differ between the three catalog entries. name/
# description/keywords are per-OS presentation; mcpServers carries the per-OS
# launcher (with the extra invariant that mac and linux share the bash one).
_ENTRY_DIFF_ALLOWED = {"name", "description", "keywords", "mcpServers"}


def _check_entry_sync(market):
    """Fail if the three catalog entries drift outside the allowed fields.

    The three entries are ONE plugin presented per-OS: everything except the
    allowed presentation/launcher fields must be byte-identical. Since 0.8.7
    mac and linux carry no mcpServers at all -- they inherit the bash launcher
    from plugin.json, so there is nothing left to drift between them. Only
    Windows overrides it. This turns the 'keep the entries in lockstep' rule
    from human discipline into a build failure.
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
    for name in ("prisma-sase-mac", "prisma-sase-linux"):
        if "mcpServers" in entries[name]:
            sys.exit("ERROR: '%s' overrides mcpServers. Only Windows needs a "
                     "launcher override; mac and linux must inherit the bash "
                     "one from plugin.json so both load paths agree." % name)
    if "mcpServers" not in entries["prisma-sase-windows"]:
        sys.exit("ERROR: prisma-sase-windows must override mcpServers -- bash "
                 "does not exist there, so inheriting the manifest launcher "
                 "would leave Windows users with a server that cannot start.")


def main():
    with open(os.path.join(ROOT, ".claude-plugin", "marketplace.json"),
              encoding="utf-8") as fh:
        market = json.load(fh)
    _check_version_sync(market)
    _check_entry_sync(market)
    entries = {p["name"]: p for p in market["plugins"]}

    with open(os.path.join(PLUGIN_DIR, ".claude-plugin", "plugin.json"),
              encoding="utf-8") as fh:
        base_manifest = json.load(fh)

    os.makedirs(DIST, exist_ok=True)
    for name in PLUGIN_NAMES:
        entry = entries[name]
        # Start from the real manifest so the bundle carries the same
        # userConfig (and therefore the same credential binding) as both the
        # marketplace and --plugin-dir paths; overlay only per-OS presentation
        # and, for Windows, the launcher.
        manifest = dict(base_manifest)
        manifest["name"] = name
        manifest["description"] = entry.get("description",
                                            base_manifest.get("description", ""))
        manifest["keywords"] = entry.get("keywords",
                                         base_manifest.get("keywords", []))
        mcp_cfg = {"mcpServers": entry.get("mcpServers",
                                           base_manifest["mcpServers"])}
        manifest["mcpServers"] = mcp_cfg["mcpServers"]
        out = os.path.join(DIST, "%s.plugin" % name)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
            for full, rel in tree_files():
                if rel.replace(os.sep, "/") == ".claude-plugin/plugin.json":
                    continue          # replaced by the per-OS manifest below
                zf.write(full, rel)
            zf.writestr(".claude-plugin/plugin.json",
                        json.dumps(manifest, indent=2, ensure_ascii=False))
            zf.writestr(".mcp.json",
                        json.dumps(mcp_cfg, indent=2))
        print("built %s (v%s)" % (out, manifest["version"]))


if __name__ == "__main__":
    main()
