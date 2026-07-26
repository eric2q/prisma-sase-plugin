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

Curious how the 6 tools map onto PANW's full API surface (and what a read-only
Phase 2 could add)? See the
[Prisma SASE API catalog](plugin/skills/prisma-sase-ops/references/api-catalog.md).

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

**3. Credentials — create the API key** (walkthrough below), then provide the
four values. **Enabling the plugin prompts for them** — in Claude Desktop and
in the Claude Code CLI alike (the Client Secret is masked and goes to secure
storage, not `settings.json`). Use that. The `~/.prisma-sase.env` file
(Windows: `%USERPROFILE%\.prisma-sase.env`; template created by the install
script) is the fallback for cloud sessions, CI, and hosts without the dialog
— and stays the place for the optional tuning variables the dialog doesn't
cover. Restart the Claude app afterwards. Full details, selfcheck and troubleshooting:
[`plugin/README.md`](plugin/README.md).

## Getting the API key (read-only service account)

Prisma SASE's "API key" is a **service account's Client ID + Client Secret**,
created in **Strata Cloud Manager (SCM)** in four steps. This plugin only
needs a **view-only** role — that is both a security requirement and a design
guarantee (the tool layer has no write path at all).

> The figures are schematic redrawings of an actual walkthrough (layout,
> fields, and warnings faithful to the original screens); tenant identifiers
> are masked. The red badges number the flow end-to-end: ① gear → ② IAM →
> ③ name → ④ Client ID → ⑤ Client Secret.

**Step 1 — open Identity & Access Management.** In SCM, click the gear icon
(**System Settings**, ①) at the bottom of the left menu → **Identity & Access
Management** (②) → **Add Identity**. A three-page wizard opens
(Identity Information → Client Credentials → Assign Roles).

<img src="plugin/docs/images/scm-1-iam-menu.png" alt="SCM left menu: ① System Settings gear → ② Identity & Access Management" width="420">

**Step 2 — Identity Information.** Identity Type = **Service Account**; pick a
recognizable Service Account Name (③, e.g. `apikey` or `claude-mcp-readonly` —
it becomes the Client ID prefix); Contact and Description are optional → **Next**.

<img src="plugin/docs/images/scm-2-identity-info.png" alt="Add New Identity — Identity Information: Identity Type = Service Account, ③ name" width="640">

**Step 3 — Client Credentials (the critical one).** The system generates the
two values on the spot: **Client ID** (④) and **Client Secret** (⑤).

⚠️ **The Client Secret is shown only this once** — the screen itself warns
*"Please save the Client Secret, you will not be able to copy it after saving
the new identity."* Copy it immediately (or **Download CSV File** — it contains
the secret; store it in a password manager, then delete the file). If it's
lost, the only fix is to regenerate (rotate) the secret for this account and
update the env file. No separate TSG lookup is needed: **the digits after `@`
in the Client ID are the TSG ID.** → **Next**.

<img src="plugin/docs/images/scm-3-client-credentials.png" alt="Client Credentials: ④ Client ID (digits after @ are the TSG ID), ⑤ Client Secret (shown once; Download CSV File)" width="640">

**Step 4 — Assign Roles (required despite the "Optional" label).** A service
account with no role has **no permissions** — the plugin would get HTTP 403.
Apps & Services = **All Apps & Services**, Role = **View Only Administrator** →
**Submit**. View Only Administrator covers every feature of this plugin; do
**not** grant Superuser or any writable role (least privilege). Narrower roles
exist (e.g. ADEM Tier 1 Support, Multitenant Monitor User) but do not cover
both the Insights and ADEM APIs — View Only Administrator is the confirmed
right-sized choice. In multi-tenant (MSP) environments, create the identity
under the correct TSG scope and bind only the tenants you need.

<img src="plugin/docs/images/scm-4-assign-roles.png" alt="Assign Roles: All Apps & Services + View Only Administrator → Submit" width="640">

