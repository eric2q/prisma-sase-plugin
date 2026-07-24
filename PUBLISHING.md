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
3. Record changes in `plugin/CHANGELOG.md` — this is the **user-facing version
   history** (linked from both root READMEs), so write it for users: what was
   fixed (`FIX`), what's new (`NEW`), what behaves differently (`CHG`).
4. **Bump the version in FOUR places, in lockstep**: the three entries (+
   `metadata`) in `.claude-plugin/marketplace.json` (what gates user-visible
   updates), and `PLUGIN_VERSION` in `plugin/mcp/config.py` (what the server
   reports in its startup log, `--selfcheck`, and
   `get_sase_status.plugin_version` — how a Desktop user can ask Claude which
   version they're running). `tools/build-standalone.py` fails on a mismatch;
   a quick sync check:
   ```bash
   python3 tools/build-standalone.py && rm -rf dist   # errors out on drift
   ```
5. Commit + push:
   ```bash
   git add -A && git commit -m "v0.7.0: <summary>" && git push
   ```
6. Users get it via **Settings → Plugins → Update** / `/plugin marketplace
   update prisma-sase` (or background refresh).

> Prefer zero-ceremony releases? Delete the `version` fields from the plugin
> entries — Claude then tracks the git commit SHA and every push becomes an
> update. Explicit versions are recommended: they gate what users see and match
> the CHANGELOG.

## Why one code tree but three catalog entries

A plugin's MCP launch command is a single string, and no command exists on all
three OSes (`bash` is missing on Windows; `cmd` is missing on macOS/Linux).
The marketplace catalog solves this: all three entries (`prisma-sase-mac`,
`prisma-sase-linux`, `prisma-sase-windows`) point at the same `./plugin` source
with `"strict": false`, and each entry carries its own `mcpServers` launch
config (`bash mcp/run.sh` for mac/linux vs `cmd /c mcp\run.cmd` for Windows).
One push updates all three. Do not add a `.mcp.json` or `.claude-plugin/plugin.json`
back into `plugin/` — under `strict: false` a component-declaring manifest
inside the plugin would conflict with the catalog entries.

## Standalone .plugin files (optional)

For machines that cannot reach the git host (customer demo laptops, air-gapped),
build the classic file-upload packages:

```bash
python3 tools/build-standalone.py        # writes dist/prisma-sase-{mac,linux,windows}.plugin
```

The script generates the per-OS `.mcp.json` + `plugin.json` on the fly from
`marketplace.json`, so versions never drift between the two install paths.

## Release checklist

- [ ] `PRISMA_MOCK=1 ... --selfcheck` passes
- [ ] `plugin/CHANGELOG.md` updated
- [ ] `marketplace.json` version bumped in **all three** entries
- [ ] no secrets anywhere in the tree (`git grep -iE "client_secret\s*=" -- ':!*.md'` should find only code reading env vars)
- [ ] push, then verify update appears on one team machine before announcing
