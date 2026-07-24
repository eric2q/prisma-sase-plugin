# Prisma SASE plugin (Phase 1 — read-only PoC)

An AI-assistant integration for **Prisma SASE / Prisma Access**: a read-only MCP
server plus the `prisma-sase-ops` Skill, packaged as a single Cowork/Claude
plugin. Ask Claude about tenant health, alerts, tunnel status, connected users,
and ADEM experience scores in natural language.

> **Read-only by design.** Every tool only *queries*. There is no write / commit
> / config-push path anywhere in this plugin (design doc sec.10.1).

### Tools (Phase 1)

| Tool | What it answers |
|---|---|
| `get_sase_status` | One-shot health: alerts by severity, tunnels up/down, connected users, ADEM score |
| `query_alerts` | Alerts by severity / state / time window (paginated) |
| `get_connected_users` | Connected Mobile Users: total, trend, by location |
| `get_user_experience` | ADEM experience score — overall or a named user/app, with LAN/WiFi/DNS/app breakdown |
| `get_remote_networks` | Per-tunnel status rows (RN/SC): up/down, site, throughput; filter `state="down"` |
| `discover_insights` | Diagnostic: probe which Insights resource/view names your tenant actually accepts (read-only) |

These tools sit on 2 of the ~15 Prisma SASE API families PANW publishes
(Insights 3.0 + ADEM). The full landscape — every family on pan.dev, what's
covered today, what's a read-only Phase-2 candidate (Service Status, ADEM app
metrics, Aggregate Monitoring for MSP, SD-WAN monitor, Subscription quotas),
and what the read-only design excludes (all `/sse/config` + push/jobs) — is
catalogued in
[`skills/prisma-sase-ops/references/api-catalog.md`](skills/prisma-sase-ops/references/api-catalog.md).

## Requirements

