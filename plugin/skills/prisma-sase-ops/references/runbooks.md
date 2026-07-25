# Diagnostic runbooks

Ordered plays for the common asks. Fire independent tool calls in parallel; stop
early once the cause is clear. Everything here is read-only.

## Runbook A — "使用者說慢 / this user's experience dropped"

1. `get_user_experience(user=<name>)` — get the overall score + `components`.
2. Read the band (`references/thresholds.md`). If overall < 70, it's degraded.
3. Name the **weakest component** and interpret it (LAN/WiFi/DNS/app mapping in
   thresholds).
4. Widen the window if they mention "the last couple of days":
   `get_user_experience(user=<name>, hours=48)` and compare.
5. Correlate: `query_alerts(hours=48)` — is there an ADEM/connectivity alert
   touching this user's location? If the app component is the weak link, the
   access network may be fine and the issue is the SaaS path.
6. Report: score + rating, weakest component, whether an alert corroborates it,
   and the plain-language likely cause.

> If a per-user score comes back empty with a `note` about the parameter name,
> the ADEM per-user query param isn't confirmed for this tenant yet — say so and
> fall back to the overall/app view.

## Runbook B — "現在有沒有問題 / is there an outage right now"

1. `get_sase_status()` — read the `headline`.
2. If it flags **critical/high alerts** → `query_alerts(severity="critical")`
   (and `"high"`) for the specifics, newest first. If the response says
   `severity_unavailable`, report the aggregate counts honestly instead.
3. If it flags **tunnels down** → `get_remote_networks(state="down")` for the
   per-tunnel rows; note SC vs RN (`node_type`), site, and monitoring state.
4. If **experience** is under 70 → `get_user_experience()` overall, then decompose.
5. Report the headline first, then the 1–2 items worth acting on. Don't bury the
   lede in raw data.

## Runbook C — "P1 告警 / critical alerts check"

1. `query_alerts(severity="critical", hours=24)` (widen `hours` for "this week").
2. Group by `category` and lead with the newest. Include timestamps.
3. If any are connectivity-related, cross-check with
   `get_remote_networks(state="down")` for a down tunnel that explains them.
4. **Aggregate-view caveat**: if the response carries `severity_unavailable`,
   this tenant only exposes alert counts (by MU/RN/SC) on the mapped view.
   Report the counts, say severity cannot be broken down yet, and (once) run
   `discover_insights(kind="alerts_detail")` to look for the per-alert view.

## Runbook D — "容量 / how many users are connected"

1. `get_connected_users()` — total, trend, by-location.
2. If `trend_1h_pct` is sharply negative during business hours, that can signal a
   connectivity problem, not just people logging off — check `query_alerts`.
3. For capacity framing, compare peak against known licensed seats (ask the user
   if unknown; the tool doesn't know the license count).

## Runbook E — first run against a new tenant (bring-up)

1. `--selfcheck` (terminal) — confirm interpreter, packages, credentials.
   Credentials belong in the plugin enable dialog (marketplace installs) or
   `~/.prisma-sase.env` (chmod 600) where there is no dialog. Note that a
   selfcheck run from a plain shell cannot see dialog-supplied values — see
   the Skill's credential-handling rules before concluding they are missing.
   On macOS, GUI apps often do NOT inherit `launchctl setenv`, so don't debug
   that path first.
2. `discover_insights()` — find which Insights resource/view names this tenant
   accepts. Check `control_probe_ok` first: if the control failed, fix
   auth/region before trusting any naming conclusion.
3. Adopt `suggested_insights_map` as a one-line `PRISMA_INSIGHTS_MAP=` entry in
   `~/.prisma-sase.env`; restart the Claude app so the server reloads.
4. `get_sase_status()` — verify the headline reflects real data (no PARTIAL /
   UNKNOWN, no `field_note`).
5. If alerts show `unrecognized severity` or experience shows `no_data_debug`,
   relay those field lists back to the plugin maintainer to fix the mappings.

## Runbook F — a tool returns HTTP 400

1. Read the error `hint`: if it names an unverified resource/view, this is a
   naming issue, not an outage → `discover_insights(kind=<that kind>)`.
2. If `discover_insights` shows even the control probe failing, the problem is
   auth/region/permissions → `--selfcheck`, verify region and the read-only
   role, then retry.
3. Never present a 400 as "the tenant has a problem" — it is a plugin↔tenant
   mapping issue until proven otherwise.

## Multi-tenant note

For "check customer X", pass `tsg_id=<their TSG>` (and `region` if it differs) to
any tool. Without them, the default tenant from the environment is used.
