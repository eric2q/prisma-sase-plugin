# Prisma SASE for Claude

**English** | [繁體中文](README.zh-TW.md)

Read-only **Prisma SASE / Prisma Access** tools for Claude Desktop (Cowork) and
Claude Code: a Python MCP server (6 query tools) plus the `prisma-sase-ops`
Skill (decision tree, thresholds, runbooks, weekly-report template).
Ask Claude things like *"how is SASE doing right now — any P1 alerts?"* or
*"list tunnel status — which are down?"* against your own tenant.

## Installation

Four steps, in this order — environment, credentials, server, Skill:

| | Step | What it is |
|---|---|---|
| **1** | [Prerequisites](#1-prerequisites) | `uv` and `git` — two commands, one check |
| **2** | [Get the API key](#2-get-the-api-key) | A read-only SCM service account |
| **3** | [Run the guided setup](#3-run-the-guided-setup) | One command: installs the server *and* stores the credentials |
| **4** | [Add the Skill](#4-add-the-skill-optional) | Optional — runbooks and the report template |

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

Two parts, installed separately:

| Part | What it is | How it installs | How it updates |
|---|---|---|---|
| **MCP server** | 6 read-only query tools | a **Local MCP server** entry that runs `uvx` | automatically, on every app launch |
| **`prisma-sase-ops` Skill** | decision tree, thresholds, runbooks, weekly-report template | the plugin marketplace | `/plugin marketplace update prisma-sase` |

The server works on its own. The Skill is optional and makes Claude better at
choosing between the tools and reading what they return.

How the 6 tools map onto PANW's full API surface, and what a read-only Phase 2
could add:
[Prisma SASE API catalog](plugin/skills/prisma-sase-ops/references/api-catalog.md).

## 1. Prerequisites

Install **both `uv` and `git`** before anything else.

**macOS**

```bash
brew install uv git
```

**Windows** (PowerShell), then **open a new terminal** so `PATH` is re-read:

```powershell
winget install astral-sh.uv
```

```powershell
winget install Git.Git
```

**Linux** — `curl -LsSf https://astral.sh/uv/install.sh | sh` for uv, and git
from your package manager.

**Then confirm both answer:**

```bash
uvx --version && git --version
```

Two version lines means you are ready. **Python is not required** — uv supplies
its own interpreter when the system one is too old (macOS ships 3.9;
`fastmcp` needs 3.10).

<details>
<summary>Why each one, and what it looks like when it is missing</summary>

| You need | Why | Missing looks like |
|---|---|---|
| **uv** (provides `uvx`) | The launcher for everything below, on every OS. Also supplies the Python interpreter | `uvx: command not found` in your terminal — or, if the app was already configured, an MCP server that silently never starts |
| **git** | Every command here installs `--from git+https://…`, and uv shells out to git to resolve the ref and fetch the source | uv stops at *"Git executable not found"*. Required at **install** time only; once the version is cached, launches no longer call git |
| **Network to GitHub + PyPI** | uvx fetches this repo and its dependencies on first launch, and re-checks the ref on **every** launch. Behind a corporate proxy, set `HTTPS_PROXY=http://proxy:port` | *"Failed to resolve"* / *"Git operation failed"* after an `Updating … (HEAD)` line. A warm cache does not avoid this — see [Working offline](#working-offline) |
| **A read-only SCM service account** | The Client ID / Secret / TSG the tools authenticate with | That is [step 2](#2-get-the-api-key), not needed for step 1 |

Full uv install options: [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/).
On macOS `xcode-select --install` also provides git if you would rather not use
Homebrew.

</details>

**No Prisma tenant yet?** Set `PRISMA_MOCK=1` and the tools answer with
realistic sample data — no credentials, no network.

**Running without a network** takes one extra step, because the server
re-resolves the git ref on every launch. See
[Working offline](#working-offline), under Update.

## 2. Get the API key

Prisma SASE's "API key" is a **service account's Client ID + Client Secret**,
created in Strata Cloud Manager. Follow the illustrated four-step walkthrough
[further down](#the-api-key-walkthrough-read-only-service-account) and keep both
values to hand — step 3 asks for them, and the Client Secret is shown **only
once**, at creation.

## 3. Run the guided setup

One command installs the server and stores the credentials. It asks for the
four values with an explanation of each, puts the Client Secret in your OS
keychain, and writes the Local MCP servers entry:

```bash
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
```

> **On ARM64 Windows, add two flags** — `uvx --managed-python --python
> cpython-3.12-windows-x86_64 --from … prisma-sase-setup`. A transitive
> dependency publishes no `win_arm64` wheel, so a native interpreter tries to
> compile it and fails on a missing Rust toolchain. The wizard carries the
> flags into the entry it writes, so this is the only command you type them
> into. Detail: [Windows on ARM](plugin/README.md#windows-on-arm).

It shows the entry and asks before writing anything. To paste it into
**Settings → Extensions → Local MCP servers** yourself instead, use `--print`,
which prints the JSON and writes nothing. The entry it produces:

```json
{
  "command": "/opt/homebrew/bin/uvx",
  "args": ["--from", "git+https://github.com/eric2q/prisma-sase-plugin",
           "prisma-sase-mcp"],
  "env": {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "PRISMA_CLIENT_ID": "apikey@**********.iam.panserviceaccount.com",
    "PRISMA_TSG_ID": "**********",
    "PRISMA_REGION": "sg",
    "PRISMA_SECRET_CMD": "security find-generic-password -s prisma-sase -a client_secret -w"
  }
}
```

The secret itself is not in there. `PRISMA_SECRET_CMD` fetches it from the
keychain at launch. Panel values are stored in plaintext in
`claude_desktop_config.json`, which is included in Time Machine and any backup
that copies your home directory — so the secret stays out of it.

**Then restart the Claude app completely** (macOS: ⌘Q — closing the window does
not relaunch MCP servers) and ask it about your tenant. The tools now work.

## 4. Add the Skill (optional)

The Skill adds the judgement around the tools — which one to reach for, what
the numbers mean, the diagnostic runbooks and the weekly-report template:

*Claude Desktop / Cowork:* **Settings → Plugins → Add marketplace → Add from a
repository** → `eric2q/prisma-sase-plugin` → install **prisma-sase**.

*Claude Code (CLI):*

```
/plugin marketplace add eric2q/prisma-sase-plugin
/plugin install prisma-sase@prisma-sase
```

> **`Plugin "prisma-sase" not found in marketplace "prisma-sase"`?** You added
> this marketplace before 0.9.0, so the local clone still lists the old
> `prisma-sase-mac` / `-windows` / `-linux` entries. `marketplace add` does
> nothing when the clone already exists, so it never refreshes. Update it, then
> install:
>
> ```
> /plugin marketplace update prisma-sase
> ```
>
> Also uninstall the old entry — it mounts an MCP server of its own, which
> duplicates the Local MCP one from step 3:
>
> ```
> /plugin uninstall prisma-sase-mac@prisma-sase
> ```

> **No uv, and cannot install it?** There is a venv fallback that needs only
> Python ≥ 3.10: clone the repo and run `bash src/prisma_sase_mcp/install.sh`
> (Windows: `src\prisma_sase_mcp\install.bat`), then point a Local MCP entry at
> `run.sh`. It works identically but does **not** auto-update — you pull the
> repo yourself. Details in [`plugin/README.md`](plugin/README.md).

## The API key walkthrough (read-only service account)

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

**Provide the values from step 3** — three supported paths, best first:

- **`prisma-sase-setup` (recommended):** the guided setup,
  [step 3](#3-run-the-guided-setup). Secret to the OS keychain, the other three
  onto the Local MCP entry, and a `PRISMA_SECRET_CMD` that fetches the secret at
  launch. Nothing secret is written to a file.
- **The Local MCP servers panel, by hand:** the same four as environment
  variables. Note that `PRISMA_CLIENT_SECRET` then sits in
  `claude_desktop_config.json` in plaintext — acceptable for a lab tenant, less
  so for a customer's.
- **Env file** (`~/.prisma-sase.env`, `KEY=VALUE`, no quotes; masked here
  with asterisks) — for the venv fallback path, cloud sessions and CI:

  ```
  PRISMA_CLIENT_ID=apikey@**********.iam.panserviceaccount.com
  PRISMA_CLIENT_SECRET=********************************
  PRISMA_TSG_ID=**********
  PRISMA_REGION=sg
  ```

  The secret line can instead point at a secret store, keeping the file
  non-sensitive: `PRISMA_SECRET_CMD=security find-generic-password -s
  prisma-sase -a client_secret -w` (also works with `secret-tool`, `pass`,
  `op read`).

`PRISMA_TSG_ID` = the digits after `@` in the Client ID (the setup wizard
detects it for you); `PRISMA_REGION` = your tenant's actual region (e.g. `sg`,
`us`, `de`). Then restart the Claude app. To check what is stored without
revealing it: `uvx --from git+https://github.com/eric2q/prisma-sase-plugin
prisma-sase-setup --show`.

**Storage principle:** credentials live in exactly one of the supported
homes — the OS keychain (via `PRISMA_SECRET_CMD`), the panel entry, or the
local env file (`chmod 600`) — and nowhere else. Never commit them to
a repo, never keep copies in project folders, and never paste the secret
anywhere — for cloud sessions, use a temporary staged copy and delete it
afterwards (see [`plugin/README.md`](plugin/README.md), "Cloud sessions").

> ⚠️ **Never paste the Client Secret into a chat, message window, or document.**
> The tools deliberately take no credential parameters — credentials only ever
> enter the local env file. If the secret ever leaks, rotate it in SCM
> immediately and update the env file.

## If the SASE tools don't appear

Three things to try, in order:

1. **Run the server by hand** — it prints exactly what it found, and no
   credential values:

   ```bash
   uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-mcp --selfcheck
   ```

   A missing `uvx` on `PATH` is the most common cause. The app does not give
   MCP servers a login shell's `PATH`, which is why the generated entry sets
   `PATH` explicitly. If `which uvx` prints a directory not in that list, add it.
2. **Ask Claude to run `prisma_sase_setup_required`.** When the real server
   can't start, a dependency-free fallback takes its place and this tool
   returns the diagnosis plus copy-paste fix commands.
3. **Read `~/.prisma-sase-launch.log`** — the launch breadcrumb naming the
   interpreter that was chosen and the exact cause of failure (no file at all
   = the host never launched the server). Line-by-line key:
   [`plugin/README.md`](plugin/README.md#if-the-tools-dont-show-up).

After any fix, **restart the Claude app completely** (macOS: ⌘Q — closing the
window doesn't relaunch MCP servers).

## Update

**The server updates itself.** The Local MCP entry runs `uvx --from git+…` with
no pinned ref, so every app launch re-resolves this repo's `main` and rebuilds
if the commit changed. Restarting the app is all it takes. To confirm the
version you are running, ask for the SASE status — the response carries
`plugin_version`.

**The Skill does not.** Plugins are cached per version and only move when you
say so:

```
/plugin marketplace update prisma-sase
```

or **Settings → Plugins → (marketplace) Update** in Desktop. Versions are
pinned by the `version` field in `.claude-plugin/marketplace.json` — users see
an update when it changes (see [`PUBLISHING.md`](PUBLISHING.md)).

**What changed in each version** — bug fixes, new features, behavior changes —
is recorded per release in [`plugin/CHANGELOG.md`](plugin/CHANGELOG.md)
(entries are tagged `FIX` / `NEW` / `CHG`).

**Pinning, if you need a stable target.** Add a git ref to the `--from` URL and
the auto-update stops there: `git+https://github.com/eric2q/prisma-sase-plugin@v0.9.2`.
Useful for a customer demo you do not want moving under you.

### Working offline

Because the server re-resolves the git ref on every launch, an unpinned entry
needs network access **each time it starts**, not only on first install. A warm
cache does not change this.

To run without a network — on a plane, or inside a network that blocks GitHub —
pin a **full 40-character commit SHA**:

```
git+https://github.com/eric2q/prisma-sase-plugin@e666ab410338855b4e03044c7f596e6654645f7e
```

**A tag is not enough.** Tags can be moved, so uv still contacts the remote to
check, and `@v0.9.2` fails offline exactly as an unpinned URL does. Only a full
SHA lets uv trust the cache. Warm the cache once while online and the pinned
entry then launches with no connection.

## Notes on hosting

This repository is **public** — `uvx` clones it anonymously, anyone can add the
marketplace without GitHub authentication, and both update paths just work.

If you fork and host this as a **private** repo instead: `uvx` uses your git
credential helper, so `gh auth setup-git` (or an SSH remote with a loaded
`ssh-agent` key, via `git+ssh://git@github.com/...`) is enough for the server.
For the Skill, manual marketplace add/update uses the same credentials, but
background auto-update of private repos over HTTPS is limited by design — set
`CLAUDE_CODE_PLUGIN_KEEP_MARKETPLACE_ON_FAILURE=1` so a failed background pull
keeps the working copy.

## Repo layout

```
src/prisma_sase_mcp/              # the MCP server -- what uvx builds and runs
src/prisma_sase_mcp/setup_wizard.py   # the `prisma-sase-setup` guided installer
src/prisma_sase_mcp/install.sh    # venv fallback for hosts without uv
pyproject.toml                    # entry points: prisma-sase-mcp, prisma-sase-setup
plugin/                           # the Skill
plugin/CHANGELOG.md               # version history: bug fixes & new features per release
.claude-plugin/marketplace.json   # catalog: one entry, the Skill
tools/build-standalone.py         # optional: build an offline .plugin (file-upload install)
PUBLISHING.md                     # maintainer release workflow
README.zh-TW.md                   # this page in Traditional Chinese
```

A standalone `.plugin` file (for machines that cannot reach the marketplace)
can still be built any time: `python3 tools/build-standalone.py` → `dist/`. It
carries the Skill only, and cannot update itself.
