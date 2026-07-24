# Prisma SASE Plugin Marketplace

Read-only **Prisma SASE / Prisma Access** tools for Claude Desktop (Cowork) and
Claude Code: a Python MCP server (6 query tools) plus the `prisma-sase-ops`
Skill (decision tree, thresholds, runbooks, weekly-report template).
Ask Claude things like *"現在 SASE 狀態如何?有沒有 P1 告警?"* or
*"list tunnel status — which are down?"* against your own tenant.

> **Read-only by design** — no write / commit / config-push path exists anywhere.

## 關於本專案與免責聲明 / About & Disclaimer

**中文** — 本專案作者任職於 Palo Alto Networks,職務為 Solutions Consultant。
這是作者為了向客戶推廣 Prisma SASE、以個人時間開發的 **side project**:
**並非 Palo Alto Networks 官方開發、維護或背書,不代表公司立場;
內容與查詢結果亦不保證正確性、完整性或適用性** —— 使用前請自行評估,
重要決策請以官方文件與官方支援管道為準。本專案以開源方式發佈
(MIT License,見 [LICENSE](LICENSE)),歡迎透過 GitHub Issues / PR
提出任何意見與回饋,也歡迎**無償**引用、修改與再利用。

**English** — The author works at Palo Alto Networks as a Solutions
Consultant. This is a personal **side project** built on personal time to
help introduce Prisma SASE to customers. **It is not developed, maintained,
or endorsed by Palo Alto Networks and does not represent the company; no
guarantee is made as to the correctness, completeness, or fitness of its
content or query results** — evaluate before use, and rely on official
documentation and support channels for important decisions. The project is
open source under the [MIT License](LICENSE); feedback and contributions
are welcome via GitHub Issues / PRs, and everyone is free to use, modify,
and reference it at no cost.

*Palo Alto Networks、Prisma 及相關標誌為 Palo Alto Networks, Inc. 之商標。
Palo Alto Networks, Prisma, and related marks are trademarks of
Palo Alto Networks, Inc.*

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
