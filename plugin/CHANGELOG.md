# Changelog

## 0.9.0 — 2026-07-27

**The plugin split in two.** The MCP server is no longer mounted by the
plugin; it installs as a **Local MCP server** launched through `uvx`, and the
plugin ships the `prisma-sase-ops` Skill alone.

The reason is the update cadence. A plugin is cached per version
(`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`), so a server fix
reached you only when you explicitly clicked Update. `uvx --from git+...`
re-resolves this repo on **every app launch** — so a fix pushed today is
running on your machine after your next restart, with nothing to click. For a
component that talks to a live API and whose bugs arrive as field reports,
that is the cadence it needed.

**What you have to do once:**

```bash
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
```

Existing 0.8.x installs keep working until you migrate; the venv launchers
(`run.sh` / `run.cmd` / `install.sh`) are still shipped, now as the legacy
path. See the README for the full walkthrough.

- **NEW:** `prisma-sase-setup` — a guided credential installer. Asks for the
  four values with an explanation of each, detects the TSG ID from your Client
  ID, stores the Client Secret in your OS keychain, and writes the Local MCP
  servers entry for you. `--print` shows the JSON and writes nothing;
  `--show` reports what is already stored, revealing no secret. It never
  writes a plaintext secret into the entry: what goes in is a
  `PRISMA_SECRET_CMD` line, so the secret itself stays in the keychain.
- **NEW (Windows):** a secret backend where there was none. `_backend()` only
  knew `security`, `secret-tool` and `pass` — all three absent on Windows — so
  the wizard there found nothing, wrote a `PRISMA_CLIENT_SECRET` placeholder,
  and told the user to paste the secret into the very file it exists to keep
  it out of. It now uses **DPAPI** via PowerShell: the encrypted blob lives in
  `%LOCALAPPDATA%\prisma-sase\`, decryptable only by that user on that
  machine. `cmdkey` was the obvious candidate and does not work — it stores
  into Credential Manager but will not print a password back, so it cannot be
  a fetch command.
- **FIX (Windows, latent):** `_quote()` emitted POSIX `shlex` quoting into a
  string that `config.py` runs with `shell=True` — cmd.exe on Windows, which
  treats single quotes as literal characters. Harmless while Windows had no
  backend; a launch failure the moment one existed. It now quotes for cmd.exe
  and refuses what cmd.exe cannot express (an embedded `"`, or a `%` it would
  expand even inside quotes) rather than emitting a command that dies at
  launch with no diagnostic.
- **FIX (Linux):** the panel entry's `PATH` was macOS-shaped
  (`/opt/homebrew/bin:...`) and omitted `~/.local/bin`, which is where the
  official uv installer puts `uvx`. It is now built around the directory uvx
  was actually found in, so a non-standard install location needs no edit.
  Windows keeps a `PATH` too — 0.9.0 dropped it there on the theory that
  Windows resolves `.exe` without help, but uvx still has to find `git` to
  resolve the `git+` ref.
- **NEW:** `tools/verify-windows.ps1` — the Windows paths above were written
  on macOS, where their tests can only pin the *shape* of what gets emitted.
  This script runs on Windows and checks the parts that shape cannot: that the
  secret round-trips through DPAPI, that the command survives cmd.exe
  verbatim, that it works with no inherited `PATH`, and that execution policy
  does not block it. All confirmed passing on a real Windows machine.
- **FIX (Windows on ARM):** the server could not launch there at all. Found on
  a real ARM64 VM, where `--selfcheck` went off building `cryptography==49.0.0`
  from source: it arrives transitively (`fastmcp` → `mcp` → `pyjwt[crypto]`)
  and its authors publish no `win_arm64` wheel for the current version, so a
  native interpreter has nothing to install and must compile — which needs Rust
  and MSVC, and without them dies citing `cargo`, naming nothing to do with
  this plugin. The wizard now asks uv for an x64 interpreter on ARM64 Windows
  (`--managed-python --python cpython-3.12-windows-x86_64`). Windows on ARM
  emulates x64, the `win_amd64` wheels exist, and nothing is compiled. uv
  publishes no ARM64 Windows build in the first place, so this only makes
  explicit what it would have to do regardless. Other platforms are untouched —
  choosing uv's interpreter for it is a liberty, and the missing wheel is the
  whole justification.
- **NEW:** the server auto-updates. No pinned ref means every launch gets the
  current `main`. Need a frozen target for a customer demo? Pin one:
  `git+https://github.com/eric2q/prisma-sase-plugin@v0.9.0`.
