---
name: prisma-sase-ops
description: >-
  Operate, monitor, install and troubleshoot a Prisma SASE (Prisma Access)
  setup through the read-only prisma-sase MCP tools. Use whenever the user asks
  about SASE / Prisma Access health, alerts, tunnel or Remote Network / Service
  Connection status, connected Mobile Users, or ADEM user-experience scores --
  e.g. "現在 SASE 狀態如何", "有沒有 P1 告警", "幫我查 XX 使用者體驗為什麼掉",
  "列出 tunnel 狀態", "how is Prisma Access doing", "any critical alerts", "why is
  this user slow" -- or when producing a tenant health report. ALSO use it for
  installing, configuring or repairing the plugin itself, even when none of the
  query tools are loaded yet: "怎麼安裝 prisma sase", "SASE 工具跑不出來",
  "設定 SASE 憑證", "how do I install this", "set up prisma sase", "the SASE tools
  are missing", "prisma sase says missing credentials". The Skill and the MCP
  server install separately, so the Skill is often present BEFORE any tool is --
  it carries the setup walkthrough for exactly that state. Provides the
  tool-selection decision tree, metric-interpretation thresholds, diagnostic
  runbooks, credential handling rules, and the weekly-report template.
---

# Prisma SASE Ops

This Skill is the **knowledge layer** for the `prisma-sase` MCP server. The MCP
tools know *how* to call the APIs safely; this Skill tells you *which* tool to
call, *how to read the numbers*, and *how to present* the answer.

**Check your tool list before anything else.** The Skill and the server install
separately, so this Skill is frequently loaded with **no prisma-sase tools
present at all** — a user who has installed the plugin and nothing else is in
that state, and it is normal, not broken. If `get_sase_status` and friends are
absent, do not improvise tenant answers and do not treat it as a failure: go
straight to the *Bootstrap runbook* below and walk them through installing the
server. Guiding that install is a first-class job of this Skill, not a detour
from it.

All tools are **read-only**. There is no way to change tenant configuration from
here, and you must never imply that there is. When asked to *do* something —
restart a tunnel, change a policy, clear an alert — say plainly that these tools
only read, name the specific place in Strata Cloud Manager where the change is
made, and offer to verify the result afterwards with a read query. Do not hedge
or leave the impression it might be possible with different phrasing.

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
   as another env key in their **Local MCP servers** entry (or to
   `~/.prisma-sase.env` if they use one) — it is a tuning variable, not a
   credential, so it needs no secure storage — then re-run the failing tool. **If the response
   lists kinds under `matches_shipped_defaults`, tell the user those need no
   env change** — the discovered names are already this version's built-in
   verified defaults; only `suggested_insights_map` entries are worth persisting.

7. **None of the tools are loaded** → the server is not installed yet. This is
   the expected state right after installing the plugin. Go to the *Bootstrap
   runbook*; do not answer tenant questions from memory in the meantime.
8. **The tools ran but this tenant cannot answer** — the view does not exist,
   the window is empty, the field is not exposed. Say what was asked, what came
   back, and why, then stop. Do **not** substitute a neighbouring metric and
   present it as the answer, and do not describe an API limitation as something
   the user misconfigured. `PRISMA_MOCK=1` can still show what the answer
   *would* look like, which is often what a demo actually needs — offer it as a
   demo aid, never as tenant data.

## `PRISMA_MOCK` — what it is for, and what it is not

With `PRISMA_MOCK=1` every tool answers from built-in sample data instead of
calling the API: no credentials, no tenant, no network. Responses keep the real
shape (same fields, same units, the same aggregate-vs-per-alert quirks), so
they travel the identical code path a live call does. Three times it is worth
suggesting:

- **No API key yet.** Approval can take days; this shows what the tools return
  in the meantime.
- **A demo.** Showing the tools without a real tenant's alerts and IPs on
  screen.
- **Splitting a fault in two** — the one that gets forgotten. When a tool
  misbehaves, re-run it under `PRISMA_MOCK=1`: still wrong → the plugin;
  fine → the tenant, credentials, or network. That single check saves
  debugging the wrong half.

Mock output is always labelled (`mock mode: ON` in `--selfcheck`, and in
`get_sase_status`). **Never present a sample number as the user's tenant**,
never mix mock and live figures in one answer, and when someone wants real data
say plainly that the variable has to come out and the app restart.

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
- **"Which plugin version am I running?"** → there are **two** versions and
  they are allowed to differ; answer with both. `get_sase_status` returns
  `plugin_version`, which is the **server**; this Skill's own version is in
  the plugin manifest, and `CHANGELOG.md` ships at the **root of the installed
  plugin directory** (not under `plugin/` — that is the repo layout, which you
  cannot read). The CLI equivalents (`--selfcheck`, the startup log) also show
  the server version.