- **Python ≥ 3.10** (fastmcp's floor). ⚠️ On macOS the built-in `python3` is
  often **3.9** — it will NOT work. `install.sh` handles this for you.
  On Debian/Ubuntu, `venv`/`pip` are separate packages — if missing,
  `install.sh` prints the exact `sudo apt install python3-venv python3-pip`
  fix.
- macOS / Linux (`bash`), or Windows (see the **Windows install** section —
  Windows uses its own package variant `prisma-sase-windows.plugin`).
- A Prisma SASE **read-only** service account (step 3 below).

## Install on Claude Desktop / Cowork

> **Team install (recommended): via the GitHub marketplace.** Add the repo in
> **Settings → Plugins → Add marketplace → Add from a repository**, then
> install `prisma-sase-mac`, `prisma-sase-linux`, or `prisma-sase-windows` (match your OS) —
> updates then arrive with one click. See the repo-root README. The steps
> below (upload from file) remain for machines without git access; machine
> setup (step 1) is required either way.

**Step 1 — run the setup script** (from the unzipped plugin folder):

```bash
bash install.sh
```

It finds a suitable Python (tells you to `brew install python@3.12` if there is
none), creates `~/.prisma-sase-venv`, installs the dependencies, and proves the
server starts with an offline selfcheck. The plugin's launcher (`mcp/run.sh`)
finds this venv automatically — you never edit `.mcp.json`.

**Step 2 — install the plugin file.** In Claude Desktop:
**Settings → Plugins → Upload from file** → pick the variant matching your OS
(`prisma-sase-mac.plugin` / `prisma-sase-linux.plugin` /
`prisma-sase-windows.plugin`, built via `python3 tools/build-standalone.py`).

> ⚠️ Two paths that look right but are NOT an install:
> - **Putting the plugin folder into a Project folder does nothing** — Claude
>   Desktop does not auto-register plugins found in project directories.
> - **"Add marketplace" only accepts git repos/URLs.** You do not need a GitHub
>   repo — local installs go through **Upload from file**.

**Step 3 — create a read-only service account (the "API key").** The API key
is a service account's **Client ID + Client Secret**, created in Strata Cloud
Manager (SCM) in four steps (figures are schematic redrawings; tenant
identifiers masked; red badges ①–⑤ number the flow):

1. **Open Identity & Access Management** — gear icon (System Settings, ①) at
   the bottom of SCM's left menu → **Identity & Access Management** (②) →
   **Add Identity** (a three-page wizard opens).

   <img src="docs/images/scm-1-iam-menu.png" alt="SCM left menu: ① System Settings gear → ② Identity & Access Management" width="380">

2. **Identity Information** — Identity Type = **Service Account**; pick a
   recognizable name (③, e.g. `apikey` — it becomes the Client ID prefix) →
   Next.

   <img src="docs/images/scm-2-identity-info.png" alt="Identity Information: Service Account + name" width="560">

3. **Client Credentials** — the **Client ID** (④) and **Client Secret** (⑤)
   are generated on the spot. ⚠️ **The secret is shown only this once** —
   copy it immediately or **Download CSV File** (store in a password manager,
   delete the file). Lost secrets can only be rotated. The digits after `@`
   in the Client ID **are the TSG ID** — no separate lookup. → Next.

   <img src="docs/images/scm-3-client-credentials.png" alt="Client Credentials: ④ Client ID (digits after @ = TSG ID), ⑤ Client Secret (shown once)" width="560">

4. **Assign Roles** — labeled Optional but **required** (no role = HTTP 403):
   Apps & Services = **All Apps & Services**, Role = **View Only
   Administrator** → Submit. That covers everything this plugin does; don't
   grant Superuser or any writable role (least privilege). MSP/multi-tenant:
   create the identity under the correct TSG scope.

   <img src="docs/images/scm-4-assign-roles.png" alt="Assign Roles: All Apps & Services + View Only Administrator → Submit" width="560">

Never paste the Client Secret into a chat — the tools take no credential
parameters by design; if a secret leaks, rotate it in SCM and update the env
file.

**Step 4 — provide the four variables.**

**Recommended: the env file** (`install.sh` already created a template):

```bash
# fill in ~/.prisma-sase.env (created by install.sh, chmod 600):
PRISMA_CLIENT_ID=svc-...@....iam.panserviceaccount.com
PRISMA_CLIENT_SECRET=...
PRISMA_TSG_ID=1234567890
PRISMA_REGION=sg
```

This is the **primary** path on macOS: GUI apps launched from Finder/Dock/
Spotlight are **not guaranteed to inherit `launchctl setenv` variables** — on
many machines they simply never arrive (field-verified). The env file works
regardless of how the app was launched. Custom location: `PRISMA_ENV_FILE`.

*Alternative: environment variables* — if your launch method reliably forwards
them (e.g. starting the app from a terminal, or a managed-device profile), the
server inherits them, and real environment values always win over the file.

**Verify any time** (no credentials needed with mock):

```bash
~/.prisma-sase-venv/bin/python mcp/server.py --selfcheck
```

It reports the interpreter, packages, env file, credentials, and any unexpanded
`${...}` placeholders, ending with READY / NOT READY and the exact fix.

## First run against a real tenant

The shipped defaults are **live-verified** (users/users_list,
tunnels/tunnel_list, alerts/alerts_list — all confirmed against a real tenant),
so on a comparable tenant things should work out of the box. Two open items:

- **Per-alert severity**: this tenant's `alerts/alerts_list` is an *aggregate*
  view (counts only). `query_alerts` reports honest summary counts until the
  per-alert "detail" view is identified — run
  `discover_insights(kind="alerts_detail")` once and adopt the suggestion.
- **Different tenant/version?** If any Insights tool returns HTTP 400, run
  full discovery — ask Claude to run `discover_insights`, or from a terminal:

```bash
~/.prisma-sase-venv/bin/python mcp/server.py --discover
```

It probes candidates read-only, uses a documented control probe to separate
auth problems from naming problems, and prints a `suggested_insights_map` to
adopt as one line in `~/.prisma-sase.env`; then restart the Claude app.

## Try it offline first (no credentials)

Set `PRISMA_MOCK=1` (env or `~/.prisma-sase.env`) and the tools run on sample
data through the real code path — good for a first look or a customer demo.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Plugin/skill load but the MCP tools never appear | Server failed to start — usually Python < 3.10 (macOS system `python3` = 3.9) | `bash install.sh`, then reinstall the plugin. `run.sh` / `server.py` now print the exact version error |
| `pip install fastmcp` → "No matching distribution found" | Misleading pip message — your Python is too old, the package exists | `python3 --version`; use a ≥ 3.10 interpreter (`install.sh` does this) |
| "Missing required context / Missing PRISMA_CLIENT_ID…" although `launchctl getenv` shows values | macOS GUI apps launched from Finder/Dock are not guaranteed to inherit `launchctl setenv` (field-verified: on some machines the vars never arrive) | Use `~/.prisma-sase.env` (the primary path) — `install.sh` creates the template. `--selfcheck` shows which source supplied each value |
| Insights tool returns HTTP 400 | Resource/view name or filter-payload shape doesn't match this tenant (the client already auto-tries time-filter and empty-filter variants) | Run `discover_insights` (or `--discover`), adopt the `suggested_insights_map` into `~/.prisma-sase.env` |
| Alerts show only counts, `severity_unavailable: true` | The per-alert severity view (`prisma_sase_external_alerts_current`, tried automatically first) did not return usable rows on your tenant, so the tool fell back to the aggregate view (counts by MU/RN/SC) | `discover_insights(kind="alerts_detail")` probes the candidates; if none work, capture the real view name from the SASE UI (dev tools → Network — step-by-step in the Skill's `references/endpoints.md`, "When discovery finds nothing") and set `PRISMA_INSIGHTS_MAP`; please report working names so they become shipped defaults |
| Insights 400 with `DATA10003` / "Invalid resource" | The resource/view **name does not exist** on this tenant | Run `discover_insights` for working names; adopt its suggestions |
| Insights 400 with `GCP10002` / "Unrecognized name: X" | The view **exists** — only field `X` in the payload is wrong | Don't change the view name; fix the property via `PRISMA_FILTER_TIME_PROP` / `_SEVERITY_PROP` / `_STATE_PROP` |
| Insights 400 with "SELECT list must not be empty" | The query sent an empty SELECT — this can 400 even on an existing view | Discovery probes with `properties:["*"]` (always valid) precisely to avoid this trap; report it if a regular tool hits it |
| Alerts show severity `unknown` (detail view) | The tenant's severity field name differs from the candidates tried | The response's `field_note` lists the record's real fields — set `PRISMA_FILTER_SEVERITY_PROP` and report the field name |
| 401 "Token request rejected" showing a literal `${PRISMA_TSG_ID}` | v0.1.0 shipped `${...}` placeholders in `.mcp.json`'s env block; some hosts pass them through verbatim | Upgrade to ≥ 0.2.0 (env block removed). `--selfcheck` detects this exact state |
| Edited `.mcp.json` in your project folder but nothing changed | After "Upload from file", Desktop runs an **internal copy** (`~/Library/Application Support/Claude…/cowork_plugins/marketplaces/local-desktop-app-uploads/prisma-sase/`), not your folder | With ≥ 0.2.0 you shouldn't need to edit it at all — use `PRISMA_PYTHON` / env file instead. Re-upload the plugin to change packaged files |
| Need a specific interpreter (custom venv etc.) | `run.sh` picks: `PRISMA_PYTHON` → `~/.prisma-sase-venv` → `python3.13…3.10` → `python3` | Set `PRISMA_PYTHON=/abs/path/to/python` |
| Tool answers include a `_verify` note | Insights resource/view names not yet confirmed for your tenant | Confirm once, then set `PRISMA_INSIGHTS_MAP` (see `skills/prisma-sase-ops/references/endpoints.md`) |

## Windows install

The Python server is fully cross-platform; only the launcher differs. Windows
gets its **own package variant** — `prisma-sase-windows.plugin` — whose MCP
config starts the server via `cmd /c mcp\run.cmd` instead of bash (don't
upload the macOS/Linux variant on Windows; its `bash` command won't exist).

1. Install **Python ≥ 3.10** from [python.org](https://www.python.org/downloads/)
   and tick **"Add python.exe to PATH"** during setup.
   ⚠️ If typing `python` opens the **Microsoft Store**, that's the Store alias
   stub, not Python — install the real thing or disable the alias
   (Settings → Apps → Advanced app settings → App execution aliases).
2. From the unzipped plugin folder run `install.bat` — it creates
   `%USERPROFILE%\.prisma-sase-venv`, installs dependencies, writes the
   `%USERPROFILE%\.prisma-sase.env` credential template, and runs an offline
   selfcheck.
3. In Claude Desktop: **Settings → Plugins → Upload from file** → pick
   **`prisma-sase-windows.plugin`**.
4. Fill in `%USERPROFILE%\.prisma-sase.env` (same four variables). Plain user
   environment variables (System Properties / `setx`, then restart the app)
   also work on Windows — GUI apps there do inherit them — but the env file
   stays the recommended, launch-method-independent path.
   (`chmod 600` doesn't apply on Windows; the file sits in your user profile,
   which NTFS already restricts to you + administrators.)
5. Verify:
   `%USERPROFILE%\.prisma-sase-venv\Scripts\python.exe <plugin>\mcp\server.py --selfcheck`

`run.cmd` picks the interpreter the same way as `run.sh`: `PRISMA_PYTHON` →
the `.prisma-sase-venv` venv → `py -3.13…-3.10` → `python`. WSL also works if
you prefer the Linux flow, but it is not required.

## Cloud sessions: getting credentials in

Remote/cloud sessions (Cowork web, remote containers) run in a sandbox that
**cannot read your laptop's home directory** — `~/.prisma-sase.env` does not
follow you there, and two intuitive paths fail in confusing ways:

- **Attaching the dotfile to the chat** silently fails: Finder hides
  dotfiles, so the picker often sends nothing while you believe it was sent.
- **Authorizing your home directory root** is typically not allowed.

The supported path — stage a **non-dotfile copy** into a folder you can
authorize/attach, then point the server at it:

```bash
# on your Mac: copy WITHOUT the leading dot so it is visible & attachable
cp ~/.prisma-sase.env ~/Documents/<your-project>/prisma-sase.env
```

In the cloud session, set `PRISMA_ENV_FILE` to wherever the staged copy
landed (the env-file loader honors it):

```bash
PRISMA_ENV_FILE=/path/to/prisma-sase.env
```

⚠️ **Never paste the Client Secret into the conversation** — the tools take
no credential parameters by design, and a secret in chat is a secret in the
transcript. Deliberately, credentials do **not** auto-sync to the cloud;
staging is a manual, visible act. Remove the staged copy when the session's
work is done. No credentials at hand? `PRISMA_MOCK=1` runs every tool
offline with realistic sample data.

If the plugin's tools don't appear in a cloud session at all, see the
Skill's **bootstrap runbook** (SKILL.md) and the launch breadcrumb at
`~/.prisma-sase-launch.log`.

## All environment variables

| Variable | Required | Purpose |
|---|---|---|
| `PRISMA_CLIENT_ID` / `PRISMA_CLIENT_SECRET` | ✅ | service account credentials (secret: env / env file only — never commit) |
| `PRISMA_TSG_ID` | ✅ | default Tenant Service Group id |
| `PRISMA_REGION` | ✅ | `X-PANW-Region` header value (e.g. `sg`, `us`, `de`) |
| `PRISMA_SUBTENANT_ID` | — | adds `Prisma-SubTenant` header |
| `PRISMA_MOCK` | — | `1` = offline mock mode |
| `PRISMA_PYTHON` | — | absolute path of the interpreter `run.sh` should use |
| `PRISMA_ENV_FILE` | — | custom env-file path (default `~/.prisma-sase.env`, the primary credential mechanism) |
| `PRISMA_INSIGHTS_MAP` | — | JSON override of Insights resource/view names once confirmed |
| `PRISMA_FILTER_TIME_PROP` / `_SEVERITY_PROP` / `_STATE_PROP` | — | override Insights filter property names |
| `PRISMA_ADEM_ENDPOINT_TYPE` | — | ADEM `endpoint-type` (default `muAgent`) |
| `PRISMA_LOG_LEVEL` | — | `DEBUG` / `INFO` (default) / `WARNING` |

## Security

- Service account is **read-only** and bound only to the needed TSG(s); the
  plugin has no write capability, so there is no config-drift risk.
- `client_secret` lives in your environment or a `chmod 600` env file — never in
  the package, `.mcp.json`, logs, or tool responses.
- Each tool call is audit-logged (time, tool, parameter summary) to stderr; the
  token and response bodies are **not** logged.
- Query results can include user names — confirm your data-handling policy before
  demoing against a customer tenant.

## What's inside / Roadmap

```
prisma-sase-plugin/
├── .claude-plugin/plugin.json   # plugin metadata
├── .mcp.json                    # MCP mount: bash mcp/run.sh (no env block, no secrets)
├── install.sh / install.bat     # one-shot venv + deps + selfcheck (macOS/Linux | Windows)
├── mcp/                         # FastMCP server (Python, read-only)
│   ├── run.sh / run.cmd         # launcher: picks a Python >= 3.10 (per platform)
│   ├── server.py  auth.py  client.py  config.py  mock_data.py
│   ├── tools/                   # status / alerts / users / adem
│   └── requirements.txt
└── skills/prisma-sase-ops/      # decision tree, thresholds, runbooks, weekly report
```

- **Phase 1 (this)** — 4 read-only tools over stdio + the ops Skill.
- **Phase 2** — SD-WAN tools, config-snapshot audit, richer multi-tenant.
- **Phase 3** — weekly-report automation, streamable-HTTP deployment, optional
  Prisma AIRS MCP security demo.

## 關於本專案與免責聲明 / About & Disclaimer

**中文** — 本專案作者任職於 Palo Alto Networks,職務為 Solutions Consultant。
這是作者為了向客戶推廣 Prisma SASE、以個人時間開發的 **side project**:
**並非 Palo Alto Networks 官方開發、維護或背書,不代表公司立場;
內容與查詢結果亦不保證正確性、完整性或適用性** —— 使用前請自行評估,
重要決策請以官方文件與官方支援管道為準。本專案以開源方式發佈
(MIT License,見 the repository's LICENSE file),歡迎透過 GitHub Issues / PR
提出任何意見與回饋,也歡迎**無償**引用、修改與再利用。

**English** — The author works at Palo Alto Networks as a Solutions
Consultant. This is a personal **side project** built on personal time to
help introduce Prisma SASE to customers. **It is not developed, maintained,
or endorsed by Palo Alto Networks and does not represent the company; no
guarantee is made as to the correctness, completeness, or fitness of its
content or query results** — evaluate before use, and rely on official
documentation and support channels for important decisions. The project is
open source under the MIT License; feedback and contributions
are welcome via GitHub Issues / PRs, and everyone is free to use, modify,
and reference it at no cost.

*Palo Alto Networks、Prisma 及相關標誌為 Palo Alto Networks, Inc. 之商標。
Palo Alto Networks, Prisma, and related marks are trademarks of
Palo Alto Networks, Inc.*