- **NEW:** the entry sets `PATH` explicitly, because the app does not give MCP
  servers a login shell's `PATH` and `uvx: command not found` was otherwise
  the first thing everyone hit.
- **FIX (setup, high):** `prisma-sase-setup` wrote to the wrong file on any
  machine whose app directory is not literally `Claude/`. Third-party and
  enterprise builds use a suffix — `Claude-3p/` is the one seen in the field —
  and the wizard hardcoded `Claude/`, so it reported success into a file the
  running app never reads: credentials present, no tools, no error anywhere.
  It now scans for every `Claude*` config and, when a machine has more than
  one, lists them — each with the MCP server names it already holds, never a
  value — and asks which to write. Guessing is the failure mode here, so it
  does not guess. `PRISMA_PANEL_CONFIG=<path>` answers ahead of time for
  unattended runs.
- **FIX (diagnosis, high):** the plugin **stopped accusing correctly-installed
  users of a host bug.** 0.8.8 treated "enabled, but `settings.json` holds no
  `pluginConfigs` entry" as proof the enable dialog never ran — a sound
  inference *while the plugin declared `userConfig`*. 0.9.0 removed
  `userConfig`, which makes that state exactly what a **correct** install looks
  like. Every new user was being told "This is a HOST issue" and sent hunting
  for a dialog that no longer exists. The `never_configured` diagnosis is gone;
  only evidence that actually arrived at this process (a value that is blank,
  or a literal `${...}`) is reported now, as a *configuration* problem rather
  than a host one. Absence of evidence stopped being evidence when the
  architecture moved.
- **FIX:** `--selfcheck` no longer says NOT READY when it simply cannot see
  the Local MCP entry's `env` — which, by design, it never can from an
  ordinary shell. It now says so and points at setup.
- **FIX:** `from prisma_sase_mcp.tools.status import get_sase_status` — the
  MCP-free escape hatch the Skill documents as a design guarantee — actually
  works. The `sys.path` shim lived only in `__main__`, so the documented import
  raised `ModuleNotFoundError` unless you came in through the console script.
  Both this and the misdiagnosis above are pinned by regression tests.
- **CHG:** one marketplace entry (`prisma-sase`) instead of three. With no
  launcher in the plugin there is nothing to vary per OS, so
  `prisma-sase-mac` / `-linux` / `-windows` are retired along with the "match
  your OS" instruction. `tools/build-standalone.py` now emits a single
  `dist/prisma-sase.plugin`, and fails the build if anything re-introduces
  `mcpServers` or `userConfig` into the plugin — that would launch a second,
  version-pinned copy of the server alongside the uvx one.
- **CHG:** `mcp/` moved to `src/prisma_sase_mcp/` (a proper Python package with
  `pyproject.toml`), and the version now has a fourth declaration point,
  `pyproject.toml`, checked in lockstep with the other three.

## 0.8.8 — 2026-07-27

The **host** enables the plugin without ever running the `userConfig` dialog,
then expands `${user_config.*}` to **empty strings**. Every tool fails for
missing credentials; the settings screen shows four masked dots and looks
configured. Field-verified on the Cowork marketplace-cache surface — and
confirmed against `~/.claude/settings.json`, which listed the plugin under
`enabledPlugins` with **no `pluginConfigs` entry at all**.

This is a host bug and the fix belongs there
([bug report](../BUG-REPORT-userconfig-dialog-never-shown.md), filed
separately). What ships here is the plugin refusing to take the blame for it:
the failure is now detected, correctly attributed, and paired with a recovery
path. Distinct from 0.8.7 — that fixed the `--plugin-dir` sideload path and
produced *literal* `${user_config.*}` strings; this is the opposite signature.

- **FIX (diagnosis, high):** an env var that is **set but empty** is no longer
  indistinguishable from one that is **absent**. Absent means nobody tried;
  empty means the host substituted `${user_config.*}` and had nothing to
  substitute. Only the second implicates the dialog — and it was precisely the
  case the 0.2.0 placeholder guard could not catch, because the values were
  not literal `${...}`, they were `""`. Recorded in `EMPTY_VARS`.
- **FIX (diagnosis, high):** `--selfcheck` no longer reports **"The plugin IS
  configured via the enable dialog"** (and exit 0) when the host holds no
  configuration for it. That reassurance reproduced, in the one place a user
  can get a straight answer, the same false positive the settings UI gives
  with its fixed-width masked dots. It now says `ENABLED but has NO
  configuration entry`, prints the diagnosis, and exits non-zero.