- **When the two versions differ** — expected, not a fault. The server is
  re-resolved from `main` on every launch, so it moves the moment a fix is
  pushed; the Skill is pinned to a cached version and only moves when the user
  runs an update. So:
  - **Server newer than this Skill** (the common case) — trust the tool
    output over this Skill's prose. If a response carries a field this Skill
    does not describe, report it on its own terms rather than forcing it into
    a shape described here, and say the Skill text is behind. Suggest
    `/plugin marketplace update prisma-sase` when the gap actually matters to
    the answer; don't nag otherwise.
  - **Skill newer than the server** — a behaviour described here may simply
    not exist yet in their server. Say so instead of insisting the tool is
    misbehaving; a full restart picks the new server up (uvx re-resolves at
    launch).
- **`plugin_update_pending` in a response** → the host kept an old server
  process alive across an update, so **this answer came from the OLD code**
  and the update's fixes are not active. Say so up front and give the restart
  instruction from the `action` field (Desktop ⌘Q / CLI restart `claude`) —
  don't let the user assume the update took effect, and don't debug behaviour
  that the newer version may already have fixed.
  ⚠️ **Only venv-based installs can raise this.** The detection keys off a
  version-named install directory, which the uvx layout (`site-packages`)
  never has — so on a uvx install the field is *always absent* and its absence
  proves nothing. Never reason "no `plugin_update_pending`, therefore the
  server is current". To actually check a uvx server, compare its
  `plugin_version` against the repo's latest release.
- **`credentials_not_supplied` in a response** → see the dedicated section
  below. It means the credentials that reached the server were blank or
  unsubstituted — a configuration problem, never a tenant outage.

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

## Runbook — the credentials never reached the server

Triggered by `credentials_not_supplied` in a `get_sase_status` response, or by
every tool failing with "Missing PRISMA_CLIENT_ID / Missing required context".
Nothing about the tenant, the API key, or the service account is wrong — the
server simply never received four usable values.

**Lead with the attribution.** The user's most likely belief is that they
broke something, or that their tenant is down. Correct both, in this order:

1. **Say what happened, plainly.** No usable credentials reached the server.
   Relay the `detail` field verbatim — it names which variables were affected
   and how.
2. **Do not** send them to re-check the API key, the service account role, the
   region, or the SASE console. None of those are implicated, and every one of
   them is an expensive detour.

The `kind` field says which shape it is, and the two differ:
- `expanded_empty` — the names arrived set but blank. Something is supplying
  keys with no values: almost always a blank env field in the **Local MCP
  servers** entry named `prisma-sase`.
- `unexpanded` — a literal `${...}` arrived. That env block is **literal**, so
  a `${...}` in it is never substituted; the real value must be typed there.
  (`${user_config.*}` instead means a legacy 0.8.x pinned plugin install.)

⚠️ **"No credentials visible" is NOT itself a fault.** Since 0.9.0 credentials
live in the Local MCP entry's env block, which reaches the **server process
only** — a hand-run `--selfcheck` cannot see them, and `~/.claude/settings.json`
has no entry for them by design (the plugin declares no `userConfig` any more).
An install with no `pluginConfigs` entry is the **normal, correct** shape. Never
conclude from that alone that the user is misconfigured.

**Then walk the recovery:**

**Step 1 — run the guided setup (always offer this first).** It writes the
Local MCP entry and can put the Client Secret in the OS keychain, so no secret
lands in a file:
```bash
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
```
It prompts for each value (the secret hidden) and prints the entry to add.
Afterwards they must restart completely: **Desktop → ⌘Q and reopen** (closing
the window does not relaunch MCP servers); **CLI → restart `claude`**. Then
confirm by calling `get_sase_status` again.

**Step 2 — fix the entry by hand, if setup already ran.** For `expanded_empty`
and `unexpanded` the entry exists but holds a bad value: Settings →
Extensions/Connectors → **Local MCP servers** → `prisma-sase` → correct the env
field, then full restart. Note the entry's env is stored in plaintext, so the
secret belongs in `PRISMA_SECRET_CMD` rather than typed in directly.

**Step 3 — env-file fallback, when the panel is unavailable** (cloud session,
CI). `~/.prisma-sase.env`, `chmod 600`. Say plainly that this puts the secret
on disk in plaintext, and that they should **rotate it in SCM if it ever sat
there** — deleting the file does not undo the exposure. `setup-keychain.sh`
is the better variant: it keeps only non-secret values in the file plus
`PRISMA_SECRET_CMD`.

**Meanwhile**, `PRISMA_MOCK=1` runs every tool on sample data, which is enough
for a demo or to show what the answers will look like.

**Never** ask for, accept, or echo the Client Secret in the conversation — not
even to "check" it. Every path above has the user enter it into a dialog, a
hidden prompt, or a file they own. See the credential-handling rules below.

## Bootstrap runbook — when this Skill loaded but the MCP tools are absent

Structural fact since 0.9.0: **the Skill and the server install separately.**
The Skill is the plugin; the server is a **Local MCP servers** entry that uvx
runs. Installing the plugin therefore gives you this knowledge layer and *no
tools* until the server entry is added — that is a normal intermediate state,
not a broken install. The same gap appears in cloud/remote sessions (Cowork
web, remote containers), where Skills sync but no local MCP server is launched.

