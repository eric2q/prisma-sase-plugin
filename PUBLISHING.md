# Maintainer guide — publishing releases

## First-time: put this repo on GitHub

```bash
cd prisma-sase-marketplace
git init -b main
git add -A
git commit -m "prisma-sase marketplace v0.6.1"
# public or internal org repo both work; private works with the caveats in README
gh repo create eric2q/prisma-sase-plugin --private --source . --push
# (or create the repo in the GitHub UI and: git remote add origin <url> && git push -u origin main)
```

Then tell the team the repo slug — that's all they need for
**Add marketplace → Add from a repository**.

## Releasing an update

1. Edit code / skills under `plugin/`.
2. Smoke test offline (no credentials needed):
   ```bash
   PRISMA_MOCK=1 python3 plugin/mcp/server.py --selfcheck
   ```
   Then run the regression suite — stdlib only, no network, no credentials.
   It pins the shipped bugs (tunnel-state honesty, uninstall deletion,
   env-file resolution, secret non-disclosure) and checks the version
   lockstep of step 4 for you:
   ```bash
   python3 tools/test-regressions.py
   ```
   Then validate both manifests — the plugin one is what a `--plugin-dir`
   session reads, so a break there is invisible to a marketplace install:
   ```bash
   claude plugin validate ./plugin && claude plugin validate .
   ```
3. Record changes in `plugin/CHANGELOG.md` — this is the **user-facing version
   history** (linked from both root READMEs), so write it for users: what was
   fixed (`FIX`), what's new (`NEW`), what behaves differently (`CHG`).
4. **Bump the version in THREE places, in lockstep**:
   - `plugin/.claude-plugin/plugin.json` — the authoritative one. Claude Code
     always prefers the manifest's version, on both load paths.
   - `metadata.version` in `.claude-plugin/marketplace.json` — the catalog's
     own version.
   - `PLUGIN_VERSION` in `plugin/mcp/config.py` — what the server reports in
     its startup log, `--selfcheck`, and `get_sase_status.plugin_version`, so
     a user can ask Claude which version they're running.

   The three **plugin entries** carry no `version` of their own and must not
   gain one: the manifest always wins, so an entry version can't take effect —
   it can only go stale unnoticed. `tools/build-standalone.py` fails on drift
   *and* on a re-introduced entry version:
   ```bash
   python3 tools/build-standalone.py && rm -rf dist   # errors out on drift
   ```
5. Commit + push:
   ```bash
   git add -A && git commit -m "v0.7.0: <summary>" && git push
   ```
6. Users get it via **Settings → Plugins → Update** / `/plugin marketplace
   update prisma-sase` (or background refresh).

> Prefer zero-ceremony releases? Delete `version` from
> `plugin/.claude-plugin/plugin.json` too — Claude then tracks the git commit
> SHA and every push becomes an update. An explicit version is recommended: it
> gates what users see and matches the CHANGELOG. (Deleting it from the plugin
> *entries* achieves nothing — they no longer carry one; the manifest is what
> Claude reads.)

## Why one code tree but three catalog entries

A plugin's MCP launch command is a single string, and no command exists on all
three OSes (`bash` is missing on Windows; `cmd` is missing on macOS/Linux).
The marketplace catalog solves this: all three entries (`prisma-sase-mac`,
`prisma-sase-linux`, `prisma-sase-windows`) point at the same `./plugin`
source, and Windows overrides `mcpServers` with `cmd /c mcp\run.cmd`. One push
updates all three.

**Everything else belongs in `plugin/.claude-plugin/plugin.json`, not in the
entries.** That manifest is the single source of truth for `userConfig`, the
default bash launcher, and the version. The entries carry only per-OS
presentation (`name` / `description` / `keywords`) plus the Windows launcher.

This is not a style preference — it is the fix for the 0.8.7 credential bug.
A marketplace install reads `marketplace.json`; a `--plugin-dir` session reads
**only** the manifest and never sees the catalog at all. Anything declared
solely in an entry silently does not exist on the sideload path. Through 0.8.6
`userConfig` lived only in the entries and there was no manifest, so every
sideloaded session passed the literal string `${user_config.client_id}` to the
server and every tool failed for want of credentials. Declaring it in the
manifest makes both paths agree.

(Consequence: the entries are `"strict": true`, the default. Under
`strict: false` a component-declaring manifest inside the plugin is a
documented conflict, so keeping both was never an option.)