- **NEW:** `userconfig_diagnosis()` classifies a credential gap the host
  caused into `expanded_empty` (dialog never collected), `never_configured`
  (enabled with no config entry) or `unexpanded` (host cannot substitute at
  all), each with its own fix. Direct evidence from the running process
  outranks what `settings.json` implies. Returns nothing on a healthy install,
  so it never becomes noise.
- **NEW:** the verdict now reaches every surface a stuck user can see —
  `get_sase_status` gains `credentials_not_supplied` (with
  `whose_fault: "host"`) and an explicit headline, tool errors lead with it
  instead of advising a dialog that never ran, and the startup log warns.
  SKILL tells Claude to relay it verbatim and **not** to debug the tenant or
  send the user to re-check their API key.
- **NEW:** `plugin/setup-keychain.sh` — the recommended way to recover when
  the dialog is unavailable, because it is the only option besides the dialog
  that keeps the secret **out of a plaintext file**. Prompts for the secret
  (hidden — never a command-line argument, which `ps` would expose), stores it
  in the platform keychain (macOS Keychain / `secret-tool` / `pass`), and
  writes a `~/.prisma-sase.env` holding only the three non-secret values plus
  the matching `PRISMA_SECRET_CMD`. Preserves tuning variables, warns to
  **rotate** if it just replaced a plaintext secret, and flags an incomplete
  unattended run instead of writing a file that looks finished.
  `--show` / `--remove` / `--stdin`.
- **NEW (docs):** plugin README gains *"When the enable dialog never asked for
  anything"* — the symptom, why the masked dots in Settings prove nothing, a
  table of the three diagnosis kinds, **step 1: re-trigger the dialog**
  (per-host instructions; preferred, since it needs no file), step 2: the
  keychain or env-file stopgap, and step 3: clean up once the dialog works.
  Both root READMEs point at it. It states explicitly that this is **not dual
  configuration** — resolution is environment → env file → `PRISMA_SECRET_CMD`,
  first value wins, so the file only fills gaps and the dialog silently
  reclaims precedence the moment it works.
- **NEW (Skill):** a matching runbook. Claude now leads with the attribution
  (host bug, not the user, not the tenant), pre-empts the misleading settings
  screen, is told **not** to send anyone to re-check their API key or region,
  and walks dialog-first → keychain → env file while never accepting the
  secret in conversation. The credential rules now rank the three homes
  instead of listing them as equals.
- **NEW:** 16 regression tests — all three diagnosis kinds and their
  precedence, both no-false-alarm paths, the selfcheck exit code, the
  `get_sase_status` verdict, and for the keychain script: no plaintext secret
  in the written file, mode 600, tuning variables preserved, the rotation
  warning, and an end-to-end check that the server really resolves the secret
  through `PRISMA_SECRET_CMD`.

## 0.8.7 — 2026-07-27

The enable dialog silently supplied nothing when the plugin was **sideloaded**
(`--plugin-dir`), which is how Claude Desktop's local-agent sessions load it.
Marketplace installs were unaffected, so this hid behind a path that works.

- **FIX (credentials, high):** `userConfig` and `mcpServers` were declared
  **only in the marketplace entry**, and the plugin shipped no
  `plugin/.claude-plugin/plugin.json`. Under `--plugin-dir`, Claude Code reads
  that manifest and never sees `marketplace.json`, so the four
  `${user_config.*}` placeholders had no schema to bind to and were passed to
  the MCP server **verbatim** — confirmed by reading the running server's
  environment, which held the literal string `${user_config.client_id}` and
  three like it. `_is_placeholder` caught them (so the literal was never sent
  to the auth API as a secret, and the error named the cause), but every tool
  failed with "Missing required context: PRISMA_TSG_ID". The manifest now
  exists and declares both, so the dialog's values bind on **both** load
  paths. This affects 0.8.0 (which introduced `userConfig`) through 0.8.6
  identically — there is no version among them that works when sideloaded.
- **CHANGE:** the three marketplace entries move to `strict: true`. Under
  `strict: false` a plugin that also declares components in `plugin.json`
  is a documented conflict and fails to load, so keeping both was not an
  option. `strict: true` is the default and the documented mode for a plugin
  that manages its own components. The Windows entry keeps its `mcpServers`
  override (`cmd /c run.cmd`); mac and linux now inherit the bash block from
  the manifest.
- **CHANGE:** `version` is declared in `plugin.json` only. Claude Code always
  prefers the manifest's value without warning, so a version left in the
  marketplace entry can be silently masked by a stale manifest.
