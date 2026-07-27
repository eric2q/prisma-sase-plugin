# Maintainer guide — publishing releases

## The one thing to internalise first

Since 0.9.0 this repo ships **two halves that reach users by completely
different routes**:

| Half | Route | When the user gets it |
|---|---|---|
| **MCP server** (`src/prisma_sase_mcp/`) | `uvx --from git+https://github.com/eric2q/prisma-sase-plugin` | **the moment you push to `main`**, on their next app launch |
| **Skill** (`plugin/`) | the plugin marketplace | when they run Update, or a background refresh picks it up |

The consequence is blunt: **pushing to `main` is a release of the server.**
There is no staging, no "I'll tag it later", no installed copy to lag behind —
uvx re-resolves the git ref every launch. A broken commit on `main` is a broken
tool call on somebody's laptop within minutes. Work on a branch, merge when the
checks below pass.

The Skill half is the opposite: it is cached under a pinned version, so a
Skill change only ships after a version bump *and* a user-side update. Write
Skill prose so it stays true across a server release or two.

## First-time: put this repo on GitHub

```bash
cd prisma-sase-plugin
git init -b main
git add -A
git commit -m "prisma-sase v0.9.0"
# public or internal org repo both work; private works with the caveats in README
gh repo create eric2q/prisma-sase-plugin --private --source . --push
# (or create the repo in the GitHub UI and: git remote add origin <url> && git push -u origin main)
```

Then tell the team two things: the one-line setup command (below), and the repo
slug for **Add marketplace → Add from a repository** if they also want the Skill.

```bash
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
```

## Releasing an update

1. Edit code under `src/prisma_sase_mcp/` and/or the Skill under `plugin/`.
2. Smoke test offline (no credentials, no network):
   ```bash
   PRISMA_MOCK=1 python3 src/prisma_sase_mcp/server.py --selfcheck
   ```
   Then run the regression suite — stdlib only. It pins the shipped bugs
   (tunnel-state honesty, uninstall deletion, env-file resolution, secret
   non-disclosure, the setup wizard's refusal to write a plaintext secret,
   the credential-diagnosis wording) and checks the version lockstep of
   step 4 for you:
   ```bash
   python3 tools/test-regressions.py
   ```
   Then validate both manifests — the plugin one is what a `--plugin-dir`
   session reads, so a break there is invisible to a marketplace install:
   ```bash
   claude plugin validate ./plugin && claude plugin validate .
   ```
3. **Exercise the real uvx path from a clean cache.** This is the only check
   that proves what users will actually run, and it is the one that catches a
   packaging mistake the local `python3` invocation above cannot see (a module
   missing from the wheel, a dependency you had installed globally, an entry
   point that does not resolve):
   ```bash
   uvx --refresh --from git+https://github.com/eric2q/prisma-sase-plugin@<branch> \
       prisma-sase-mcp --selfcheck
   ```
   `--refresh` bypasses uv's cached build of the ref — without it you may be
   testing yesterday's tree. Substitute your branch before merging; after
   merging, re-run it with no `@ref` so it resolves `main` exactly as a user's
   launch does.
4. Record changes in `plugin/CHANGELOG.md` — this is the **user-facing version
   history** (linked from both root READMEs), so write it for users: what was
   fixed (`FIX`), what's new (`NEW`), what behaves differently (`CHG`).
5. **Bump the version in FOUR places, in lockstep**:
   - `plugin/.claude-plugin/plugin.json` — authoritative for the Skill. Claude
     Code always prefers the manifest's version, on both load paths.
   - `metadata.version` in `.claude-plugin/marketplace.json` — the catalog's
     own version.
   - `version` in `pyproject.toml` — what uvx actually builds. New since
     0.9.0; forgetting it is silent, because uvx resolves by git ref and never
     consults the version.
   - `PLUGIN_VERSION` in `src/prisma_sase_mcp/config.py` — what the server
     reports in its startup log, `--selfcheck`, and
     `get_sase_status.plugin_version`, so a user can ask Claude which version
     they're running.

   The **plugin entry** carries no `version` of its own and must not gain one:
   the manifest always wins, so an entry version can't take effect — it can
   only go stale unnoticed. `tools/build-standalone.py` fails on drift across
   all four *and* on a re-introduced entry version:
   ```bash
   python3 tools/build-standalone.py && rm -rf dist   # errors out on drift
   ```
6. Commit + push:
   ```bash
   git add -A && git commit -m "v0.9.0: <summary>" && git push
   ```
   The server is live for every user at this point. The Skill is not.
7. Skill users get it via **Settings → Plugins → Update** / `/plugin
   marketplace update prisma-sase` (or background refresh).

### Pinning, for users who need a stable target

A customer demo laptop that must not change under you can pin the ref:

```json
"args": ["--from", "git+https://github.com/eric2q/prisma-sase-plugin@v0.9.0",
         "prisma-sase-mcp"]
```

