#!/usr/bin/env bash
# Launcher for the prisma-sase MCP server.
#
# Legacy path since 0.9.0: the supported launch is `uvx --from git+...
# prisma-sase-mcp`, which brings its own interpreter and needs no wrapper.
# This is kept for venv installs made before 0.9.0 and for hosts with no uv.
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

# A stale ~/.prisma-sase-venv is silently skipped below (a Python upgrade can
# leave its symlinked interpreter dangling). Say so in the log -- the 0.8.0
# field report spent three rounds on exactly this ambiguity.
# NOTE: -e follows symlinks, so a DANGLING symlink (the usual broken-venv
# shape after a Python upgrade) is invisible to -e alone -- test -L too.
VENV_PY="$HOME/.prisma-sase-venv/bin/python"
if [ -L "$VENV_PY" ] && [ ! -e "$VENV_PY" ]; then
  _crumb "WARNING: $VENV_PY is a DANGLING symlink -- the Python it was built against moved or was removed (typical after a Python upgrade). Recreate the venv: rm -rf ~/.prisma-sase-venv && bash install.sh"
elif { [ -e "$VENV_PY" ] || [ -L "$VENV_PY" ]; } && [ ! -x "$VENV_PY" ]; then
  _crumb "WARNING: $VENV_PY exists but is not executable -- broken venv; recreate it (rm -rf ~/.prisma-sase-venv && bash install.sh)"
elif [ ! -e "$VENV_PY" ]; then
  _crumb "note: $VENV_PY not present -- will try system interpreters (which usually lack the packages)"
fi

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

# Last resort (0.8.0 field report P1): rather than dying invisibly, serve the
# stdlib-only setup server with ANY python we can find, so the assistant is
# told what is wrong instead of the tools just not existing.
if [ $# -eq 0 ]; then
  for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1; then
      _crumb "starting dependency-free setup server with $(command -v "$py")"
      exec "$py" "$DIR/setup_server.py"
    fi
  done
fi
exit 1