- **TESTS:** a `UserConfigBinding` suite fails if the manifest ever stops
  declaring `userConfig`, if any `${user_config.*}` (in the manifest or in an
  entry's override) names an undeclared key, or if `client_secret` loses
  `sensitive: true`. Verified against the 0.8.6 shape: it fails there. The
  version lockstep test now reads `plugin.json` and asserts entries do *not*
  redeclare a version.

## 0.8.6 — 2026-07-27

Documentation and user-facing message strings — no behaviour changed. Three
inaccuracies, all of which pushed users away from the credential path the
plugin actually prefers.

- **FIX (docs, high):** the docs described the plugin enable dialog as a
  **Claude Desktop** feature and told Claude Code CLI users to fall back to
  `~/.prisma-sase.env`. That is wrong. `userConfig` prompting is core Claude
  Code behaviour — *"the `userConfig` field declares values that Claude Code
  prompts the user for when the plugin is enabled"* — and a CLI install was
  field-verified to prompt for all four values. A CLI user following the old
  text would create an env file they never needed, putting the secret in a
  plaintext file when secure storage was available. Corrected in
  `README.md`, `README.zh-TW.md`, `plugin/README.md` (source list item 1,
  troubleshooting table, Windows install step 4),
  `skills/prisma-sase-ops/SKILL.md`, and the two runtime error hints in
  `mcp/auth.py` / `mcp/client.py`, which sent every user down a
  "Settings → Plugins" path that only exists in Desktop.
- **FIX (docs):** "stored in your OS secure storage (macOS Keychain), never
  in plaintext settings" was stated as unconditional — including in the
  shipped, user-visible `client_secret` field description in
  **`marketplace.json`, on all three OS variants**, so Linux and Windows
  users read a macOS-only claim in the dialog itself. Where no supported
  keychain exists the value goes to `~/.claude/.credentials.json`. Every
  occurrence now says "secure storage (macOS Keychain, or
  `~/.claude/.credentials.json` where no keychain is available)".
