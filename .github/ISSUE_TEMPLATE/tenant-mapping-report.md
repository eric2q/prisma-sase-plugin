---
name: Tenant mapping report
about: Report a working (or failing) Insights resource/view name for your tenant,
  so it can become a shipped default
title: "[mapping] <kind>: <resource>/<view> on tenant version <region/version>"
labels: tenant-mapping
---

<!-- Thank you! Working names reported here become shipped defaults for
     everyone on your tenant version. NEVER include credentials, tokens,
     TSG IDs, or response values containing user data — names and field
     lists only. -->

## What I probed

- Plugin version (`get_sase_status` → `plugin_version`, or `--selfcheck` header):
- Tenant region (e.g. `sg`, `us`, `de`):
- How found: `discover_insights` / SASE UI dev-tools capture / other:

## Result

- Kind (`alerts_detail` / `connected_users` / `remote_networks` / other):
- Resource / view (leave view empty for single-segment resources):
- Outcome: ✅ works / ❌ DATA10003 (absent) / ⚠️ GCP10002 (field mismatch)
- Payload variant that worked (`empty_filter` / `time_filter` / properties needed):
- `sample_fields` from discovery, or field names seen in the UI capture
  (names only, no values):

## PRISMA_INSIGHTS_MAP line I'm using (if adopted)

```
PRISMA_INSIGHTS_MAP=
```
