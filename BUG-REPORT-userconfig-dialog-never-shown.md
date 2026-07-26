# Bug Report — plugin `userConfig` dialog is never presented; placeholders expand to empty strings

**Component:** Claude Desktop — plugin host (local-agent / Cowork session surface)
**Affected plugin:** `prisma-sase-mac` v0.8.7 (manifest declares `userConfig` correctly)
**Reported by:** Eric (Solutions Consultant, Palo Alto Networks)
**Date:** 2026-07-27
**Severity:** High — every tool in the plugin fails; no in-product path to recover

---

## Summary

A plugin whose manifest declares `userConfig` is loaded and started by the host,
but the host **never presents the enable dialog** that would collect those
values. The `${user_config.*}` references in `mcpServers.env` are then expanded
to **empty strings** and passed to the MCP server, which starts successfully but
has no credentials and fails every call.

The failure is silent in both directions: the host reports the plugin as
installed and running, and the Plugins detail screen displays the credential
variables as fixed-length masked dots — visually identical to a correctly
configured plugin. There is no indication that configuration was never
collected, and no visible way to trigger the dialog after the fact.

This is distinct from a placeholder-expansion bug. The host **does** understand
`${user_config.*}` syntax; it substitutes them. It simply substitutes nothing,
because it never asked the user for anything.

---

## Impact

- All 4 tool families of the plugin fail (`alerts`, `connectivity`,
  `connected_users`, `experience`). The plugin is 100% unusable.
- The user cannot self-diagnose. The settings UI positively suggests the
  credentials *are* configured.
- The user cannot self-recover through the product. The only workarounds are
  out-of-band (a credential file on disk, or environment variables), which
  defeats the purpose of `userConfig` and pushes secrets out of OS secure
  storage and into plaintext files.

---

## Environment

| | |
|---|---|
| Host | Claude Desktop, macOS, local-agent / Cowork session |
| Plugin load path | `~/Library/.../Claude-3p/local-agent-mode-sessions/<id>/cowork_plugins/cache/prisma-sase/prisma-sase-mac/0.8.7/` |
| Install method | marketplace-style cache (**not** `--plugin-dir` sideload) |
| Plugin version | 0.8.7 |
| MCP server | Python, launched via `bash ${CLAUDE_PLUGIN_ROOT}/mcp/run.sh` |

The load path matters: the plugin's own 0.8.7 release fixed a *different*
credential bug that only affected `--plugin-dir` sideloading. This report is
about the marketplace-cache path, which that fix does not touch.

---

## Evidence

### 1. The manifest declares `userConfig` correctly

`plugin/.claude-plugin/plugin.json` (v0.8.7) declares all four keys
(`client_id`, `client_secret` with `sensitive: true`, `tsg_id`, `region`) and
references them from `mcpServers.prisma-sase.env`:

```json
"env": {
  "PRISMA_CLIENT_ID":     "${user_config.client_id}",
  "PRISMA_CLIENT_SECRET": "${user_config.client_secret}",
  "PRISMA_TSG_ID":        "${user_config.tsg_id}",
  "PRISMA_REGION":        "${user_config.region}"
}
```

Every placeholder resolves against a declared key. The plugin's own regression
suite (`UserConfigBinding`) enforces this and passes.

### 2. The server starts and reads the manifest

```json
{"ok": true, "plugin_version": "0.8.7", ...}
```

So the manifest was parsed and the `mcpServers` block was honoured. The failure
is not a load failure.

### 3. Every tool fails for missing credentials

```
Missing required context: PRISMA_TSG_ID (or the tsg_id argument)
```

…returned by all four sections.

### 4. The values arrived EMPTY, not as literal placeholders — this is the crux

The plugin distinguishes these two cases deliberately. `config.py` matches any
value of the form `${...}` (including dotted `${user_config.x}` names) and, when
it finds one, prefixes the error hint with an explicit
*"arrived as literal `${...}` placeholders"* message.

**That prefix is absent** from the observed error. Therefore
`PLACEHOLDER_VARS` is empty, therefore no environment variable held a literal
`${user_config.*}` string.

The host expanded the placeholders. It expanded them to nothing.

### 5. Corroboration: `PRISMA_REGION` was *not* reported missing

`_require_ctx()` checks TSG **and** region and names both when both are absent.
The error names only `PRISMA_TSG_ID`, so region was non-empty.

Region's only other possible source on this machine is the credential-file
template created by the plugin's `install.sh`, which ships with
`PRISMA_REGION=sg` pre-filled while the other three lines are blank (blank lines
are skipped by design, so they never mask an incoming value).

This independently confirms the direction of the fault: the three values that
could *only* have come from the host are empty, and the one value that had a
non-host fallback is present.

### 6. The settings UI cannot distinguish configured from unconfigured

The Plugins detail screen renders the `mcpServers.env` block as:

```
PRISMA_CLIENT_ID=●●●●●●●●
PRISMA_CLIENT_SECRET=●●●●●●●●
PRISMA_TSG_ID=●●●●●●●●
PRISMA_REGION=●●●●●●●●
```

All four masks are the same length, though the real values differ in length by
an order of magnitude (`sg` is 2 characters; a client ID is ~45). The mask is
fixed-width and content-independent, so it conveys no information about whether
a value exists at all.

It also shows raw environment-variable names rather than the human-readable
`title` strings declared in `userConfig` ("Prisma SASE Client ID", etc.),
reinforcing the impression that this is a settings *form* when it is a read-only
view of the manifest.