- **FIX (docs):** `plugin/README.md` still called the env file "the
  **primary** path on macOS", contradicting the numbered source list directly
  above it (where the enable dialog is #1) *and* the troubleshooting table in
  the same file. The 0.8.5 userConfig-first pass swept `install.sh` but
  missed this paragraph, so the claim that it "completes the userConfig-first
  pass" was premature. The `launchctl setenv` caveat it carried was also
  stranded under the `PRISMA_SECRET_CMD` item while describing the env file;
  it now sits with the env file, and the environment-variable note explains
  that the dialog injects through that same channel — which is why a
  hand-run `--selfcheck` cannot see dialog-supplied credentials.

## 0.8.5 — 2026-07-26

From a full code review of the plugin. Two of these let the tooling report
something reassuring that was not true.

- **FIX (honesty, high):** tunnel state was matched by **substring**, so any
  state name *containing* "up" counted as UP — `Disrupted`, `Setup`,
  `backup`, `SUPERVISING`. A disrupted tunnel therefore produced the
  headline **"Healthy: all tunnels up"**, defeating the 0.8.4 honesty work
  (which had fixed the `init` case but not the matching underneath it).
  Matching is now exact against an explicit up/down vocabulary (numeric
  `1`/`0` included); anything unrecognized falls through to `other_states`
  and is reported as *not up*, never assumed healthy.
- **FIX (security, high):** `uninstall.sh` **left credential files on disk
  while printing "removed"** when the home directory contained a space (e.g.
  `/Users/Eric Chen`). Paths were joined into a string and word-split by the
  delete loop; `rm -rf` returns success for a path that does not exist, so
  every fragment reported success. Paths are now held in an array, and each
  removal is **verified against the filesystem** — a surviving target prints
  `FAILED to remove` and exits non-zero, so "done" now means deleted.
- **FIX:** a `PRISMA_ENV_FILE` pointing at a **non-existent path** silently
  fell back to `~/.prisma-sase.env`. That is worst exactly where the
  variable is the only credential path — cloud sessions — where a typo'd
  staged path looked like a working setup. `--selfcheck` and startup now
  warn, naming the missing path and what (if anything) was used instead.
- **FIX (low):** `limit=0` returned 20 rows instead of clamping to 1. A
  parseable out-of-range number is now clamped; only unparseable input falls
  back to the default.
- **NEW:** `tools/test-regressions.py` — a stdlib-only, no-network
  regression suite (20 tests) pinning each bug above plus the credential
  audit, the secret-never-echoed guarantee, the version lockstep, and an
  all-tools mock smoke test. Run with
  `python3 tools/test-regressions.py`.
- **CHG (docs):** `install.sh` no longer calls the env file "the PRIMARY
  credential path" — the enable dialog is, and the file is the documented
  fallback (completes the userConfig-first pass).

## 0.8.4 — 2026-07-25

From a live install→use→uninstall walkthrough. Three gaps, one of them a
security one and one an honesty bug in the headline.

- **FIX (honesty, high):** the status headline could say **"Healthy"** while
  tunnels were not actually up. Tunnels in `other_states` (e.g. one stuck in
  `init` — never established) and tunnels that are up but whose
  **monitoring is down** (traffic flows, health unobserved) were both
  invisible to it; a live tenant had one of the former and two of the latter.
  Both are now counted, named (`not_up_names`, `monitoring_down_names`), and
  reported in the headline. SKILL forbids rounding "12 up, 0 down" up to
  "all good".
- **NEW (security):** `--selfcheck` audits credential files — warns when any
  `~/.prisma-sase*.env` is readable beyond the owner (a stray file with a
  plaintext secret at mode 644 was found only during removal), and lists
  look-alike files the plugin never reads so forgotten copies surface. Paths
  and mode bits only; contents are never read.
- **NEW (uninstall):** `plugin/uninstall.sh` removes what the host
  uninstaller cannot — the ~100 MB `~/.prisma-sase-venv`, credential files,
  and the launch log — listing everything first and prompting before
  deleting (`--dry-run`, `--yes`, `--keep-credentials`), then printing the
  `claude plugin uninstall` / `marketplace remove` commands and a
  rotate-your-secret reminder. plugin/README gains an **Uninstalling**
  section documenting exactly what each side removes.

## 0.8.3 — 2026-07-25

- **NEW:** the server detects when **it is itself out of date**. Hosts keep an
  MCP server process alive across a marketplace update, so the process
  launched from the previous version's directory keeps serving — reporting
  the old `plugin_version` while none of the update's fixes are live. A live
  CLI session needed `ps` forensics to spot this. Now `get_sase_status`
  returns `plugin_update_pending` (running vs installed version + the restart
  instruction), `--selfcheck` prints an `UPDATE PENDING` line, and startup
  logs a warning. Detection is layout-scoped (only when the code sits in a
  directory named after its own version), so dev checkouts never false-alarm.
  SKILL tells Claude to lead with this rather than debugging behaviour the
  newer version may already fix.
- **CHG:** ADEM overall-score extraction also accepts `endpointScore` /
  `experienceScore` (and snake_case variants) as aggregate-score keys.

## 0.8.2 — 2026-07-25

Driven by a live Claude Code CLI walkthrough of a fresh install. The plugin's
own guidance produced a WRONG diagnosis, and recovery still required manual
shell work — both fixed.

- **FIX (wrong diagnosis, high):** a hand-run `--selfcheck` cannot see values
  supplied through the plugin enable dialog — userConfig is injected into the
  MCP **server process** only — so it reported `credentials: MISSING` for a
  correctly configured plugin, and the assistant told the user to create an
  env file they did not need. Selfcheck now reads the host's
  `pluginConfigs` from `~/.claude/settings.json`, lists which options are
  set, states plainly that their invisibility here is expected, and returns
  a distinct **"DEPENDENCIES READY; credentials not visible from this
  shell"** result instead of NOT READY. SKILL carries the same warning:
  never conclude "no credentials" from a shell selfcheck.
- **NEW (self-repair):** the fallback server gained
  `prisma_sase_install_dependencies` — it creates `~/.prisma-sase-venv`
  (picking a ≥3.10 base interpreter if the current one is too old) and
  installs the requirements, reporting each step and the exact reload
  instructions. Recovery from "tools missing" is now a conversation
  ("shall I fix it?" → done) instead of copy-pasting shell commands.
- **FIX (P2 follow-up):** the live ADEM payload puts **per-segment** averages
  (`wlan` / `lan` / `vpnUnderlay` …) under `average` with no aggregate score.
  That is now reported as `no_data_reason: "no_aggregate_score"` with the
  segments exposed as components and the weakest named — instead of being
  dismissed as "no data". The note explicitly forbids inventing an overall
  score by averaging them.
- **DOC:** SKILL covers the CLI reload path (`/reload-plugins`) alongside
  Desktop's ⌘Q, and notes that a just-installed plugin's server is not
  running until reloaded.

## 0.8.1 — 2026-07-25

Driven by the 0.8.0 field report (macOS Cowork): a failed startup used to
make the entire toolset vanish with no error anywhere the user could see.

- **NEW (P1, the big one):** `mcp/setup_server.py` — a **dependency-free
  fallback MCP server**. When the real server can't start (missing
  fastmcp/httpx, or Python below the 3.10 floor), the plugin now serves this
  instead of exiting: it speaks stdio MCP with the standard library alone and
  exposes one tool, `prisma_sase_setup_required`, whose *description already
  names the problem* and whose output is the full diagnosis plus copy-paste
  fix commands. The failure now arrives in the conversation instead of
  silently removing every tool. `run.sh`/`run.cmd` also fall back to it with
  any available interpreter when no Python ≥ 3.10 exists.
