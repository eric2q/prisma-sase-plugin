# Prisma SASE API catalog — the full PANW API landscape

A survey of every Prisma SASE API family published on pan.dev (surveyed
2026-07-24), and where this plugin sits in that landscape. Use this to answer
"can the plugin do X?", "what else could be queried?", and "why is Y excluded?".

Unless noted, every family shares the **unified SASE mechanics** this plugin
already implements in `auth.py`/`client.py`:

- Base URL: `https://api.sase.paloaltonetworks.com`
- OAuth2 `client_credentials` at
  `https://auth.apps.paloaltonetworks.com/oauth2/access_token`,
  scope `tsg_id:<TSG_ID>`, ~15-minute tokens
- Service-account + role model (see the README API-key walkthrough)

## Coverage legend

| Mark | Meaning |
|---|---|
| ✅ | implemented in this plugin today |
| ◐ | partially implemented (family used, more endpoints available) |
| ○ | read-only candidate — fits the plugin's design, not yet built |
| ❌ | not planned (niche / different product area) |
| 🚫 | excluded **by design** — write/config path; the read-only guarantee forbids it |

## API families

| API family | Base path | What it offers | Plugin |
|---|---|---|---|
| **Authentication Service** | `auth.apps.paloaltonetworks.com/oauth2/access_token` | OAuth2 token issuance for all unified SASE APIs | ✅ `auth.py` |
| **Prisma Access Insights 3.0** | `/insights/v3.0/resource/query/{resource}/{view}` | Tenant health telemetry: alerts, tunnel status & bandwidth, connected users, sites, applications, PAB events. JSON filter query language | ✅ core — `query_alerts`, `get_remote_networks`, `get_connected_users`, `get_sase_status`, plus `discover_insights` probing |
| **Autonomous DEM (ADEM)** | `/adem/telemetry/v2/...` | Digital-experience timeseries: agent/app experience scores, application metrics, traffic-flow measurements; `endpoint-type` selects MU agents vs Remote Networks | ◐ `get_user_experience` uses `/measure/agent/score`; documented siblings: `/measure/application/metric` (app + internet metrics), `/measure/nav/traffic` (flow measurements from firewall logs via ADEM probes) |
| **SASE Service Status** | `https://sase-secondary.status.paloaltonetworks.com/api/v2/{status,components,incidents/unresolved}.json` | PANW's own service-status page as JSON: overall indicator (none/minor/major/critical), per-component status, unresolved incidents, scheduled maintenance. **No auth needed** | ○ strong candidate — would answer "is the problem on PANW's side?" with zero credentials |
| **Subscription Service** | `/subscription/v1/...` | Licenses/quotas assigned to TSGs | ○ read-only license/quota queries would fit |
| **Aggregate Monitoring** (multitenant) | `/mt/monitor/v1/agg/<path>?agg_by=tenant` | MSP cross-tenant aggregates: alerts list, license quota/utilization, tenant list, mobile-gateway status, URL summaries. Requires `X-PANW-Region` header (client already sends it) | ○ Phase-2 candidate for MSP/multi-tenant demos |
| **Interconnect Monitoring** | `/mt/monitor/v1/interconnect/...` | Ingress/egress throughput of interconnect connections | ○ niche sibling of the above |
| **Tenancy Service** | `/tenancy/...` | Create/list/manage the TSG hierarchy (tenants, sub-tenants) | ❌ management-plane admin, not ops monitoring |
| **Identity & Access Management (IAM)** | `/iam/...` | Service accounts, roles, permissions, access policies | ❌ used **once, manually** to create the read-only service account (README walkthrough); not a runtime concern |
| **Prisma Access Configuration** | `/sse/config/v1/...` (formerly `/config/v1/...`) | Full tenant configuration: remote networks, service connections (+BGP, SC groups), mobile agent/GlobalProtect, locations, auth/cert profiles, onboarding (`/enable`) | 🚫 config plane — even though GETs exist, Phase 1 deliberately ships **no** config-plane access |
| **SCM Configuration Operations** | config versions / candidate config / **push** / jobs | The commit pipeline: build a candidate config, push it, track jobs | 🚫 the exact write path the read-only guarantee exists to exclude |
| **Prisma SD-WAN (unified)** | `/sdwan/v4.x/api/...`, `/sdwan/monitor/v2.0/...` | Branch SD-WAN: sites, elements, interfaces, events, monitor metrics; ADEM has SD-WAN-flavored endpoints too | ○ Phase 2 (SKILL.md already announces branch-device tools) |
| **Prisma SD-WAN (legacy)** | `api.hood.cloudgenix.com/v2.x/...` | Pre-2022 CloudGenix API; different auth and base URL | ❌ superseded by unified |
| **SASE 5G Monitor Service** | `/sase/api/monitor-services-5g/...` | 5G subscriber/slice monitoring | ❌ niche |
| **Identity SSPM** | (identity-sspm) | SaaS Security Posture Management incidents | ❌ different product area |

