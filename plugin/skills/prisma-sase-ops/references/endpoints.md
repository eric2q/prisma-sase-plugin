# Endpoints & API mapping

How each MCP tool maps to the underlying Prisma SASE API, plus the tenant items
still to confirm. (Auth facts are verified per design doc sec.3 and are handled
inside the server — you never build a token or a header yourself.)

## Tool → API

| Tool | API family | Method & path | Notes |
|---|---|---|---|
| `get_sase_status` | Insights 3.0 + ADEM | several, in parallel | Aggregates alerts, connectivity, users, experience |
| `query_alerts` | Insights 3.0 | `POST /insights/v3.0/resource/query/<resource>/<view>` | Filter payload, time-windowed |
| `get_connected_users` | Insights 3.0 | `POST /insights/v3.0/resource/query/<resource>/<view>` | Mobile Users |
| `get_remote_networks` *(status only in P1)* | Insights 3.0 | `POST .../query/<resource>/<view>` | Tunnel up/down |
| `get_user_experience` | ADEM Telemetry v2 | `GET /adem/telemetry/v2/measure/agent/score` | `start`/`end` epoch, `endpoint-type`, `response-type` |

## Insights 3.0 filter syntax (confirmed shape)

Body is a `filter` object with a `rules` array. Each rule = `property`,
`operator`, `values` (array). Rules combine with boolean AND by default.

```json
{
  "filter": {
    "rules": [
      { "property": "event_time", "operator": "last_n_hours", "values": [24] },
      { "property": "severity",   "operator": "in",           "values": ["critical", "high"] }
    ]
  }
}
```

Operators available: `equal`, `not_equal`, `in`, `not_in`, `greater`,
`greater_or_equal`, `less`, `less_or_equal`; time: `last_n_hours`,
`last_n_days`, `last_n_weeks`, `between`.

## ADEM score query (confirmed shape)

```
GET /adem/telemetry/v2/measure/agent/score
    ?start=<epoch>&end=<epoch>&endpoint-type=muAgent&response-type=summary
```

The server fills `start`/`end` from the `hours` window automatically.

## ⚠️ Resource/view names: current live-verification state

Live results from the live tenant, region `sg` (2026-07-23, two rounds —
now baked in as the shipped defaults):

| Kind | Shipped default | Live status |
|---|---|---|
| alerts | `alerts/alerts_list` | ✅ works, but it is an **AGGREGATE** view (total/mu/rn/sc counts — no per-alert severity) |
| alerts_detail | `alerts/alert_list` (candidate) | ❓ per-alert view **not yet identified** — probe with `discover_insights(kind="alerts_detail")` |
| connected_users | `users/users_list` | ✅ confirmed (**needs time filter**; appears to be per-user rows) |
| remote_networks | `tunnels/tunnel_list` | ✅ confirmed, 13 rows (**needs time filter**; up/down via `tunnel_state_name`; throughput fields are **Kbps** — tool renames them to `*_kbps`) |
| (control) | `applications/application_list` | documented in public docs |

Note the naming pattern: the working views are `application_list`,
`users_list`, `tunnel_list` — when probing a new tenant expect the
`<singular>_list` form more often than `<plural>s_list`. Views that rejected
this tenant: `mobile_users/*`, `remote_networks/*`, `sites/site_list`,
`agent_users/*`, `branch_users/*`, `tunnels/tunnels_list`.

The client auto-injects a `last_n_hours` time filter when a caller passes no
rules (some views 400 on an empty filter), and retries once with an empty
filter if the injected one is rejected — matching what discovery probes.

**Don't guess by hand — run `discover_insights`.** It probes candidates
read-only (including `<singular>_list` variants, matching the documented
`applications/application_list` pattern), uses the control probe to separate
auth/region problems from naming problems, shows each working view's real
field names, and returns a ready `suggested_insights_map`. Adopt it by adding
one line to `~/.prisma-sase.env`:

```
PRISMA_INSIGHTS_MAP={"connected_users":{"resource":"<real>","view":"<real>","verified":true},"remote_networks":{"resource":"<real>","view":"<real>","verified":true}}
```

Filter **property names** (`event_time`, `severity`, `state`) are likewise
tenant/version dependent → `PRISMA_FILTER_TIME_PROP` /
`PRISMA_FILTER_SEVERITY_PROP` / `PRISMA_FILTER_STATE_PROP`. Record **field
names** in responses can differ too — `query_alerts` tries several severity
field candidates and, if none match, returns a `field_note` listing the
record's actual fields; `get_user_experience` returns `no_data_debug` with the
response keys when the score is null. Relay those to the plugin maintainer so
defaults can be fixed.

The ADEM per-user parameter name is a placeholder (`user`) until confirmed;
override behaviour is documented in the runbooks.
