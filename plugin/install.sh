#!/usr/bin/env bash
# One-shot setup for the prisma-sase MCP server.
#
# What it does:
#   1. Finds a Python >= 3.10 (fastmcp's floor; macOS system python3 is often 3.9).
#   2. Creates a venv at ~/.prisma-sase-venv (override with PRISMA_VENV).
#   3. Installs mcp/requirements.txt into it.
#   4. Runs a mock-mode selfcheck to prove the server starts.
#
# After this, the plugin's mcp/run.sh finds the venv automatically -- no config
# edits needed. Written for bash 3.2 (macOS default) compatibility.
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
  echo "  macOS: 'brew install python@3.12' then re-run this script." >&2
  echo "  (The system /usr/bin/python3 on macOS is often 3.9 -- too old.)" >&2
  exit 1
fi
echo "-- using $PY ($("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])'))"

# 2) venv
if [ ! -x "$VENV/bin/python" ]; then
  echo "-- creating venv at $VENV"
  "$PY" -m venv "$VENV"
else
  echo "-- reusing existing venv at $VENV"
fi

# 3) deps
echo "-- installing dependencies (fastmcp, httpx)"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet -r "$DIR/mcp/requirements.txt"

# 4) credential file template (the PRIMARY credential path -- on macOS, GUI
#    apps often do not inherit launchctl setenv variables, so a chmod-600 env
#    file is the reliable mechanism; empty lines are ignored by the server)
ENVF="$HOME/.prisma-sase.env"
if [ ! -f "$ENVF" ]; then
  cat > "$ENVF" <<'EOF'
# prisma-sase credentials -- fill in the values below (KEY=VALUE, no quotes needed).
# This file is the recommended way to provide credentials on macOS.
# Keep it private: chmod 600 ~/.prisma-sase.env
PRISMA_CLIENT_ID=
PRISMA_CLIENT_SECRET=
PRISMA_TSG_ID=
PRISMA_REGION=sg
EOF
  chmod 600 "$ENVF"
  echo "-- created credential template $ENVF (chmod 600) -- fill in your values"
else
  echo "-- keeping existing $ENVF"
fi

# 5) prove the server starts (offline, no credentials needed)
echo "-- running selfcheck (mock mode)"
PRISMA_MOCK=1 "$VENV/bin/python" "$DIR/mcp/server.py" --selfcheck

echo ""
echo "== install complete =="
echo "venv python : $VENV/bin/python"
echo "next steps  :"
echo "  1. Fill in your read-only service-account values in $ENVF"
echo "     (create the account in Strata Cloud Manager if you haven't)."
echo "  2. Upload the .plugin file in Claude Desktop: Settings > Plugins > Upload from file."
echo "     (mcp/run.sh finds this venv automatically -- no .mcp.json edits needed.)"
echo "  3. Verify:  $VENV/bin/python \"$DIR/mcp/server.py\" --selfcheck"
echo "  4. First run against a real tenant: ask Claude to run discover_insights"
echo "     (or:  $VENV/bin/python \"$DIR/mcp/server.py\" --discover )"
echo "     to find your tenant's real Insights resource/view names."
