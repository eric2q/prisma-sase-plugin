#!/usr/bin/env bash
# Venv-based setup for the prisma-sase MCP server -- the FALLBACK path.
#
# Since 0.9.0 the normal install is uvx, which needs none of this:
#
#     uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup
#
# uvx builds the environment itself and re-resolves the git ref on every
# launch, so you stay current. Use this script instead when uv is unavailable
# or blocked -- an air-gapped host, a locked-down build image, or a checkout
# you want to run and edit in place.
#
# What it does:
#   1. Finds a Python >= 3.10 (fastmcp's floor; macOS system python3 is often 3.9).
#   2. Creates a venv at ~/.prisma-sase-venv (override with PRISMA_VENV).
#   3. Installs requirements.txt into it.
#   4. Runs a mock-mode selfcheck to prove the server starts.
#
# After this, run.sh (in this directory) finds the venv automatically -- no
# config edits needed. Written for bash 3.2 (macOS default) compatibility.
set -eu

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${PRISMA_VENV:-$HOME/.prisma-sase-venv}"

echo "== prisma-sase install =="

# 1) find a suitable python
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      PY="$(command -v "$c")"
      break
    fi
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: no Python >= 3.10 found on PATH." >&2
  case "$(uname -s)" in
    Darwin)
      echo "  Install one, then re-run this script:" >&2
      echo "   - Homebrew:           brew install python@3.12" >&2
      echo "   - official installer: https://www.python.org/downloads/" >&2
      echo "  (The system /usr/bin/python3 on macOS is often 3.9 -- too old.)" >&2
      ;;
    Linux)
      echo "  Install with your distro's package manager, then re-run this script:" >&2
      echo "   - Debian/Ubuntu: sudo apt update && sudo apt install python3 python3-venv python3-pip" >&2
      echo "   - Fedora/RHEL:   sudo dnf install python3" >&2
      ;;
    *)
      echo "  Install Python >= 3.10 (https://www.python.org/downloads/), then re-run this script." >&2
      ;;
  esac
  exit 1
fi
echo "-- using $PY ($("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"

# 1b) venv prerequisite: Debian/Ubuntu ship python3 WITHOUT ensurepip until
#     python3-venv is installed -- catch that here with the exact fix instead
#     of letting 'python3 -m venv' die with a confusing error.
if ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
  PYMM="$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
  echo "ERROR: $PY cannot create virtualenvs (module 'ensurepip' is missing)." >&2
  echo "  Debian/Ubuntu fix: sudo apt install python$PYMM-venv   (or: python3-venv)" >&2
  echo "  Then re-run this script." >&2
  exit 1
fi

# 2) venv
if [ ! -x "$VENV/bin/python" ]; then
  echo "-- creating venv at $VENV"
  if ! "$PY" -m venv "$VENV"; then
    echo "ERROR: could not create the virtualenv at $VENV." >&2
    echo "  Check the message above; common causes are a partial Python install" >&2
    echo "  or no write permission to $VENV. Fix it and re-run this script" >&2
    echo "  (safe to re-run; or pick another location via PRISMA_VENV=/path)." >&2
    exit 1
  fi
else
  echo "-- reusing existing venv at $VENV"
fi

# 3) deps
echo "-- installing dependencies (fastmcp, httpx)"
if ! "$VENV/bin/python" -m pip install --quiet --upgrade pip; then
  echo "WARNING: pip self-upgrade failed -- continuing with the bundled pip." >&2
fi
if ! "$VENV/bin/python" -m pip install --quiet -r "$DIR/requirements.txt"; then
  echo "ERROR: dependency install failed (fastmcp, httpx)." >&2
  echo "  Most common cause: no network access to pypi.org (offline, firewall," >&2
  echo "  or corporate proxy)." >&2
  echo "   - behind a proxy: export HTTPS_PROXY=http://proxy:port  then re-run" >&2
  echo "   - offline now:    re-run this script when you have network access" >&2
  echo "  Re-running is safe -- the venv is kept and the install resumes." >&2
  exit 1
fi

# 4) credential file template. On this fallback path there is no Local MCP
#    panel entry to carry the variables, so the file is how the server is
#    configured -- it is also where the non-credential PRISMA_* tuning
#    variables live. On macOS it is the reliable mechanism when GUI apps do
#    not inherit launchctl setenv; empty lines are ignored by the server.
ENVF="$HOME/.prisma-sase.env"
if [ ! -f "$ENVF" ]; then
  cat > "$ENVF" <<'EOF'
# prisma-sase credentials (KEY=VALUE, no quotes needed).
# Keep it private: chmod 600 ~/.prisma-sase.env
#
# This file is the venv/fallback path. The normal uvx install carries these
# same four values as environment variables on the Local MCP servers entry
# instead -- if you have one of those, it wins and this file can stay empty.
PRISMA_CLIENT_ID=
PRISMA_TSG_ID=
PRISMA_REGION=sg
# Secret, pick ONE:
#  a) plaintext here (simplest):
PRISMA_CLIENT_SECRET=
#  b) or fetch it from a secret store at startup (keeps this file
#     non-sensitive). Examples:
#       PRISMA_SECRET_CMD=security find-generic-password -s prisma-sase -w
#       PRISMA_SECRET_CMD=secret-tool lookup service prisma-sase key client_secret
#       PRISMA_SECRET_CMD=pass show prisma-sase/client-secret
#       PRISMA_SECRET_CMD=op read "op://Private/prisma-sase/client secret"
EOF
  chmod 600 "$ENVF"
  echo "-- created credential template $ENVF (chmod 600) -- fill in your values"
else
  echo "-- keeping existing $ENVF"
fi

# 5) prove the server starts (offline, no credentials needed)
echo "-- running selfcheck (mock mode)"
PRISMA_MOCK=1 "$VENV/bin/python" "$DIR/server.py" --selfcheck

echo ""
echo "== install complete =="
echo "venv python : $VENV/bin/python"
echo "next steps  :"
echo "  1. Register the server. Settings > Extensions/Connectors > Local MCP"
echo "     servers, add an entry named prisma-sase with:"
echo "       command : $VENV/bin/python"
echo "       args    : $DIR/server.py"
echo "     (or point it at run.sh, which finds this venv on its own)."
echo "  2. Credentials -- pick ONE and restart the app:"
echo "       bash \"$DIR/setup-keychain.sh\"   # secret -> keychain, file stays clean"
echo "       or fill in $ENVF   # simplest, but the secret sits on disk"
echo "     (Create the read-only service account in Strata Cloud Manager first"
echo "      -- see the README.)"
echo "  3. Optional: install the Skill for the diagnostic runbooks --"
echo "     /plugin marketplace add eric2q/prisma-sase-plugin"
echo "     /plugin install prisma-sase@prisma-sase"
echo "  4. Verify:  $VENV/bin/python \"$DIR/server.py\" --selfcheck"
echo "  5. First run against a real tenant: ask Claude to run discover_insights"
echo "     (or:  $VENV/bin/python \"$DIR/server.py\" --discover )"
echo "     to find your tenant's real Insights resource/view names."
