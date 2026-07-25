#!/usr/bin/env python3
"""Dependency-free fallback MCP server: reports WHY the real server can't run.

Field report (0.8.0, macOS Cowork): when the chosen interpreter lacked
fastmcp/httpx, the real server exited and the whole toolset simply vanished
from the conversation -- no error, no hint, nothing pointing at the launch
log. Diagnosing it took three rounds across two sessions.

This module is the fix. It speaks just enough MCP (stdio JSON-RPC:
initialize / tools/list / tools/call / ping) using ONLY the standard library,
so it starts even when nothing is installed and even on a Python below the
3.10 floor. It exposes a single tool whose NAME and DESCRIPTION already carry
the problem, so the assistant sees the failure in its tool list without
calling anything -- and one call returns the exact fix.

Kept deliberately simple and 3.6-compatible: this file must never be the
thing that fails.
"""
import json
import os
import platform
import sys

PROTOCOL_VERSION = "2024-11-05"
REQUIRED_PACKAGES = ("fastmcp", "httpx")
MIN_PYTHON = (3, 10)

HERE = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS = os.path.join(HERE, "requirements.txt")
SERVER_PY = os.path.join(HERE, "server.py")
LAUNCH_LOG = os.path.expanduser("~/.prisma-sase-launch.log")


def _missing_packages():
    missing = []
    for name in REQUIRED_PACKAGES:
        try:
            __import__(name)
        except Exception:
            missing.append(name)
    return missing


def _venv_paths():
    """The venv the launcher prefers, plus whether it looks usable."""
    if os.name == "nt":
        venv_py = os.path.expanduser(
            "~\\.prisma-sase-venv\\Scripts\\python.exe")
    else:
        venv_py = os.path.expanduser("~/.prisma-sase-venv/bin/python")
    return venv_py, os.path.exists(venv_py), os.access(venv_py, os.X_OK)


def diagnose():
    """Human-readable report: what is wrong and the exact commands to fix it."""
    missing = _missing_packages()
    too_old = sys.version_info < MIN_PYTHON
    venv_py, venv_exists, venv_usable = _venv_paths()

    lines = ["prisma-sase MCP server is NOT running -- setup is incomplete.", ""]
    lines.append("Diagnosis")
    lines.append("  interpreter:  Python %d.%d.%d at %s"
                 % (sys.version_info[0], sys.version_info[1],
                    sys.version_info[2], sys.executable))
    lines.append("  platform:     %s" % platform.platform(terse=True))
    if too_old:
        lines.append("  problem:      Python is older than the 3.10 required "
                     "by fastmcp")
    if missing:
        lines.append("  problem:      missing package(s) for THIS interpreter: %s"
                     % ", ".join(missing))
    if venv_exists and not venv_usable:
        lines.append("  note:         %s exists but is not executable -- a "
                     "broken virtualenv (common after a Python upgrade "
                     "relocates the interpreter it was built against). "
                     "Recreating it fixes this." % venv_py)
    elif not venv_exists:
        lines.append("  note:         %s does not exist, so the launcher fell "
                     "back to a system interpreter that has no packages."
                     % venv_py)

    lines.append("")
    lines.append("Fix (recreate the plugin's virtualenv -- the launcher finds "
                 "it automatically):")
    if os.name == "nt":
        lines.append("  rmdir /s /q \"%USERPROFILE%\\.prisma-sase-venv\"")
        lines.append("  py -3 -m venv \"%USERPROFILE%\\.prisma-sase-venv\"")
        lines.append("  \"%USERPROFILE%\\.prisma-sase-venv\\Scripts\\python.exe\" "
                     "-m pip install -r \"" + REQUIREMENTS + "\"")
    else:
        lines.append("  rm -rf ~/.prisma-sase-venv")
        lines.append("  python3 -m venv ~/.prisma-sase-venv")
        lines.append("  ~/.prisma-sase-venv/bin/python -m pip install -r %s"
                     % REQUIREMENTS)
    lines.append("")
    lines.append("Then verify, and RESTART the Claude app completely "
                 "(macOS: Cmd-Q, not just closing the window -- a plugin "
                 "server is only relaunched on a full restart):")
    if os.name == "nt":
        lines.append("  \"%USERPROFILE%\\.prisma-sase-venv\\Scripts\\python.exe\" "
                     "\"" + SERVER_PY + "\" --selfcheck")
    else:
        lines.append("  ~/.prisma-sase-venv/bin/python %s --selfcheck"
                     % SERVER_PY)
    lines.append("")
    lines.append("More detail: the launch breadcrumb at %s records which "
                 "interpreter was chosen and why startup failed."
                 % LAUNCH_LOG)
    return "\n".join(lines)


def _summary():
    """One-line problem statement used in the tool description."""
    missing = _missing_packages()
    if sys.version_info < MIN_PYTHON:
        return ("Python %d.%d is below the required 3.10"
                % sys.version_info[:2])
    if missing:
        return "missing package(s): %s" % ", ".join(missing)
    return "startup prerequisites are not met"


TOOL_NAME = "prisma_sase_setup_required"


def _tool_definition():
    return {
        "name": TOOL_NAME,
        "description": (
            "SETUP INCOMPLETE -- the Prisma SASE tools are unavailable in this "
            "session because %s. The normal tools (get_sase_status, "
            "query_alerts, get_remote_networks, get_connected_users, "
            "get_user_experience, discover_insights) are NOT loaded, so no "
            "tenant data can be queried. Call this tool to get the exact "
            "diagnosis and the copy-paste commands that fix it, and show them "
            "to the user -- do not attempt to answer SASE questions from "
            "memory or guesswork." % _summary()),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    }


def _send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def _result(req_id, payload):
    _send({"jsonrpc": "2.0", "id": req_id, "result": payload})


def _error(req_id, code, message):
    _send({"jsonrpc": "2.0", "id": req_id,
           "error": {"code": code, "message": message}})


def serve():
    """Minimal MCP stdio loop. Returns when stdin closes."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method")
        req_id = msg.get("id")
        if req_id is None:          # notification -- never answered
            continue

        if method == "initialize":
            requested = (msg.get("params") or {}).get("protocolVersion")
            _result(req_id, {
                "protocolVersion": (requested if isinstance(requested, str)
                                    else PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "prisma-sase (setup required)",
                               "version": "0.0.0-setup"},
            })
        elif method == "tools/list":
            _result(req_id, {"tools": [_tool_definition()]})
        elif method == "tools/call":
            name = (msg.get("params") or {}).get("name")
            if name == TOOL_NAME:
                _result(req_id, {
                    "content": [{"type": "text", "text": diagnose()}],
                    "isError": False,
                })
            else:
                _result(req_id, {
                    "content": [{"type": "text", "text":
                                 "Only '%s' is available: the Prisma SASE "
                                 "server did not start.\n\n%s"
                                 % (TOOL_NAME, diagnose())}],
                    "isError": True,
                })
        elif method == "ping":
            _result(req_id, {})
        else:
            _error(req_id, -32601, "Method not found: %s" % method)


def main():
    if "--print" in sys.argv:       # human use / tests
        print(diagnose())
        return 0
    try:
        serve()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