- **NEW:** the launcher now logs *why* a preferred interpreter was skipped —
  `~/.prisma-sase-venv` missing, or present but **not executable** (a
  dangling venv, typically after a Python upgrade relocates the interpreter
  it was built against). That ambiguity cost the reporter three rounds.
  For the record: the interpreter search order has not changed since v0.6.1
  — 0.8.0 did not break dependencies; the venv was absent or stale.
- **NEW (P2):** ADEM score extraction handles the real response shape
  (`startTime/endTime/endpointType/tenantServiceGroup/rowCount/average`):
  `average` is read as the score (scalar or per-metric dict → components),
  and `rowCount` is surfaced. `rowCount: 0` is now reported as
  `no_data_reason: "empty_window"` with an explicit "this is NOT a mapping
  problem" note; a non-zero rowCount without a score is flagged
  `shape_mismatch` and reports `average`'s keys for correction.
- **CHG (P3):** aggregate alert output adds `category_coverage_pct`, and
  below 50% coverage the note says the view is a weak basis for an alert
  overview (live: 137 of 707 = 19%).
- **DOC:** the launch breadcrumb is promoted out of the Skill into a
  prominent **"If the tools don't show up"** section in plugin/README (with
  a line-by-line key) and both root READMEs — the people who need it are
  precisely those who can't reach the Skill. Troubleshooting gains the
  full-restart requirement (macOS ⌘Q; closing the window is not enough) and
  the dangling-venv row. SKILL tells Claude to look for
  `prisma_sase_setup_required` first and relay it verbatim.

## 0.8.0 — 2026-07-24

Credentials leave plaintext: enable-dialog (userConfig) + secret-command
backends. Addresses the cross-agent risk that any agent with shell access
can read a plaintext env file — now there need be nothing sensitive to read.

- **NEW (userConfig):** all three catalog entries (and the generated
  standalone manifests) declare `userConfig` — installing/enabling the
  plugin prompts for Client ID / Client Secret / TSG ID / Region in a
  dialog. The secret is `sensitive`: hosts store it in the OS secure
  storage (macOS Keychain) and inject it into the server env via
  `${user_config.*}` substitution. No env file needed on Desktop.
- **NEW (PRISMA_SECRET_CMD):** credential-process pattern — when
  `PRISMA_CLIENT_SECRET` is otherwise unset, the server runs the
  configured command and reads the secret from stdout (macOS `security`,
  `secret-tool`, `pass`, 1Password `op read`, ...). The env file can then
  hold only non-sensitive values. stderr is discarded, never logged.
- **CHG (safety net):** the `${...}` placeholder detector now also matches
  dotted names (`${user_config.client_secret}`), so a host that passes
  userConfig values through unexpanded is detected — values treated as
  unset with a named explanation, falling through to the env file, instead
  of sending the literal string to the auth API (the v0.2.0 bug's twin).
- **CHG:** `--selfcheck` reports the secret's source (environment /
  userConfig, env file — flagged as plaintext with upgrade hints, or
  PRISMA_SECRET_CMD) and diagnoses a secret command that returns nothing.
- **CHG:** `tools/build-standalone.py` now takes `mcpServers` and
  `userConfig` verbatim from the marketplace entries (one source of truth;
  the hardcoded launcher configs are gone). install.sh/install.bat env
  templates document that every line may stay empty when the dialog is
  used, and show PRISMA_SECRET_CMD examples.
- **DOC:** credential docs rewritten around the supported-homes model (OS
  secure storage / local env file / secret store — nowhere else): both
  root READMEs, plugin/README (sources + precedence, env-var table), and
  the Skill's credential rules — including the clarification that the
  host's enable dialog is settings UI, not "the conversation".

## 0.7.4 — 2026-07-24

Consistency release: record the one live datapoint we have, and make the
three-entry lockstep rule machine-enforced.

