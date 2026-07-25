---
name: prisma-sase-ops
description: >-
  Operate and monitor a Prisma SASE (Prisma Access) tenant through the
  read-only prisma-sase MCP tools. Use whenever the user asks about SASE / Prisma
  Access health, alerts, tunnel or Remote Network / Service Connection status,
  connected Mobile Users, or ADEM user-experience scores -- e.g. "現在 SASE 狀態如何",
  "有沒有 P1 告警", "幫我查 XX 使用者體驗為什麼掉", "列出 tunnel 狀態", "how is Prisma
  Access doing", "any critical alerts", "why is this user slow" -- or when
  producing a tenant health report. Provides the tool-selection decision tree,
  metric-interpretation thresholds, diagnostic runbooks, and the weekly-report
  template.
---

# Prisma SASE Ops

This Skill is the **knowledge layer** for the `prisma-sase` MCP server. The MCP
tools know *how* to call the APIs safely; this Skill tells you *which* tool to
call, *how to read the numbers*, and *how to present* the answer.

All tools are **read-only**. There is no way to change tenant configuration from
here, and you must never imply that there is.

## Tools at a glance

| Tool | Use it for | Key args |
|---|---|---|
| `get_sase_status` | Vague "how are things / any problems?" — one-shot overview | `tsg_id?`, `region?` |
| `query_alerts` | Specific alert questions (severity, raised/cleared, time window) | `severity?`, `state?`, `hours=24`, `limit=20` |
| `get_connected_users` | How many Mobile Users are connected, by location, trend | `hours=24`, `limit=20` |
| `get_user_experience` | ADEM experience score — overall or a named user/app | `user?`, `app?`, `hours=24` |
| `get_remote_networks` | Per-tunnel status rows (RN/SC): up/down, site, throughput; filter by state | `state?`, `hours=1`, `limit=20` |
| `discover_insights` | Diagnostic: probe which Insights resource/view names THIS tenant accepts | `kind?`, `tsg_id?`, `region?` |

Every tool takes optional `tsg_id` and `region` to target a specific tenant
(useful in multi-customer demos); omit them to use the default tenant.

## Decision tree — pick the tool

1. **Vague / broad status** ("現在狀態如何", "everything ok?", "any issues right
   now", "health check") → `get_sase_status` first. Read its `headline`, then
   drill in only where it flags a problem.
2. **Alerts specifically** ("有沒有 P1/critical 告警", "what fired overnight",
   "show cleared vs raised") → `query_alerts`. Map "P1" → `severity="critical"`,
   "P2" → `"high"`. Default window is 24h; widen with `hours` if they say "this
   week".
3. **A named user or app is mentioned**, or "slow / bad experience / 卡 / 慢" →
   `get_user_experience` with that `user` (or `app`). Then decompose the
   `components` (LAN/WiFi/DNS/app) to locate the weak link.
4. **Connected-user count / capacity / "how many people online"** →
   `get_connected_users`.
5. **Tunnel / Remote Network / Service Connection / 分點連線 status** →
   `get_remote_networks` (per-tunnel rows; `state="down"` to list problems).
   The quick up/down counts also appear in `get_sase_status`'s `connectivity`
   section. (SD-WAN branch-device tools arrive in Phase 2.)
6. **An Insights-backed tool returns HTTP 400**, a response carries `_verify`,
   or it's the **first run against a new tenant** → `discover_insights`. It
   probes candidate resource/view names read-only, separates auth problems from
   naming problems via a documented control probe, and returns a paste-ready
   `PRISMA_INSIGHTS_MAP`. Walk the user through adding that JSON (single line)
   to `~/.prisma-sase.env`, then re-run the failing tool. **If the response
   lists kinds under `matches_shipped_defaults`, tell the user those need no
   env change** — the discovered names are already this version's built-in
   verified defaults; only `suggested_insights_map` entries are worth persisting.

When a request spans several of these, start with `get_sase_status`, then fire
the specific tools **in parallel** for the parts that need detail.

## Reading get_sase_status honestly

`headline` is derived from the actual check outcomes: `Healthy` (all 4 checks
succeeded, data interpretable), `ATTENTION` (real problems found), `PARTIAL`
(some checks failed or returned no data — health cannot be confirmed), or
`UNKNOWN` (all checks failed). **Never summarize a PARTIAL/UNKNOWN result as
"everything looks fine"** — state what was verified, what wasn't, and why (the
per-section `error`/`hint` says). The `checks` object gives the counts.

## Output conventions