## Insights 3.0: documented resources & views (public docs)

Naming is tenant/version dependent — this is why `discover_insights` exists.
Names actually documented on pan.dev:

- `applications/application_list` — the documented example; this plugin's
  **control probe**
- `sites/site_count` — number of sites
- `sites/site_status` — status of Sites / Remote Networks / Service Connections
  (includes data-center listing)
- `users` active-user list view (per-user rows with connection details)
- `users/branch_connected_entity_count` — connected entities for branch users
- Named "general resources" in the query-language docs: `tunnel_status`,
  `open_alerts_count_timeseries`, `prisma_sase_external_alerts_current`;
  custom resources like `location_rn_bandwidth`,
  `location_gp_mobile_users_logins`

Live-verified on a real tenant by this plugin (see `config.INSIGHTS_MAP`):
`users/users_list`, `tunnels/tunnel_list`, `alerts/alerts_list` (aggregate).

## Legacy Insights 1.0 / 2.0 (context for older tenants)

Panorama-managed / pre-TSG tenants use a **different base URL and shape**:
`https://pa-<region>.api.prismaaccess.com/api/sase/v{1,2}.0/resource/query/...`
(1.0 adds `/tenant/{super_tenant_id}` and an Insights-UI API key instead of
OAuth2). Resources there include `prisma_sase_external_alerts_current` —
**per-alert rows with severity**. This plugin targets 3.0 only; if a tenant
rejects 3.0 everywhere (control probe fails with valid auth), it may be a 1.0/
2.0-era tenant — that's an API-generation mismatch, not a mapping problem.

## What "read-only by design" means against this catalog

The plugin's client can only build Insights **query** POSTs and ADEM **GETs**
(`client.py`). Everything marked 🚫 is not just unimplemented — there is no
code path capable of reaching it. Families marked ○ can be added without
weakening that guarantee (they are query/GET families), which is the Phase-2
menu: Service Status (no-auth outage check), ADEM application metrics,
Aggregate Monitoring for MSP, SD-WAN monitor, Subscription quotas.

## Sources

- pan.dev — Prisma SASE welcome / Get Started (base URL, OAuth2, TSG scope):
  https://pan.dev/sase/docs/ , https://pan.dev/sase/docs/getstarted/
- Insights 3.0: https://pan.dev/access/api/insights/ ,
  https://pan.dev/access/docs/insights/getting_started-30/ ,
  https://pan.dev/access/docs/insights/query_language_resources/
- Insights 1.0/2.0 (legacy): https://pan.dev/access/docs/insights/getting_started-20/
- ADEM: https://pan.dev/access/docs/adem/ ,
  https://pan.dev/access/api/adem/autonomous-dem-api/
- Aggregate Monitoring: https://pan.dev/sase/docs/mt-monitor/
- Tenancy / TSG: https://pan.dev/sase/docs/tenant-service-groups/
- IAM & roles: https://pan.dev/sase/api/iam/ , https://pan.dev/sase/docs/roles/
- Subscription: https://pan.dev/sase/api/subscription/
- Prisma Access Configuration: https://pan.dev/access/api/prisma-access-config/
- SCM Operations: https://pan.dev/scm/api/config/sase/operations/operations-api/
- SD-WAN: https://pan.dev/sdwan/docs/ , https://pan.dev/sdwan/api/
- Service Status: https://pan.dev/sase/docs/saseservicestatusapi/