That trades auto-update for reproducibility. Tag releases (`git tag v0.9.0 &&
git push --tags`) so this option exists even if nobody uses it today.

## Why the server left the plugin

Through 0.8.x the plugin mounted the MCP server itself, via a `mcpServers`
block and a `bash mcp/run.sh` launcher. Two things made that untenable:

**The plugin cache is version-pinned.** Claude Code installs a plugin into
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` and runs *that*
copy. A server fix reached users only when they explicitly updated. For a
component that talks to a live API and whose bugs are field-reported, that is
the wrong update cadence.

**A launch command is a single string, and no command exists on all three
OSes** (`bash` is missing on Windows; `cmd` is missing on macOS/Linux). The
0.8.x workaround was three marketplace entries — `prisma-sase-mac`,
`prisma-sase-linux`, `prisma-sase-windows` — differing only in their launcher.
Three identities to keep in lockstep, three chances to drift, and a permanent
"match your OS" instruction in the install docs.

uvx solves both at once: one command that works everywhere, re-resolved from
git on every launch. So 0.9.0 collapsed the three entries into one
`prisma-sase` plugin that ships the **Skill alone**, and moved the server to a
Local MCP entry the user's host launches directly.

`tools/build-standalone.py` enforces the split: it fails if `plugin.json` or
any marketplace entry declares `mcpServers` or `userConfig`. Re-adding either
would quietly launch a *second*, version-pinned copy of the server alongside
the uvx one — two servers claiming the same tool names, one of them stale.
`userConfig` is gone for the same reason: credentials now arrive through the
Local MCP entry's `env` block, and a declared-but-unused `userConfig` would
resurrect the enable dialog that 0.8.7's credential bug lived in.

## Testing the Skill locally (`--plugin-dir`)

```bash
claude --plugin-dir /path/to/repo/plugin        # sideload; reads plugin.json only
```

A sideloaded plugin gets a synthetic marketplace named `inline`, so its
identity is **`prisma-sase@inline`**, not `prisma-sase@prisma-sase`. That
mattered enormously through 0.8.x, when credentials were filed in
`~/.claude/settings.json` under the plugin identity and the mismatch produced
a silent empty-string substitution.

**Since 0.9.0 it barely matters.** The plugin carries no `userConfig` and no
server, so there is nothing identity-keyed left to get wrong: the Skill loads,
and the tools come from the Local MCP entry regardless of how the Skill was
loaded. Sideload freely.

`@inline` is not in the Claude Code docs — it is inferred from the
`~/.claude/plugins/data/<name>-inline/` directory and confirmed empirically on
2.1.219. Re-check it if a future release changes sideload identity.

### Testing the server against a real tenant

Credentials for development go through the same guided setup users run — there
is no separate dev path any more, and `--print` lets you inspect the entry
without writing it:

```bash
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup --print
uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup --show
```

To exercise your **working tree** rather than a pushed ref, point `--from` at
the local path:

```bash
uvx --from . prisma-sase-mcp --selfcheck
```

`--show` reports what is already stored without printing the secret. Keep it
that way: nothing in this repo should ever echo a credential value.

## Standalone .plugin file (optional)

For machines that cannot reach the git host, build the file-upload package:

```bash
python3 tools/build-standalone.py        # writes dist/prisma-sase.plugin
```

One zip now, not three — with no launcher in the plugin there is nothing to
vary per OS. Note what this does *not* solve: the zip contains the **Skill
only**. A machine that cannot reach GitHub also cannot run `uvx --from
git+...`, so it has no tools either. For a genuinely air-gapped install the
server has to be vendored separately (`uv pip install .` into a venv on the
target, with a Local MCP entry pointing at that venv's `prisma-sase-mcp`).

## Release checklist

- [ ] `PRISMA_MOCK=1 python3 src/prisma_sase_mcp/server.py --selfcheck` passes
- [ ] `python3 tools/test-regressions.py` passes
- [ ] `claude plugin validate ./plugin && claude plugin validate .` both pass
- [ ] `uvx --refresh --from git+…@<branch> prisma-sase-mcp --selfcheck` passes — the real user launch path, from a cold cache
- [ ] `python3 tools/build-standalone.py && rm -rf dist` succeeds (version + entry drift check)
- [ ] `plugin/CHANGELOG.md` updated
- [ ] version bumped in **four** places: `plugin/.claude-plugin/plugin.json`, `metadata.version`, `pyproject.toml`, `config.PLUGIN_VERSION` (the entry carries none)
- [ ] no secrets anywhere in the tree (`git grep -iE "client_secret\s*=" -- ':!*.md'` should find only code reading env vars), and no dev settings file committed
- [ ] push, then **re-clone from GitHub** and re-run the checks there — the 0.8.7 bug was an untracked file that passed every local check
- [ ] re-run the uvx check with **no `@ref`** so it resolves `main`, exactly as a user's next app launch will
- [ ] verify on one team machine before announcing: full restart (⌘Q, not window close), then ask Claude for `get_sase_status` and confirm `plugin_version`
