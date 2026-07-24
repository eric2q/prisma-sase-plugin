# Prisma SASE Plugin Marketplace

**English** | [繁體中文](README.zh-TW.md)

Read-only **Prisma SASE / Prisma Access** tools for Claude Desktop (Cowork) and
Claude Code: a Python MCP server (6 query tools) plus the `prisma-sase-ops`
Skill (decision tree, thresholds, runbooks, weekly-report template).
Ask Claude things like *"how is SASE doing right now — any P1 alerts?"* or
*"list tunnel status — which are down?"* against your own tenant.

> **Read-only by design** — no write / commit / config-push path exists anywhere.

## About & Disclaimer

The author works at Palo Alto Networks as a Solutions Consultant. This is a
personal **side project** built on personal time to help introduce Prisma SASE
to customers. **It is not developed, maintained, or endorsed by Palo Alto
Networks and does not represent the company; no guarantee is made as to the
correctness, completeness, or fitness of its content or query results** —
evaluate before use, and rely on official documentation and support channels
for important decisions. The project is open source under the
[MIT License](LICENSE); feedback and contributions are welcome via GitHub
Issues / PRs, and everyone is free to use, modify, and reference it at no cost.

*Palo Alto Networks, Prisma, and related marks are trademarks of
Palo Alto Networks, Inc.*

## What's in the box

This repo is a **plugin marketplace**: one code tree (`plugin/`), three OS-specific
catalog entries that differ only in how the server is launched. Install the one for
your OS:

| Your OS | Install this plugin | Launcher |
|---|---|---|
| macOS | **`prisma-sase-mac`** | `bash mcp/run.sh` |
| Linux | **`prisma-sase-linux`** | `bash mcp/run.sh` |
| Windows | **`prisma-sase-windows`** | `cmd /c mcp\run.cmd` |

## Prerequisites

Everything the plugin needs before installing. **Not sure? Just run the install
script (step 1 below)** — it checks all of this and, for anything missing,
prints the exact command to fix it, per OS. It is always safe to re-run.

| You need | How to check | If it's missing |
|---|---|---|
| **Python ≥ 3.10** | `python3 --version` (Windows: `py --version` or `python --version`) | macOS: `brew install python@3.12`, or the [python.org](https://www.python.org/downloads/) installer. Debian/Ubuntu: `sudo apt install python3 python3-venv python3-pip`. Fedora/RHEL: `sudo dnf install python3`. Windows: [python.org](https://www.python.org/downloads/) installer — tick **"Add python.exe to PATH"** |
| **venv + pip** (usually bundled with Python) | `python3 -m venv --help` | Debian/Ubuntu ship them separately: `sudo apt install python3-venv python3-pip`. Elsewhere they come with Python |
| **Network to PyPI** (one-time) | — | Needed once so the install script can fetch `fastmcp` + `httpx`. Behind a corporate proxy: set `HTTPS_PROXY=http://proxy:port` first, then run the script |
| **git** (marketplace install only) | `git --version` | macOS: `xcode-select --install`. Linux: `sudo apt install git` / `sudo dnf install git`. Windows: [git-scm.com](https://git-scm.com/). No git at all? Use the standalone `.plugin` file instead (see [Repo layout](#repo-layout)) |

⚠️ Two known traps the script also detects and explains:
- **macOS**: the built-in `/usr/bin/python3` is often **3.9** — too old. Install
  a newer one; the script finds it automatically.
- **Windows**: if typing `python` opens the **Microsoft Store**, that's an alias
  stub, not Python. Install the real one from python.org (tick "Add to PATH"),
  or disable the alias (Settings → Apps → Advanced app settings → App execution
  aliases).

No Prisma tenant yet? Everything can still be tried offline: set `PRISMA_MOCK=1`
and the tools answer with realistic sample data — no credentials, no network.

## Install

**1. One-time machine setup** (Python ≥ 3.10 + venv + dependencies + credential
template). Clone or download this repo anywhere temporary and run:

```bash
# macOS / Linux
bash plugin/install.sh
```
```bat
:: Windows (Python from python.org first — tick "Add python.exe to PATH")
plugin\install.bat
```

**2. Add the marketplace + install the plugin.**

*Claude Desktop / Cowork:* **Settings → Plugins → Add marketplace → Add from a
repository** → enter this repo (`eric2q/prisma-sase-plugin` or the full git URL) → install
**prisma-sase-mac**, **prisma-sase-linux**, or **prisma-sase-windows** to match your OS.

*Claude Code (CLI):*

```
/plugin marketplace add eric2q/prisma-sase-plugin
/plugin install prisma-sase-mac@prisma-sase      # macOS
/plugin install prisma-sase-linux@prisma-sase    # Linux
/plugin install prisma-sase-windows@prisma-sase  # Windows
```

**3. Credentials** — fill in `~/.prisma-sase.env` (Windows:
`%USERPROFILE%\.prisma-sase.env`; the template was created by the install
script). Four values: `PRISMA_CLIENT_ID`, `PRISMA_CLIENT_SECRET`,
`PRISMA_TSG_ID`, `PRISMA_REGION`. Restart the Claude app. Full details,
service-account creation walkthrough, selfcheck and troubleshooting:
[`plugin/README.md`](plugin/README.md).

## Update

Maintainer pushes to this repo → users pick it up with
**Settings → Plugins → (marketplace) Update** in Desktop, or:

```
/plugin marketplace update prisma-sase
```

Claude Code also refreshes marketplaces in the background. Versions are pinned
by the `version` field in `.claude-plugin/marketplace.json` — users see an
update when it changes (see [`PUBLISHING.md`](PUBLISHING.md)).

## Notes on hosting

This repository is **public** — anyone can add the marketplace and install
without GitHub authentication, and background auto-updates just work.

If you fork and host this as a **private** repo instead: manual add/update
uses your normal git credentials (`gh auth setup-git`, SSH agent), but
background auto-update of private repos over HTTPS is limited by design —
run `gh auth setup-git` on each machine and set
`CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE=1` so a failed background
pull keeps the working copy. SSH remotes with a loaded `ssh-agent` key
auto-update fine.

## Repo layout

```
.claude-plugin/marketplace.json   # catalog: 3 OS-specific entries, shared source, per-OS launcher
plugin/                           # the single code tree (server + skills + installers)
tools/build-standalone.py         # optional: build offline .plugin files (file-upload installs)
PUBLISHING.md                     # maintainer release workflow
README.zh-TW.md                   # this page in Traditional Chinese
```

Standalone `.plugin` files (for machines without git access) can still be built
any time: `python3 tools/build-standalone.py` → `dist/`.
