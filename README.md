# Prisma SASE Plugin Marketplace

Read-only **Prisma SASE / Prisma Access** tools for Claude Desktop (Cowork) and
Claude Code: a Python MCP server (6 query tools) plus the `prisma-sase-ops`
Skill (decision tree, thresholds, runbooks, weekly-report template).
Ask Claude things like *"現在 SASE 狀態如何?有沒有 P1 告警?"* or
*"list tunnel status — which are down?"* against your own tenant.

> **Read-only by design** — no write / commit / config-push path exists anywhere.

This repo is a **plugin marketplace**: one code tree (`plugin/`), three OS-specific
catalog entries that differ only in how the server is launched. Install the one for
your OS:

| Your OS | Install this plugin | Launcher |
|---|---|---|
| macOS | **`prisma-sase-mac`** | `bash mcp/run.sh` |
| Linux | **`prisma-sase-linux`** | `bash mcp/run.sh` |
| Windows | **`prisma-sase-windows`** | `cmd /c mcp\run.cmd` |

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

## Private repository notes

Manual add/update uses your normal git credentials (`gh auth login` /
`gh auth setup-git`, SSH agent). Background auto-update of **private** repos
over HTTPS is limited by design; for a smooth private-marketplace experience:

- run `gh auth setup-git` once on each machine, and
- set `CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE=1` so a failed background
  pull keeps the working copy (manual update still works normally).

SSH remotes with a loaded `ssh-agent` key auto-update fine.

## Repo layout

```
.claude-plugin/marketplace.json   # catalog: 2 entries, shared source, per-OS launcher
plugin/                           # the single code tree (server + skills + installers)
tools/build-standalone.py         # optional: build offline .plugin files (file-upload installs)
PUBLISHING.md                     # maintainer release workflow
```

Standalone `.plugin` files (for machines without git access) can still be built
any time: `python3 tools/build-standalone.py` → `dist/`.