- **Alerts** are always reported **with their severity and timestamp**, highest
  severity first. Lead with the counts by severity, then the notable items.
  **Exception**: when the response has `severity_unavailable: true`, the
  per-alert severity view (`prisma_sase_external_alerts_current`, tried
  automatically first) returned nothing usable and the tool fell back to the
  aggregate view (counts by MU/RN/SC only) — report the `summary_counts`,
  never invent severities. Suggest `discover_insights(kind="alerts_detail")`
  to probe the severity view directly: if it works, ask the user to report it
  (mapping gets marked verified); if it doesn't exist, present severity as an
  API limitation, NOT a setting the user forgot. If the response carries
  `sub_tenant_count` / `aggregation_note`, always say the total is summed
  across N sub-tenants (alerts **raised within the window**, not currently
  active) — the SASE UI shows per-sub-tenant numbers and will look lower.
- **ADEM scores** are always reported **with their rating band** (see
  `references/thresholds.md`), not as a bare number. A score below 70 is
  "degraded" and should be called out, with the weakest component named.
- **Tunnels**: state up/down counts and name the ones that are **down**. Two
  more states matter and are NOT "fine": tunnels in `other_states` (e.g.
  `init` — never established; see `not_up_names`) and tunnels that are up
  with `monitoring_down` (traffic flows but health is unobserved; see
  `monitoring_down_names`). Both appear in the headline — report them, don't
  round "12 up, 0 down" up to "all good".
- **Throughput is in Kbps** — the field names carry the unit
  (`avg/peak/p95_throughput_kbps`) and every response includes a `units` block.
  When presenting to humans, convert to Mbps (÷1000, one decimal) and **always
  write the unit**: `peak_throughput_kbps: 8042.58` → "峰值約 8.0 Mbps", never
  "8042" bare and never "8 Gbps". `peak` is the highest per-minute sample
  within the time bucket, not an absolute instantaneous max. Sanity check:
  if a reading would exceed the site's physical uplink, you have almost
  certainly misread the unit — stop and re-check before reporting.
- Keep it tight: summarize, don't dump raw JSON at the user. Surface the numbers
  that matter and the one or two things worth acting on.
- **"Which plugin version am I running?"** → `get_sase_status` returns
  `plugin_version`; the CLI equivalents (`--selfcheck`, the startup log) show
  it too. Compare against the repo's `plugin/CHANGELOG.md` to tell the user
  what their version does or lacks.
- **`plugin_update_pending` in a response** → the host kept an old server
  process alive across a marketplace update, so **this answer came from the
  OLD code** and the update's fixes are not active. Say so up front and give
  the restart instruction from the `action` field (Desktop ⌘Q / CLI
  `/reload-plugins`) — don't let the user assume the update took effect, and
  don't debug behaviour that the newer version may already have fixed.

## Reading the `_verify` / `note` fields

Tool responses may include:
- `_verify` — the Insights resource/view used is a documented default not yet
  confirmed against this tenant. If a tool also returns empty data or a 404-style
  error, that mapping is the likely cause; tell the user it can be corrected via
  the `PRISMA_INSIGHTS_MAP` env var (see `references/endpoints.md`). Do **not**
  silently treat unverified-and-empty as "all clear".
- `note` — results were truncated by `limit`; mention the total and that the
  window or limit can be adjusted.
- `ok: false` with `error` + `hint` — relay the hint; it is written to be
  actionable (missing env var, wrong region, missing read-only role).

## Bootstrap runbook — when this Skill loaded but the MCP tools are absent

Structural fact of cloud/remote sessions (Cowork web, remote containers):
**Skills sync into the session, but the plugin's MCP server may not be
launched there** — a fresh container has no `~/.prisma-sase-venv`, no
fastmcp/httpx, and no `~/.prisma-sase.env`. If `get_sase_status` /
`query_alerts` etc. are NOT in your tool list, do not improvise answers and
do not give up.

**First, look for `prisma_sase_setup_required`.** If that tool is present,
the server failed to start and a dependency-free fallback took over: call it
for the diagnosis, then **offer to run `prisma_sase_install_dependencies`** —
it creates `~/.prisma-sase-venv` and installs the requirements in about a
minute, no shell work needed from the user. Afterwards they must reload
completely: **Claude Desktop → ⌘Q and reopen** (closing the window does not
relaunch plugin servers); **Claude Code CLI → `/reload-plugins` or restart
`claude`**. Do not attempt tenant answers while in this state.

**Freshly installed plugin?** In the CLI, a just-installed plugin's MCP
server is not running yet — `/plugin install` says so. Run
`/reload-plugins` before concluding anything is broken.

If no tools at all are present, bootstrap in ~2 minutes:

1. **Diagnose** — read the launch breadcrumb FIRST, then run selfcheck:
   ```bash
   cat ~/.prisma-sase-launch.log           # why the server died (stderr is invisible here)
   bash <plugin>/mcp/run.sh --selfcheck    # or: python3 <plugin>/mcp/server.py --selfcheck
   ```
   ⚠️ **Never conclude "the user has no credentials" from a hand-run
   selfcheck.** Values supplied through the plugin's enable dialog
   (userConfig) are injected into the **MCP server process only** — they are
   invisible to any command you run in a shell, so `credentials: MISSING` is
   *expected* there and says nothing about the user's setup. Selfcheck (≥
   0.8.2) reads the host settings and prints this caveat itself; if you see
   an older build, check
   `~/.claude/settings.json` → `pluginConfigs[...].options` for
   `client_id`/`tsg_id`/`region` (the secret is in OS secure storage and
   correctly absent). **Only** treat credentials as missing when neither the
   dialog nor an env file has them.
   How to read the breadcrumb:
   - **File does not exist** → the host never even ran the launcher (the
     MCP server was not attempted) — bootstrapping below is the only path.
   - `run.sh invoked` → launch was attempted.
   - `launching with <python>` → an interpreter was chosen; if nothing
     follows, the server process itself died after start (check selfcheck).
   - `FATAL: ...` → the exact cause of death: no Python ≥ 3.10, version
     floor, or missing packages — each maps to step 2 below.
2. **Missing deps** → create the venv the launcher already knows to find:
   ```bash
   python3 -m venv ~/.prisma-sase-venv
   ~/.prisma-sase-venv/bin/python -m pip install -r <plugin>/mcp/requirements.txt
   ```
3. **Missing credentials** → the user must stage them into the session
   (their laptop's `~/.prisma-sase.env` does NOT follow them to the cloud).
   Walk them through the supported path in the plugin README section
   *"Cloud sessions: getting credentials in"* — staged env file +
   `PRISMA_ENV_FILE=<path>`. **Never ask for or accept the Client Secret in
   the conversation.** No credentials available? `PRISMA_MOCK=1` still
   demonstrates every tool offline.
4. **Call the tools without the MCP layer** — every tool is a plain
   synchronous, importable function (keep relying on this; it is a design
   guarantee):
   ```python
   import sys; sys.path.insert(0, "<plugin>/mcp")
   from tools.status import get_sase_status
   from tools.alerts import query_alerts
   print(get_sase_status())
   ```
   Same client, same read-only guarantees, same output shapes as the MCP
   tools — everything in this Skill about interpreting results applies
   unchanged.

## Credential handling rules — enforce these when guiding users

1. **Only the supported homes, nowhere else.** Credentials live in exactly
   one of: (a) the **plugin enable dialog** (userConfig — the secret lands
   in the OS secure storage; the recommended path on Desktop), (b) the
   **local env file** `~/.prisma-sase.env` (Windows:
   `%USERPROFILE%\.prisma-sase.env`, `chmod 600`), or (c) a secret store
   reached via **`PRISMA_SECRET_CMD`** (Keychain / secret-tool / pass /
   1Password). Never suggest project folders, git repos, notes, shared
   drives, or cloud storage.
2. **Never in the conversation.** Do not ask for, accept, or echo
   `PRISMA_CLIENT_SECRET` (or full env-file contents) in chat — the tools
   take no credential parameters by design. If a user starts pasting a
   secret, stop them and point to a supported home instead. **The host's
   plugin enable dialog is settings UI, not the conversation** — telling a
   user to fill it in is correct, not a violation.
3. **Cloud sessions get a TEMPORARY staged copy only** (bootstrap runbook
   step 3): a non-dotfile copy in an authorized folder + `PRISMA_ENV_FILE`.
   It is a working copy, not a second home — when the session's work is
   done, **proactively remind the user to delete it**.
4. **Suspected exposure → rotate, don't just delete.** If a secret ever
   lands in a chat, repo, or shared file, tell the user to rotate it in SCM
   (Identity & Access Management → the service account → regenerate the
   secret) and update the local env file. Deleting the message/file does
   not un-leak it.

## References

- `references/endpoints.md` — which tool maps to which API, filter syntax, and
  the tenant-confirmation checklist.
- `references/api-catalog.md` — the full PANW Prisma SASE API landscape
  (every family on pan.dev), what this plugin covers vs. what is a read-only
  candidate vs. what the read-only design excludes. Use it to answer "can the
  plugin do X / why not Y / what could Phase 2 add".
- `references/thresholds.md` — ADEM score bands, alert severity ↔ P1–P4, tunnel
  status semantics.
- `references/runbooks.md` — step-by-step diagnostic plays ("user says it's
  slow", "is there an outage", "capacity check").
- `templates/weekly-report.md` — structure for the tenant health weekly report.
