# Changelog

## 0.6.7 — 2026-07-24

Discovery no longer over-recommends PRISMA_INSIGHTS_MAP.

- **CHG:** `discover_insights` now compares each discovered mapping against
  the shipped `config.INSIGHTS_MAP` defaults. Names that already match a
  built-in **verified** mapping are reported under a new
  `matches_shipped_defaults` field with a "no PRISMA_INSIGHTS_MAP needed"
  note, instead of being included in `suggested_insights_map`. Only genuinely
  new or shipped-as-unverified mappings (e.g. `alerts_detail`) are suggested
  for persistence. Previously discovery told every user to set the env var
  even when the result was identical to the defaults.
- **CHG:** SKILL.md decision tree: relay `matches_shipped_defaults` as
  "no env change needed"; only persist `suggested_insights_map` entries.

## 0.6.6 — 2026-07-24

PANW API landscape survey consolidated into the Skill.

- **NEW:** `skills/prisma-sase-ops/references/api-catalog.md` — every Prisma
  SASE API family published on pan.dev (surveyed 2026-07-24): Insights 3.0,
  ADEM, Service Status, Subscription, Aggregate/Interconnect Monitoring,
  Tenancy, IAM, Prisma Access Configuration, SCM Operations, SD-WAN
  (unified + legacy), 5G Monitor, SSPM — each with base path, purpose, and a
  coverage mark (implemented / partial / read-only candidate / not planned /
  excluded-by-design). Includes documented Insights 3.0 resource-view names,
  the legacy Insights 1.0/2.0 base-URL note (API-generation mismatch
  diagnosis), the Phase-2 read-only menu, and source links.
- **DOC:** SKILL.md references the catalog; endpoints.md carries a scope note
  pointing to it; plugin/README tools section links the coverage picture;
  root README (EN + zh-TW) links the catalog under the plugin table.

## 0.6.5 — 2026-07-24

Credentials documentation: illustrated API-key walkthrough (from the Windows
deployment guide v0.5.0).

- **NEW:** `plugin/docs/images/` — four schematic SCM screenshots
  (tenant identifiers masked, red badges ①–⑤ numbering the flow):
  System Settings → IAM menu, Identity Information, Client Credentials,
  Assign Roles.
- **DOC:** root README (EN + zh-TW) gains a full **"Getting the API key
  (read-only service account)"** section — the four SCM wizard steps with
  figures, the secret-shown-only-once warning (copy / Download CSV File /
  rotate-if-lost), TSG ID = the digits after `@` in the Client ID, the
  "Assign Roles says Optional but is required (no role = 403)" trap,
  View Only Administrator + least-privilege guidance, and the
  never-paste-the-secret-into-chat rule.
- **DOC:** plugin/README Step 3 expanded from two lines into the same
  illustrated four-step walkthrough (images ship inside the plugin, so the
  standalone .plugin packages carry them too).

## 0.6.4 — 2026-07-24

Prerequisite guidance: assume the user may have NOTHING installed (not even
Python) and guide every gap to resolution instead of dying with a raw error.

- **NEW:** root README (EN + zh-TW) gains a **Prerequisites** section: a
  check-it / fix-it table for Python ≥ 3.10, venv+pip, PyPI network access,
  and git — with per-OS install commands (brew / python.org / apt / dnf),
  the macOS python3.9 trap, the Windows Store-alias trap, and the
  `PRISMA_MOCK=1` no-tenant tryout path.
- **CHG:** `install.sh` failure paths are now guided, not fatal-and-cryptic:
  OS-aware "no Python" instructions (brew / apt / dnf / python.org),
  a pre-check for Debian/Ubuntu's missing `ensurepip` (`python3-venv`) with
  the exact apt command, venv-creation failure hints (permissions /
  `PRISMA_VENV`), and pip-install failure hints (offline / `HTTPS_PROXY`,
  safe-to-re-run note). pip self-upgrade failure downgraded to a warning.
- **CHG:** `install.bat` mirrors the same guidance (venv failure → Store-alias
  hint + `PRISMA_VENV`; dependency failure → proxy/offline hint; re-run safe).
- **DOC:** plugin/README Requirements notes the Debian/Ubuntu venv/pip split.

## 0.6.3 — 2026-07-24

Project-review cleanup: one correctness fix, docs refreshed, bilingual landing
page.

- **FIX:** `query_alerts` local severity/state filtering (the fallback path
  used when the view rejects those filter rules) now runs on the **full record
  set before truncation**. Previously it filtered the already-`limit`-capped
  rows, so matches beyond the first `limit` records were silently dropped and
  `total_matched` was under-counted.
- **DOC:** repo-root README rewritten in English as the default landing page,
  with a language switcher to the new full Traditional Chinese version
  (`README.zh-TW.md`).
- **DOC:** install.sh / install.bat completion messages now lead with the
  marketplace install (Add from a repository) and mention the standalone
  file-upload build only as the no-git fallback; plugin/README no longer
  references the retired single `prisma-sase.plugin` filename.