If `get_sase_status` / `query_alerts` etc. are NOT in your tool list, do not
improvise answers and do not give up.

**First, look for `prisma_sase_setup_required`.** If that tool is present,
the server started but its dependencies are missing and a dependency-free
fallback took over: call it for the diagnosis, then **offer to run
`prisma_sase_install_dependencies`**. Afterwards they must reload completely:
**Claude Desktop → ⌘Q and reopen** (closing the window does not relaunch MCP
servers); **Claude Code CLI → restart `claude`**. Do not attempt tenant
answers while in this state. (On a uvx install this tool should never appear —
uvx builds the environment itself. Seeing it means a venv-based install.)

**Just added the Local MCP entry?** It does not start until the app restarts.
Desktop: ⌘Q and reopen. CLI: restart `claude`.

If no tools at all are present, the fix is almost always **"the server was
never installed"** — the user has the Skill only. Offer this first:

1. **Install the server** — one command, no Python setup needed:
   ```bash
   uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
   ```
   It prompts for the four values (secret hidden), can store the secret in the
   OS keychain, and prints the **Local MCP servers** entry to add. Full restart
   afterwards. This is the whole install — it needs no venv and no `pip`.
2. **If the entry exists but no tools appeared** — diagnose:
   ```bash
   cat ~/.prisma-sase-launch.log     # only exists on venv-based installs
   uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-mcp --selfcheck
   ```
   ⚠️ **Never conclude "the user has no credentials" from a hand-run
   selfcheck.** The Local MCP entry's env reaches the **server process only**,
   so `credentials: MISSING` is *expected* in a shell and says nothing about
   their setup. Likewise, `~/.claude/settings.json` holding no `pluginConfigs`
   entry is **correct** since 0.9.0 — the plugin declares no `userConfig`.
   Only treat credentials as genuinely missing when the server itself reports
   `expanded_empty` or `unexpanded` (see the runbook above).
   The most common real cause is `PATH`: the app does not give MCP servers a
   login shell's `PATH`, so `uvx` is not found. The entry needs an explicit
   `PATH` in its env — `which uvx` gives the directory to add.
3. **Cloud session, no panel to configure** → stage credentials into the
   session (their laptop's `~/.prisma-sase.env` does NOT follow them there):
   a staged env file + `PRISMA_ENV_FILE=<path>`. **Never ask for or accept the
   Client Secret in the conversation.** No credentials available?
   `PRISMA_MOCK=1` still demonstrates every tool offline.
4. **Call the tools without the MCP layer** — every tool is a plain
   synchronous, importable function (keep relying on this; it is a design
   guarantee):
   ```python
   from prisma_sase_mcp.tools.status import get_sase_status
   from prisma_sase_mcp.tools.alerts import query_alerts
   print(get_sase_status())
   ```
   From a source checkout, `sys.path.insert(0, "<repo>/src/prisma_sase_mcp")`
   first and drop the package prefix.
   Same client, same read-only guarantees, same output shapes as the MCP
   tools — everything in this Skill about interpreting results applies
   unchanged.

## Credential handling rules — enforce these when guiding users

1. **Only the supported homes, nowhere else.** The Client Secret lives in
   exactly one of: (a) a secret store reached via **`PRISMA_SECRET_CMD`**
   (Keychain / secret-tool / pass / 1Password — what `prisma-sase-setup` and
   `setup-keychain.sh` configure for you), (b) the **Local MCP servers**
   entry's env block, or (c) the **local env file** `~/.prisma-sase.env`
   (Windows: `%USERPROFILE%\.prisma-sase.env`, `chmod 600`). Never suggest
   project folders, git repos, notes, shared drives, or cloud storage.

   These are **not equal choices** — recommend them in order:
   - **(a) always first.** It is the only one where the secret is not stored
     in readable form anywhere: the entry holds a *command*, not the value.
   - **(b) and (c) both put the secret in plaintext on disk.** The Local MCP
     entry is stored as plain JSON in the host's config — it is *not* secure
     storage, despite being settings UI. Say so plainly when suggesting
     either; do not present them as equivalent to (a).

   The non-secret three (`PRISMA_CLIENT_ID`, `PRISMA_TSG_ID`,
   `PRISMA_REGION`) belong in the Local MCP entry — they are identifiers, not
   secrets. Resolution order is environment → env file → `PRISMA_SECRET_CMD`,
   stopping at the first value, so the entry wins and the file only fills gaps.
2. **Never in the conversation.** Do not ask for, accept, or echo
   `PRISMA_CLIENT_SECRET` (or full env-file contents) in chat — the tools
   take no credential parameters by design. If a user starts pasting a
   secret, stop them and point to a supported home instead. **Settings UI and
   a terminal prompt are not the conversation** — telling a user to run
   `prisma-sase-setup` or to fill in the Local MCP entry is correct, not a
   violation.
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