**Provide the values from step 3** — two supported paths:

- **Plugin enable dialog (recommended):** when you install/enable the plugin,
  Claude prompts for Client ID, Client Secret, TSG ID, and Region — this
  works in Claude Desktop and in the Claude Code CLI. The secret is masked
  on entry and stored in **secure storage** (macOS Keychain, or
  `~/.claude/.credentials.json` where no keychain is available), not in
  `settings.json` and not in any file of ours.
- **Env file** (`~/.prisma-sase.env`, `KEY=VALUE`, no quotes; masked here
  with asterisks) — the fallback for cloud sessions, CI, or hosts without
  the dialog:

  ```
  PRISMA_CLIENT_ID=apikey@**********.iam.panserviceaccount.com
  PRISMA_CLIENT_SECRET=********************************
  PRISMA_TSG_ID=**********
  PRISMA_REGION=sg
  ```

  The secret line can instead point at a secret store, keeping the file
  non-sensitive: `PRISMA_SECRET_CMD=security find-generic-password -s
  prisma-sase -w` (also works with `secret-tool`, `pass`, `op read`).

`PRISMA_TSG_ID` = the digits after `@` in the Client ID; `PRISMA_REGION` =
your tenant's actual region (e.g. `sg`, `us`, `de`). Then restart the Claude
app and (optionally) verify with the server's `--selfcheck` — it reports
which source supplied the secret.

**Storage principle:** credentials live in exactly one of the supported
homes — the OS secure storage (via the enable dialog / `PRISMA_SECRET_CMD`)
or the local env file (`chmod 600`) — and nowhere else. Never commit them to
a repo, never keep copies in project folders, and never paste the secret
anywhere — for cloud sessions, use a temporary staged copy and delete it
afterwards (see [`plugin/README.md`](plugin/README.md), "Cloud sessions").

> ⚠️ **Never paste the Client Secret into a chat, message window, or document.**
> The tools deliberately take no credential parameters — credentials only ever
> enter the local env file. If the secret ever leaks, rotate it in SCM
> immediately and update the env file.

## If the SASE tools don't appear

Two things to try, in order — both designed for the case where the plugin
looks installed but no Prisma SASE tools exist in the conversation:

1. **Ask Claude to run `prisma_sase_setup_required`.** When the real server
   can't start, a dependency-free fallback takes its place and this tool
   returns the diagnosis plus copy-paste fix commands.
2. **Read `~/.prisma-sase-launch.log`** — the launch breadcrumb naming the
   interpreter that was chosen and the exact cause of failure (no file at all
   = the host never launched the server). Line-by-line key:
   [`plugin/README.md`](plugin/README.md#if-the-tools-dont-show-up-two-places-to-look).

After any fix, **restart the Claude app completely** (macOS: ⌘Q — closing the
window doesn't relaunch plugin servers).

## Update

Maintainer pushes to this repo → users pick it up with
**Settings → Plugins → (marketplace) Update** in Desktop, or:

```
/plugin marketplace update prisma-sase
```

Claude Code also refreshes marketplaces in the background. Versions are pinned
by the `version` field in `.claude-plugin/marketplace.json` — users see an
update when it changes (see [`PUBLISHING.md`](PUBLISHING.md)).

**What changed in each version** — bug fixes, new features, behavior changes —
is recorded per release in [`plugin/CHANGELOG.md`](plugin/CHANGELOG.md)
(entries are tagged `FIX` / `NEW` / `CHG`).

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
plugin/CHANGELOG.md               # version history: bug fixes & new features per release
tools/build-standalone.py         # optional: build offline .plugin files (file-upload installs)
PUBLISHING.md                     # maintainer release workflow
README.zh-TW.md                   # this page in Traditional Chinese
```

Standalone `.plugin` files (for machines without git access) can still be built
any time: `python3 tools/build-standalone.py` → `dist/`.