- **DOC:** root README repo-layout note corrected (3 catalog entries, not 2);
  endpoints.md no longer claims `get_sase_status` fans out in parallel (its
  sub-queries are sequential, best-effort).

## 0.6.2 — 2026-07-24

Catalog rename (distribution only — no code changes).

- **CHG:** marketplace entries are now OS-explicit: `prisma-sase-mac`,
  `prisma-sase-linux`, `prisma-sase-windows` (mac/linux share the bash
  launcher; windows uses cmd). Anyone who installed the old `prisma-sase`
  entry should uninstall it and install the entry matching their OS after
  updating the marketplace.
- **CHG:** `tools/build-standalone.py` now emits three .plugin files.


## 0.6.1 — 2026-07-24

Distribution change only — no tool behavior changes.

- **NEW:** GitHub **plugin-marketplace** distribution. The repo root carries
  `.claude-plugin/marketplace.json` with two catalog entries (`prisma-sase`
  for macOS/Linux, `prisma-sase-windows` for Windows) sharing ONE code tree —
  each entry embeds its own launcher via `strict: false` + inline `mcpServers`.
  Push to GitHub = release; users update via the Plugins UI or
  `/plugin marketplace update`.
- **CHG:** `plugin/.mcp.json` and `plugin/.claude-plugin/plugin.json` removed
  from the code tree (the catalog entries own identity + launch config).
  Standalone file-upload packages are still available via
  `tools/build-standalone.py`, which generates both manifests from
  `marketplace.json` so the two install paths cannot drift.

## 0.6.0 — 2026-07-23

Driven by the throughput-units field report: `avg/peak_throughput` are **Kbps**
per SCM docs / pan.dev schema, but were passed through as bare numbers —
trivially misread as Mbps (8042.58 → "8 Gbps", an 8000× error that contradicts
physical uplink limits).

- **BREAKING (key rename):** `get_remote_networks` tunnel rows now emit
  `avg_throughput_kbps` / `peak_throughput_kbps` (and newly exposed
  `p95_throughput_kbps`) instead of the bare-named fields — the unit lives in
  the key so it cannot be dropped.
- **NEW:** every `get_remote_networks` response carries a `units` block
  (kbps, peak = max per-minute sample within the time bucket, bucket
  granularity by window).
- **NEW:** `p95_throughput_kbps` exposed (better than peak for capacity
  sizing). Byte/packet fields remain filtered; documented for future opt-in.
- **CHG:** server tool description states the unit up front so the model knows
  before ever seeing data; module/function docstrings document unit, peak
  semantics, bucket granularity, and the bytes→Kbps conversion.
- **CHG:** Skill updated — SKILL.md output convention (present as Mbps ÷1000
  with the unit written out; physical-uplink sanity check), thresholds.md
  gains a "Throughput units & semantics" section, endpoints.md notes Kbps.
- **CHG:** mock tunnel values corrected to realistic Kbps scale so offline
  demos read correctly.

## 0.5.0 — 2026-07-23

Windows support. The Python server was already cross-platform; the launcher
layer was not (bash-only).

- **NEW:** `mcp/run.cmd` — Windows launcher mirroring `run.sh`'s interpreter
  pick order (`PRISMA_PYTHON` → `%USERPROFILE%\.prisma-sase-venv` →
  `py -3.13…-3.10` → `python`).
- **NEW:** `install.bat` — Windows one-shot setup (venv + deps +
  `%USERPROFILE%\.prisma-sase.env` template + mock selfcheck), with a
  Microsoft-Store-python-stub warning.
- **NEW:** separate package variant `prisma-sase-windows.plugin` whose
  `.mcp.json` starts the server via `cmd /c mcp\run.cmd`. Shipping a second
  artifact avoids asking Windows users to edit the post-upload internal config
  copy (the round-1 issue-7 lesson). Same code, same version, different
  launcher wiring.
- **CHG:** README gains a full Windows install section (python.org, Store
  alias trap, `setx`/env-file credentials); version guard message now names
  install.bat / python.org on Windows.
- **NOTE:** the Windows scripts are untested on a real Windows machine —
  written to mirror the verified macOS flow; field reports welcome.

## 0.4.0 — 2026-07-23

Driven by the round-2 live run: all three v0.3.0 fixes confirmed working;
discovery identified the tenant's real view names, which exposed two code
bugs — both fixed, and the verified mappings are now the shipped defaults.

- **FIX (BUG-1, blocking):** views like `tunnels/tunnel_list` reject an empty
  filter with HTTP 400. The client now injects a default `last_n_hours` time
  filter when a caller passes no rules, and retries once with an empty filter
  if the injected one is rejected (matching what discovery probes). The
  connectivity check therefore works, and the misleading "verify region" 400
  hint now leads with payload/mapping causes + a discovery pointer.
- **NEW:** `get_remote_networks` tool — per-tunnel rows (site, name, node_type
  RN/SC, transport, up/down via `tunnel_state_name`, monitoring state,
  throughput, endpoints), with a `state="down"` filter. Tunnel row data is now
  actually reachable (previously only counts via the status headline).