**This screen is what caused the user to believe credentials had been provisioned
without their knowledge.** The actual state was that none had ever been entered.

---

## Root cause (hypothesis)

The enable flow that collects `userConfig` is not run on this install surface.
`userConfig` support appears to be wired to a specific install path; on the
local-agent / Cowork marketplace-cache path the plugin is activated directly,
and placeholder substitution proceeds against an empty configuration store.

The host developers can confirm this quickly by checking whether any persisted
config store contains a `userConfig` entry for this plugin. The expectation
under this hypothesis is that no such entry exists.

---

## Requested changes

Ordered by importance. Items 1 and 2 are correctness; 3 and 4 are the
difference between a user recovering on their own and filing this report.

### 1. Run the `userConfig` collection flow on every surface that can enable a plugin

**Why:** `userConfig` is the only credential mechanism that keeps a secret in OS
secure storage. A surface that activates plugins but skips the collection flow
silently downgrades every plugin that depends on it.

**Purpose:** A plugin author declares `userConfig` once and can rely on it
regardless of how the user installs. Today the declaration is honoured on some
paths and ignored on others, with no signal to author or user.

### 2. Never expand a missing required `userConfig` value to an empty string

Either block enable until required values are supplied, or leave the variable
unset and surface the reason.

**Why:** Empty-string expansion is the least recoverable failure mode available.
It is indistinguishable from "the user submitted a blank field", it destroys the
information the server needs to explain itself, and it specifically defeats
plugins that already guard against unexpanded placeholders — this plugin has such
a guard, and it could not fire.

**Purpose:** Turn a downstream, misattributed credentials error into an
actionable, correctly-attributed configuration error at the point of failure.

**Related:** consider marking `userConfig` entries as required (the schema has no
`required` flag today), so the host knows which values must block activation.

### 3. Show real configuration state in the Plugins detail screen

Render the declared `userConfig` fields using their `title`, each with an
explicit **Configured / Not configured** state. Keep secret values masked — the
ask is to distinguish *empty* from *set*, not to reveal anything. Do not present
the raw `mcpServers.env` block as though it were user-supplied settings.

**Why:** The current screen states the opposite of the truth. It showed four
masked values for four values that did not exist.

**Purpose:** Make "is this plugin configured?" answerable in the UI, which is
where a user will look first.

### 4. Provide a way to re-open the configuration dialog

An **Edit / Configure** affordance on the plugin's detail screen, not gated on
uninstall-and-reinstall.

**Why:** Credentials rotate, get typo'd, and — as here — are sometimes never
collected. A one-shot dialog at install time with no re-entry means the only
recovery is a destructive reinstall.

**Purpose:** Make configuration a normal, repeatable operation.

---

## Reproduction

1. Publish a plugin whose `plugin/.claude-plugin/plugin.json` declares
   `userConfig` and references `${user_config.*}` from `mcpServers.env`.
2. Install it on the local-agent / Cowork surface via the marketplace path
   (so it lands under `cowork_plugins/cache/...`).
3. Observe that no configuration dialog is presented at any point.
4. Fully quit and relaunch the app.
5. Call any tool → fails for missing credentials. Inspect the server's
   environment: the variables are present but empty, not literal placeholders.
6. Open Settings → Plugins → the plugin. The env block shows four equal-length
   masked values, suggesting configuration that does not exist.

---

## Notes for triage

- Not a regression in the plugin. Manifest, placeholder references and the
  regression suite covering them are all correct in 0.8.7.
- Not the sideload bug fixed in plugin 0.8.7 — that one affected `--plugin-dir`
  and produced *literal* `${user_config.*}` strings. Opposite signature.
- Not stale-process related. A full Cmd+Q relaunch was performed.
- Not the pre-0.2.0 `.mcp.json` `${PRISMA_*}` issue, which produced HTTP 401 with
  a literal placeholder in the message.

### Verification of the root-cause hypothesis — CONFIRMED

The outstanding check has now been run on the reporting machine.
`~/.claude/settings.json` contains:

```
enabledPlugins : ["prisma-sase-mac@prisma-sase"]     <- present
pluginConfigs  : no entry matching "prisma"          <- ABSENT
```

The plugin is **enabled with no configuration entry of any kind**. Not an
entry with empty values — no entry at all. This closes the gap between "the
dialog was never shown" and "the dialog was shown and submitted empty": there
is nothing in the config store to have been submitted.

Combined with evidence §4 (values arrived empty, not as literal placeholders),
the sequence is: the host activated the plugin, skipped the `userConfig`
collection flow, and substituted the declared placeholders against an empty
configuration store.

### Plugin-side mitigation shipped in 0.8.8

The host fix is still required — this only stops the plugin from being blamed
for it. As of plugin v0.8.8:

- An env var that is **set but empty** is recorded separately from one that is
  **absent**, since only the former implicates the dialog.
- `--selfcheck` no longer claims the plugin is configured when the host holds
  no configuration for it (it previously did, exiting 0 — the same false
  positive as the settings screen).
- `get_sase_status` returns `credentials_not_supplied` with
  `whose_fault: "host"`, and the headline says so, so the failure is not
  mistaken for a tenant outage.

None of this recovers the credentials; the documented workaround
(`~/.prisma-sase.env`) remains the only path until the host collects them.