- **DOC:** `prisma_sase_external_alerts_current` docs no longer say "pending
  live verification" — the one live test so far was NEGATIVE (sg tenant,
  DATA10003, view absent; issue #9). endpoints.md, api-catalog.md, and the
  config.py mapping comment now record that result, note availability is
  tenant-version dependent, state the cost (one failing call per
  query_alerts before the aggregate fallback on such tenants), and point to
  the UI-capture workflow as the manual path.
- **NEW:** `tools/build-standalone.py` now fails if the three catalog
  entries drift on anything other than `name`/`description`/`keywords`/
  `mcpServers`, or if mac/linux stop sharing an identical bash launcher —
  the "keep entries in lockstep" rule is a build failure instead of human
  discipline (groundwork for adding `userConfig` to all three safely).
  PUBLISHING.md documents the enforced invariant.

## 0.7.3 — 2026-07-24

Follow-ups to the cloud-session report: teach the AI to READ the breadcrumb,
and make credential-storage principles explicit and enforceable.

- **CHG (Skill):** bootstrap runbook step 1 now explains how to interpret
  `~/.prisma-sase-launch.log` line by line — including the key inference
  that a **missing file means the host never attempted to launch the MCP
  server** (vs. a launch that died), which the field report couldn't
  distinguish.
- **NEW (Skill):** "Credential handling rules — enforce these when guiding
  users": (1) the LOCAL machine's env file is the only long-term home —
  never project folders / repos / shared drives; (2) secrets never in the
  conversation — stop users who start pasting one; (3) cloud staged copies
  are temporary working copies — proactively remind users to delete them;
  (4) exposure → rotate in SCM, deleting the leaked copy is not enough.
- **DOC:** the same storage principles spelled out in plugin/README (cloud
  section) and both root READMEs' credentials step (EN + zh-TW).

## 0.7.2 — 2026-07-24

Driven by the cloud-session field report (Cowork remote sandbox, region sg):
the plugin must survive environments where the MCP server never starts and
stderr is invisible.