- **FIX (BUG-2):** `alerts/alerts_list` on the live tenant is an AGGREGATE view
  (total/mu/rn/sc counts — structurally no per-alert severity). `query_alerts`
  now tries an `alerts_detail` mapping first and otherwise returns honest
  `summary_counts` with `severity_unavailable: true` instead of
  `{unknown: N}`; the status headline reports "severity breakdown unavailable"
  rather than implying an unclassified alert. Detail-view candidates
  (`alert_list`, `alert_detail`, …) added to `discover_insights(kind="alerts_detail")`.
- **CHG:** live-verified mappings baked into defaults: `users/users_list`
  (connected users, per-user rows counted correctly) and `tunnels/tunnel_list`
  (remote networks). Discovery suggestions now include the working
  `payload` variant.
- **CHG:** mock data mirrors the live shapes (aggregate alerts view, tunnel
  field names) so offline demos exercise the same code paths as production.

## 0.3.0 — 2026-07-23

Driven by the first LIVE tenant run (the live tenant (region sg)): auth + region
+ payload verified end-to-end (alerts returned real data); remaining issues
were endpoint naming, a misleading headline, and credential delivery.

- **FIX:** `get_sase_status` headline is now derived from actual section
  outcomes — UNKNOWN when all checks fail, PARTIAL when some fail or lack data,
  plus a machine-readable `checks` summary. It previously said "Healthy" even
  when every section errored.
- **NEW:** `discover_insights` tool (and `server.py --discover` CLI): read-only
  probing of candidate Insights resource/view names (incl. `<singular>_list`
  variants per the documented `applications/application_list` pattern), a
  documented control probe to separate auth problems from naming problems,
  per-view real field names, and a paste-ready `PRISMA_INSIGHTS_MAP` suggestion.
- **CHG:** `~/.prisma-sase.env` is now the PRIMARY credential path (macOS GUI
  apps are not guaranteed to inherit `launchctl setenv` — field-verified).
  `install.sh` creates a chmod-600 template; error hints point to it; the env
  loader skips empty template values.
- **FIX:** Insights 400/404 errors on unverified mappings now carry the
  "best-guess name" hint + discovery pointer in the error itself (previously
  the `_verify` note only appeared on successful responses).
- **CHG:** `alerts/alerts_list` marked live-verified. `query_alerts` reads
  severity/message/id/time through field-name candidates and returns a
  `field_note` with the record's real fields when severity is unclassifiable
  (live tenant showed `{unknown: 1}`).
- **CHG:** `get_user_experience` returns `no_data_debug` (response keys only,
  no values) when the score is null, instead of a bare null.
- Credentials remain env/env-file only — deliberately NOT tool parameters, so
  secrets never travel through the conversation.

## 0.2.0 — 2026-07-23

Fixes driven by the first real-world install (macOS / Apple Silicon, Claude
Desktop, plugin uploaded from file). Full detail in the install report.

- **FIX (blocking):** removed the `${...}` env block from `.mcp.json`. Hosts can
  pass those placeholders through verbatim, so the server authenticated with the
  literal string `${PRISMA_TSG_ID}` → HTTP 401. The server now inherits its
  environment; an optional `~/.prisma-sase.env` / `PRISMA_ENV_FILE` file covers
  hosts that don't forward it.
- **FIX (blocking):** `.mcp.json` no longer hard-codes `command: "python3"`
  (macOS system 3.9 < fastmcp's 3.10 floor → silent startup death, tools never
  appear). New `mcp/run.sh` launcher picks an interpreter:
  `PRISMA_PYTHON` → `~/.prisma-sase-venv/bin/python` → `python3.13…3.10` → `python3`.
- **NEW:** hard Python ≥ 3.10 guard at the top of `server.py` with an exact,
  actionable stderr error (version found, path, three fixes).
- **NEW:** unexpanded-`${...}` placeholder detection — treated as unset and named
  explicitly in selfcheck and tool errors instead of surfacing a confusing 401.
- **NEW:** `server.py --selfcheck` — interpreter / packages / env file /
  credentials / placeholder report ending in READY / NOT READY.
- **NEW:** `install.sh` — one-shot venv creation + dependency install + mock
  selfcheck; prints exact next steps.
- **NEW:** README rewritten around the real Desktop flow: Settings → Plugins →
  **Upload from file** (project folder ≠ install; marketplace = git only), the
  post-upload internal-copy location, and a symptom→fix troubleshooting table.
- **CHG:** `fastmcp` requirement widened to `>=2,<4` (3.4.4 verified working in
  the field).

## 0.1.0 — 2026-07-23

Initial Phase 1 PoC: read-only FastMCP server (stdio) with `get_sase_status`,
`query_alerts`, `get_connected_users`, `get_user_experience`; token cache with
auto-renew; response slimming; offline mock mode; `prisma-sase-ops` Skill
(decision tree, thresholds, runbooks, weekly-report template).
