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
  **Exception**: when the response has `severity_unavailable: true`, this
  tenant's alerts view is an aggregate (counts by MU/RN/SC only) — report the
  `summary_counts` and say severity breakdown is not available yet; never
  invent severities, and mention `discover_insights(kind="alerts_detail")` as
  the path to fix it.
- **ADEM scores** are always reported **with their rating band** (see
  `references/thresholds.md`), not as a bare number. A score below 70 is
  "degraded" and should be called out, with the weakest component named.
- **Tunnels**: state up/down counts and name the ones that are **down**.
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