The lockstep rule is machine-enforced: `tools/build-standalone.py` fails if
the three entries differ on anything other than `name` / `description` /
`keywords` / `mcpServers`, if mac or linux re-introduces an `mcpServers`
override, if Windows loses one, or if any entry re-introduces a `version`.
`tools/test-regressions.py` additionally fails if the manifest stops declaring
`userConfig`, if any `${user_config.*}` names an undeclared key, or if
`client_secret` loses `sensitive: true`.

## Testing a build locally (`--plugin-dir`) — the `@inline` trap

`claude --plugin-dir ./plugin` is the fastest way to exercise a change, but it
is **not** the same load path as a marketplace install, and the difference
will waste an afternoon if you do not know it:

```bash
claude --plugin-dir /path/to/repo/plugin        # sideload; reads plugin.json only
```

A sideloaded plugin gets a synthetic marketplace named `inline`, so its
identity is **`prisma-sase-mac@inline`** — not `prisma-sase-mac`, and not the
`prisma-sase-mac@prisma-sase` that the marketplace install uses. Your normal
credentials in `~/.claude/settings.json` are filed under the marketplace id
and will **not** be found.

The failure mode is nasty: an unrecognised `pluginConfigs` key produces no
warning. Substitution just resolves to an empty string, so the server starts
happily and every tool reports missing credentials — which looks identical to
"the plugin is broken."

To supply credentials to a sideloaded session, use a settings file keyed on
`@inline`:

```json
{
  "pluginConfigs": {
    "prisma-sase-mac@inline": {
      "options": {
        "client_id": "…",
        "client_secret": "…",
        "tsg_id": "…",
        "region": "…"
      }
    }
  }
}
```

```bash
claude --plugin-dir /path/to/repo/plugin --settings ~/.prisma-sase-dev.json
```

> **The secret is plaintext here.** Sideloading never shows the enable dialog
> (the plugin is auto-enabled and never prompts), so there is no path that
> writes to the Keychain. `chmod 600` the file, keep it **outside the repo**,
> and never commit it. If you would rather not have a plaintext secret at all,
> leave `client_secret` out and let the server pick it up from
> `~/.prisma-sase.env` / `PRISMA_SECRET_CMD` instead.

To verify a change actually binds — without printing any credential:

```bash
claude --plugin-dir /path/to/repo/plugin --settings ~/.prisma-sase-dev.json mcp list
```

`✔ Connected` only proves the process started. To prove the *values* arrived,
have `run.sh` report presence and length (never the value) on first line, or
check `plugin_version` and the credential status via `get_sase_status`.

`@inline` is not in the Claude Code docs — it is inferred from the
`~/.claude/plugins/data/<name>-inline/` directory and confirmed empirically on
2.1.219. Re-check it if a future release changes sideload identity.

## Standalone .plugin files (optional)

For machines that cannot reach the git host (customer demo laptops, air-gapped),
build the classic file-upload packages:

```bash
python3 tools/build-standalone.py        # writes dist/prisma-sase-{mac,linux,windows}.plugin
```

Each bundle starts from the real `plugin/.claude-plugin/plugin.json` and
overlays only the per-OS name/description/keywords and, for Windows, the
launcher. That is deliberate: synthesising a manifest from `marketplace.json`
(as this did through 0.8.6) shipped bundles with **no `userConfig`**, so the
file-upload install had the same credential failure as the sideload path.

## Release checklist

- [ ] `PRISMA_MOCK=1 ... --selfcheck` passes
- [ ] `python3 tools/test-regressions.py` passes
- [ ] `claude plugin validate ./plugin && claude plugin validate .` both pass
- [ ] `python3 tools/build-standalone.py && rm -rf dist` succeeds (version + entry drift check)
- [ ] `plugin/CHANGELOG.md` updated
- [ ] version bumped in **three** places: `plugin/.claude-plugin/plugin.json`, `metadata.version`, `config.PLUGIN_VERSION` (entries carry none)
- [ ] no secrets anywhere in the tree (`git grep -iE "client_secret\s*=" -- ':!*.md'` should find only code reading env vars), and no dev settings file committed
- [ ] push, then **re-clone from GitHub** and re-run the checks there — the 0.8.7 bug was an untracked file that passed every local check
- [ ] verify the update appears on one team machine before announcing
