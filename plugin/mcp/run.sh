#!/usr/bin/env bash
# Launcher for the prisma-sase MCP server.
#
# Why this exists (v0.2.0): hard-coding "command": "python3" broke on macOS,
# where the system python3 is often 3.9 (< fastmcp's 3.10 floor) -- the server
# died silently and the tools never appeared. This wrapper picks a suitable
# interpreter, in order:
#
#   1. $PRISMA_PYTHON               (explicit override, absolute path)
#   2. ~/.prisma-sase-venv/bin/python   (the venv install.sh creates)
#   3. python3.13 / 3.12 / 3.11 / 3.10 on PATH
#   4. python3 (server.py itself still guards the version and errors clearly)
#
# Written for bash 3.2 (macOS default) compatibility.
set -eu

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Breadcrumb log (cloud feedback #1): in remote/cloud sessions stderr is
# invisible to the user, so a silent launch death leaves no trace. Record the
# launch attempt (overwrite) here; later fatal errors append to the same file
# (server.py does too). Purely diagnostic -- never fails the launch.
LOG="$HOME/.prisma-sase-launch.log"
_crumb() { echo "[$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo -)] $1" >> "$LOG" 2>/dev/null || true; }
: > "$LOG" 2>/dev/null || true
_crumb "run.sh invoked (dir=$DIR)"

candidates=""
if [ -n "${PRISMA_PYTHON:-}" ]; then
  candidates="$PRISMA_PYTHON"
fi
candidates="$candidates $HOME/.prisma-sase-venv/bin/python python3.13 python3.12 python3.11 python3.10 python3"

for py in $candidates; do
  if command -v "$py" >/dev/null 2>&1; then
    if "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
      _crumb "launching with $(command -v "$py")"
      exec "$py" "$DIR/server.py" "$@"
    fi
  fi
done

_crumb "FATAL: no Python >= 3.10 found on PATH ($PATH)"
echo "ERROR: prisma-sase MCP server needs Python >= 3.10 and none was found." >&2
echo "  Fix one of:" >&2
echo "   - run the plugin's install.sh to create ~/.prisma-sase-venv, or" >&2
echo "   - install Python (e.g. 'brew install python@3.12'), or" >&2
echo "   - set PRISMA_PYTHON to an absolute path of a Python >= 3.10." >&2
echo "  Diagnostic breadcrumb written to $LOG" >&2
exit 1