- **NEW (cloud #1):** SKILL.md **bootstrap runbook** — when the Skill loaded
  but the MCP tools are absent (cloud/remote sessions), Claude now has the
  documented 2-minute recovery path: selfcheck → venv + deps → staged
  credentials → **direct-import fallback** (every tool is a plain
  synchronous importable function — now an explicit design guarantee).
- **NEW (cloud #1):** launch breadcrumb at `~/.prisma-sase-launch.log` —
  run.sh records the attempt and chosen interpreter; run.sh and server.py
  append fatal causes (no Python, version floor, missing deps). Post-mortem
  trail for environments where stderr is unreadable.
- **NEW (cloud #2):** plugin/README section **"Cloud sessions: getting
  credentials in"** — the supported staging path (`cp` to a non-dotfile
  copy in an authorizable folder + `PRISMA_ENV_FILE`), the dotfile-attachment
  trap, and the explicit rule that secrets never go through the chat.
- **CHG (cloud #3):** alerts_detail discovery candidates widened (siblings
  of `prisma_sase_external_alerts_current`, view-form variants); the
  "capture the real query from the SASE UI dev tools → PRISMA_INSIGHTS_MAP"
  path is now a **documented first-class workflow** (endpoints.md
  step-by-step, linked from discovery notes and README troubleshooting).
- **FIX (cloud #4):** NOT READY guidance (selfcheck + dependency pre-check)
  now prescribes the dedicated venv (matching run.sh's search order) instead
  of `pip install` into the system interpreter, which Debian/Ubuntu block
  (PEP 668).
- **FIX (cloud #5):** aggregate alert counts pin their semantics: when
  MU+RN+SC covers less than `total` (live: 132 of 722), the response carries
  `summary_counts.other_uncategorized` and a `category_note` ("do not treat
  the categorized sum as the total"), propagated into `get_sase_status`.
- **FIX (cloud, polish):** `get_sase_status`'s experience section now
  includes `no_data_debug` when present — its own note told readers to look
  at a field that had been sliced away.

## 0.7.1 — 2026-07-24

The plugin can now say what version it is — previously the version lived
only in marketplace.json, so a Desktop user (who can only reach the MCP
tools) had no way to find out in-conversation.

- **NEW:** `PLUGIN_VERSION` embedded in `config.py`; reported in the server
  startup log, in `--selfcheck` (header line), and as
  `get_sase_status.plugin_version` — ask Claude "which plugin version am I
  running?" and it can answer.
- **NEW:** `tools/build-standalone.py` fails the build if
  `config.PLUGIN_VERSION` and the marketplace.json versions drift.
- **DOC:** PUBLISHING.md release step now says bump four places in lockstep
  (three marketplace entries + PLUGIN_VERSION) with the sync check;
  SKILL.md tells Claude where to read the version and to compare against
  the CHANGELOG when users ask.

## 0.7.0 — 2026-07-24

PANW guidance (internal, 2026-07-24) folded in: the per-alert severity view
is identified, the ADEM per-user parameter is corrected, and all v0.6.8
probe/semantics assumptions are confirmed.

- **NEW (severity path):** `alerts_detail` now defaults to
  `prisma_sase_external_alerts_current` — a single-segment Insights 3.0
  resource (no view component) returning per-alert rows with severity
  (`alert_id`, `severity`, `severity_id`, `state`, `updated_time`).
  `query_alerts` tries it automatically before falling back to the
  aggregate view; marked unverified until confirmed live. The client and
  discovery now support single-segment resource paths.
- **FIX (ADEM per-user):** per-user scoping now sends
  `filter=userName==<email>` (the correct parameter) instead of the guessed
  `user=`. Valid `endpoint-type` values documented: `muAgent`, `rnAgent`.
- **CHG (discovery):** candidate list updated from guidance —
  `prisma_sase_external_alerts_current` leads alerts_detail;
  `users/all/user_list_all`, `sites/rn_list`, `sites/sc_list`,
  `sites/site_status` added; speculative dead-end candidates trimmed.
  `DATA10002` (Invalid Resource property name) added to the
  exists_field_mismatch class; classification order fixed so property-name
  errors are not mistaken for missing views.
- **CHG (confirmed semantics):** `alerts/alerts_list` = one row per
  sub-tenant, `total_count` = alerts raised within the time window (docs and
  messages updated); scope to one sub-tenant via `sub_tenant_id`/`domain`
  filter. Error codes confirmed stable (BigQuery passthrough: GCP* from BQ,
  DATA* from the gateway). `properties:["*"]` = BQ passthrough, fine for
  probing; official SELECT format is `[{"property": "name"}]`. Token
  `expires_in` guaranteed 900 s. Rate limits documented: 1000 calls/min per
  source IP → 429; ~4000/min → 403 + 10-min IP block (403 hint updated).
- **DOC:** endpoints.md, api-catalog.md (incl. `incidents/incidents_list`
  dead end → SCM Unified Incident Framework), SKILL.md, plugin/README
  troubleshooting, and both README walkthroughs (role confirmation: View
  Only Administrator is the right-sized standard role) updated accordingly.

## 0.6.8 — 2026-07-24

Driven by issue #3 (live-test field report, region sg): discovery probe
false negatives, honest severity messaging, sub-tenant count labeling.

- **FIX (high, #3):** `discover_insights` probes now SELECT with
  `properties:["*"]` (always a valid SELECT) and classify 400s by the
  server's error identity instead of guessing: `DATA10003`/"Invalid
  resource" → `not_found`; `GCP10002`/"Unrecognized name"/"SELECT list must
  not be empty" → `exists_field_mismatch` (view exists, fix the property
  name, not the view). A filter-only fallback variant matches the shape the
  live-verified query tools send. Views that exist but need explicit
  properties are no longer misclassified as unavailable.
- **NEW:** `SaseApiError` carries `api_code`/`api_message` extracted from
  error bodies; tool error dicts expose them (`api_error_code`/`_message`)
  and 400 errors include the identity inline. Discovery output gains an
  error-code interpretation note and a field-mismatch note naming the
  affected views; mock probes mirror the DATA10003 shape.
- **FIX (medium, #3):** aggregate-alerts messaging no longer implies a
  missing view mapping. `query_alerts`' note and `get_sase_status`'
  headline now say severity is not exposed by this tenant's Insights API
  (field-verified: no per-alert Insights view exists on that tenant shape;
  the dedicated Prisma Access alerts/notifications API is the Phase-2
  path), with discovery as the way to check a given tenant.
- **FIX (low, #3):** the aggregate alerts view returns one row per
  sub-tenant; counts are now summed across ALL rows (previously only the
  first row was read) and labeled: `sub_tenant_count`, `by_sub_tenant`
  breakdown, an `aggregation_note`, and "across N sub-tenants" in the
  status headline — so totals no longer look inconsistent with the
  per-sub-tenant numbers in the SASE UI.
- **DOC (#3):** the probing technique (`["*"]` + DATA10003 vs GCP10002
  interpretation) documented in endpoints.md and the plugin README
  troubleshooting table; SKILL.md updated to present severity gaps as an
  API limitation and to always mention cross-sub-tenant aggregation.

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
