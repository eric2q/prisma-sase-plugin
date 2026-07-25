#!/usr/bin/env python3
"""Prisma SASE MCP server -- Phase 1 (read-only).

Exposes four read-only tools over stdio for Claude Desktop / Cowork:
    get_sase_status, query_alerts, get_connected_users, get_user_experience

Design doc sec.8/sec.10: stdio transport, credentials from environment only,
and no write/commit/push path anywhere. Set PRISMA_MOCK=1 to run offline with
sample data (no credentials or network required).

Diagnostics:
    python server.py --selfcheck   interpreter/deps/credential status, then exit
    python server.py --discover    probe the tenant's real Insights resource/view
                                   names (read-only), print JSON, then exit
"""
import sys


def _breadcrumb(msg):
    """Append a diagnostic line to ~/.prisma-sase-launch.log; never raises.

    Cloud feedback #1: in remote/cloud sessions the user cannot see stderr, so
    a fatal init error leaves no trace. This file is the post-mortem trail
    (run.sh writes the launch attempt; fatal paths here append the cause).
    """
    try:
        import datetime
        import os as _os
        with open(_os.path.expanduser("~/.prisma-sase-launch.log"), "a",
                  encoding="utf-8") as fh:
            fh.write("[%s] %s\n" % (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _venv_fix_lines(req_path):
    """The recommended dependency fix: a dedicated venv, matching run.sh's
    search order -- NOT the system interpreter (Debian/Ubuntu PEP 668 blocks
    system pip installs; cloud feedback #4)."""
    import os as _os
    server_path = _os.path.join(_os.path.dirname(_os.path.abspath(req_path)),
                                "server.py")
    if sys.platform == "win32":
        venv_py = "%USERPROFILE%\\.prisma-sase-venv\\Scripts\\python.exe"
        return [
            "  py -3 -m venv %USERPROFILE%\\.prisma-sase-venv",
            "  %s -m pip install -r %s" % (venv_py, req_path),
            "  %s %s --selfcheck" % (venv_py, server_path),
        ]
    venv_py = "~/.prisma-sase-venv/bin/python"
    return [
        "  python3 -m venv ~/.prisma-sase-venv",
        "  %s -m pip install -r %s" % (venv_py, req_path),
        "  PRISMA_MOCK=1 %s %s --selfcheck" % (venv_py, server_path),
    ]


# --- Hard floor FIRST: fastmcp needs Python >= 3.10 (v0.2.0, install report #3/#5).
# On macOS the system python3 is often 3.9 -- without this guard the server just
# dies and the tools silently never appear.
if sys.version_info < (3, 10):
    _breadcrumb("FATAL: Python %d.%d.%d at %s is below the 3.10 floor"
                % (sys.version_info[0], sys.version_info[1],
                   sys.version_info[2], sys.executable))
    sys.stderr.write(
        "ERROR: prisma-sase MCP server requires Python >= 3.10; this is "
        "Python %d.%d.%d at %s\n"
        "Fix one of:\n"
        "  - run the plugin's install.sh (macOS/Linux) or install.bat (Windows)\n"
        "    to create the ~/.prisma-sase-venv virtualenv, or\n"
        "  - install a newer Python (macOS: 'brew install python@3.12'; "
        "Windows: python.org), or\n"
        "  - set PRISMA_PYTHON to a Python >= 3.10 (the run.sh/run.cmd "
        "launcher will use it).\n"
        % (sys.version_info[0], sys.version_info[1], sys.version_info[2],
           sys.executable))
    # Same reasoning as the dependency check below (0.8.0 field report P1):
    # serve the stdlib-only setup server so the assistant can see and relay
    # the problem instead of the tools silently disappearing. setup_server is
    # deliberately 3.6-compatible so it runs on this too-old interpreter.
    if len(sys.argv) == 1:
        import os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
        try:
            import setup_server
            _breadcrumb("starting dependency-free setup server "
                        "(Python too old)")
            sys.exit(setup_server.main())
        except Exception as _exc:      # never let the fallback mask the error
            sys.stderr.write("(setup-status server unavailable: %s)\n" % _exc)
    sys.exit(1)

import importlib.util
import logging
import os

# Make sibling modules (config, auth, client) and the tools/ package importable
# when the MCP host launches this file directly as a script.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Logs MUST go to stderr -- stdout is the JSON-RPC channel for stdio transport.
logging.basicConfig(
    level=os.environ.get("PRISMA_LOG_LEVEL", "INFO").upper(),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("prisma_sase.server")

import config  # stdlib-only import; safe even when deps are missing


def _selfcheck():
    """Print a human-readable readiness report and exit. No MCP startup."""
    d = config.env_diagnostics()
    missing_pkgs = [p for p in ("fastmcp", "httpx")
                    if importlib.util.find_spec(p) is None]

    print("prisma-sase selfcheck (plugin v%s)" % config.PLUGIN_VERSION)
    _stale = config.stale_version_check()
    if _stale:
        print("  UPDATE PENDING: v%s is installed on disk but this code is "
              "v%s.\n                  Restart the app to load it (Desktop: "
              "Cmd-Q; CLI: /reload-plugins)."
              % (_stale["installed"], _stale["running"]))
    print("  python:       %s  (%s)" % (d["python"], d["executable"]))
    print("  packages:     %s" % ("fastmcp OK, httpx OK" if not missing_pkgs
                                  else "MISSING: " + ", ".join(missing_pkgs)))
    print("  mock mode:    %s" % ("ON (PRISMA_MOCK set)" if d["mock_mode"] else "off"))
    print("  env file:     %s" % (
        "%s (supplied: %s)" % (d["env_file"], ", ".join(d["env_file_keys"]) or "none")
        if d["env_file"] else "none found (~/.prisma-sase.env)"))
    print("  region:       %s" % (d["region"] or "(not set)"))
    print("  credentials:  %s" % ("all 4 required vars set" if not d["missing"]
                                  else "MISSING: " + ", ".join(d["missing"])))
    # userConfig values reach the MCP server process only -- a hand-run
    # selfcheck cannot see them. Say so loudly, or the "MISSING" line above
    # gets read as "the user never configured the plugin" (it did, once).
    _pcfg = config.plugin_config_snapshot()
    if _pcfg:
        print("  plugin config: %s has %s set via the enable dialog"
              % (_pcfg["plugin_id"], ", ".join(_pcfg["keys"]) or "no options"))
        if d["missing"]:
            print("                 ^ NOTE: those values are injected into the "
                  "MCP SERVER process only, so they are invisible here. A "
                  "'MISSING' line above is EXPECTED when running selfcheck by "
                  "hand and does NOT mean the plugin is unconfigured. The "
                  "Client Secret lives in OS secure storage and never appears "
                  "in %s." % _pcfg["settings_path"])
    _src = {"environment": "environment (host/userConfig dialog or shell)",
            "env_file": "env file (PLAINTEXT -- consider the userConfig "
                        "dialog or PRISMA_SECRET_CMD)",
            "secret_cmd": "PRISMA_SECRET_CMD (keychain/manager-backed)"}
    if d["secret_source"]:
        print("  secret from:  %s" % _src.get(d["secret_source"],
                                              d["secret_source"]))
    elif d["secret_cmd_set"]:
        print("  secret from:  PRISMA_SECRET_CMD is set but returned nothing "
              "-- run it by hand to debug")
    if d["unexpanded_placeholders"]:
        print("  placeholders: WARNING -- literal ${...} received for: %s"
              % ", ".join(d["unexpanded_placeholders"]))
        print("                %s" % config.placeholder_hint())
    else:
        print("  placeholders: none detected")

    if missing_pkgs:
        req = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "requirements.txt")
        print("\nRESULT: NOT READY -- install the dependencies into a "
              "dedicated venv (run.sh/run.cmd find it automatically):")
        for line in _venv_fix_lines(req):
            print(line)
        print("  (avoid installing into the system interpreter -- "
              "Debian/Ubuntu block system pip installs, PEP 668)")
        return 1
    if d["mock_mode"]:
        print("\nRESULT: READY (mock mode -- no live API calls)")
        return 0
    if d["missing"] and _pcfg and not d["unexpanded_placeholders"]:
        print("\nRESULT: DEPENDENCIES READY; credentials not visible from this "
              "shell.\n  The plugin IS configured via the enable dialog (%s). "
              "Those values only\n  reach the MCP server process, so this "
              "hand-run check cannot confirm them.\n  Verify by asking Claude "
              "to run get_sase_status after a full app restart."
              % ", ".join(_pcfg["keys"]))
        return 0
    if d["missing"] or d["unexpanded_placeholders"]:
        print("\nRESULT: NOT READY -- fix the items above "
              "(or set PRISMA_MOCK=1 to try the tools offline).")
        return 1
    print("\nRESULT: READY (live mode)")
    return 0


if "--selfcheck" in sys.argv:
    sys.exit(_selfcheck())

# --- Dependency pre-check: one clear error naming THIS interpreter -----------
_missing_pkgs = [p for p in ("fastmcp", "httpx")
                 if importlib.util.find_spec(p) is None]
if _missing_pkgs:
    _req = os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    _breadcrumb("FATAL: missing package(s) %s for %s"
                % (", ".join(_missing_pkgs), sys.executable))
    sys.stderr.write(
        "ERROR: missing package(s) %s for this interpreter:\n"
        "       %s\n"
        "Fix -- install into a dedicated venv (run.sh finds it automatically;\n"
        "avoid the system interpreter, Debian/Ubuntu block it via PEP 668):\n"
        "%s\n"
        "       (or run the plugin's install.sh / install.bat, or point\n"
        "       PRISMA_PYTHON at a Python >= 3.10 that has the deps)\n"
        % (", ".join(_missing_pkgs), sys.executable,
           "\n".join(_venv_fix_lines(_req))))
    # 0.8.0 field report P1: exiting here made the whole toolset vanish from
    # the conversation with no error the user could see. Instead, serve the
    # dependency-free setup server so the failure and its fix arrive as a
    # tool the assistant can read and relay. CLI invocations (flags present)
    # keep the old exit-with-error behaviour.
    if len(sys.argv) == 1:
        _breadcrumb("starting dependency-free setup server (degraded mode)")
        sys.stderr.write("Starting the setup-status server instead so the "
                         "problem is visible in the conversation.\n")
        import setup_server
        sys.exit(setup_server.main())
    sys.exit(1)

from typing import Optional

from tools.discover import discover_insights as _discover_insights

# --discover: run the read-only endpoint discovery from the CLI (no MCP host
# needed -- credentials come from the environment / ~/.prisma-sase.env).
if "--discover" in sys.argv:
    import json as _json
    _result = _discover_insights()
    print(_json.dumps(_result, indent=2, ensure_ascii=False))
    sys.exit(0 if _result.get("ok") and _result.get("control_probe_ok") else 1)

from fastmcp import FastMCP

from tools.status import get_sase_status as _get_sase_status
from tools.alerts import query_alerts as _query_alerts
from tools.networks import get_remote_networks as _get_remote_networks
from tools.users import get_connected_users as _get_connected_users
from tools.adem import get_user_experience as _get_user_experience

mcp = FastMCP("prisma-sase")


def _audit(tool, **params):
    """Per-call audit log: tool name + non-null param summary only.

    Never logs the token, the client secret, or any response body (design doc
    sec.7). tsg_id/region are operational context, not secrets, so they are kept
    to make multi-tenant demos traceable.
    """
    summary = {k: v for k, v in params.items() if v is not None}
    log.info("tool_call %s %s", tool, summary)


@mcp.tool()
def get_sase_status(tsg_id: Optional[str] = None,
                    region: Optional[str] = None) -> dict:
    """Prisma SASE health overview in a single call: alert counts by severity,
    tunnel up/down for remote networks & service connections, currently
    connected Mobile Users, and the overall ADEM experience score. Use this for
    vague "how is SASE doing / any problems right now?" questions. Also returns
    plugin_version -- use it when the user asks which plugin version they are
    running. Read-only. Optional tsg_id/region override the default tenant
    (handy for multi-customer demos)."""
    _audit("get_sase_status", tsg_id=tsg_id, region=region)
    return _get_sase_status(tsg_id=tsg_id, region=region)


@mcp.tool()
def query_alerts(severity: Optional[str] = None, state: Optional[str] = None,
                 hours: int = 24, limit: int = 20,
                 tsg_id: Optional[str] = None, region: Optional[str] = None) -> dict:
    """Query Prisma Access alerts (Insights 3.0). Filter by severity
    (critical/high/medium/low), state (e.g. raised/cleared), and a look-back
    window in hours (default 24). Returns counts by severity plus a slimmed,
    paginated list (limit default 20, max 100). Read-only."""
    _audit("query_alerts", severity=severity, state=state, hours=hours,
           limit=limit, tsg_id=tsg_id, region=region)
    return _query_alerts(severity=severity, state=state, hours=hours,
                         limit=limit, tsg_id=tsg_id, region=region)


@mcp.tool()
def get_remote_networks(state: Optional[str] = None, hours: int = 1,
                        limit: int = 20, tsg_id: Optional[str] = None,
                        region: Optional[str] = None) -> dict:
    """Tunnel status rows for Remote Networks / Service Connections (Insights
    3.0 tunnels view): per-tunnel site, name, type, up/down state, monitoring
    state, throughput and endpoints. Use for "list tunnel status", "which
    tunnels are down", "分點連線狀態". Optional state filter ('up'/'down').
    hours is the look-back window (1 = current state).
    UNITS: throughput fields are in Kbps (field names end in _kbps; divide by
    1000 for Mbps -- 8042.58 means ~8 Mbps, NOT 8 Gbps), and 'peak' is the max
    per-minute sample within the time bucket, not an absolute instantaneous
    value. Read-only."""
    _audit("get_remote_networks", state=state, hours=hours, limit=limit,
           tsg_id=tsg_id, region=region)
    return _get_remote_networks(state=state, hours=hours, limit=limit,
                                tsg_id=tsg_id, region=region)


@mcp.tool()
def get_connected_users(hours: int = 24, limit: int = 20,
                        tsg_id: Optional[str] = None,
                        region: Optional[str] = None) -> dict:
    """Currently connected Mobile Users: total count, short-term trend, and
    distribution by location (Insights 3.0). Read-only."""
    _audit("get_connected_users", hours=hours, limit=limit,
           tsg_id=tsg_id, region=region)
    return _get_connected_users(hours=hours, limit=limit,
                                tsg_id=tsg_id, region=region)


@mcp.tool()
def get_user_experience(user: Optional[str] = None, app: Optional[str] = None,
                        hours: int = 24, endpoint_type: Optional[str] = None,
                        tsg_id: Optional[str] = None,
                        region: Optional[str] = None) -> dict:
    """ADEM experience score (Telemetry v2): overall, or for a specific
    user/app, with a component breakdown (LAN/WiFi/DNS/app) and a rating band.
    Use when a user "says it's slow" or to check experience health. Scores below
    70 indicate degradation. Read-only."""
    _audit("get_user_experience", user=user, app=app, hours=hours,
           endpoint_type=endpoint_type, tsg_id=tsg_id, region=region)
    return _get_user_experience(user=user, app=app, hours=hours,
                                endpoint_type=endpoint_type,
                                tsg_id=tsg_id, region=region)


@mcp.tool()
def discover_insights(kind: Optional[str] = None,
                      tsg_id: Optional[str] = None,
                      region: Optional[str] = None) -> dict:
    """Probe which Insights 3.0 resource/view names THIS tenant actually
    accepts (read-only query POSTs only). Use when Insights-backed tools return
    HTTP 400, when responses carry a _verify note, or on first setup against a
    new tenant. Includes a documented control probe (applications) to separate
    auth/region problems from naming problems. Returns working names, each
    view's real field names, and a paste-ready PRISMA_INSIGHTS_MAP suggestion.
    Optional kind filters to one family: alerts / connected_users /
    remote_networks."""
    _audit("discover_insights", kind=kind, tsg_id=tsg_id, region=region)
    return _discover_insights(kind=kind, tsg_id=tsg_id, region=region)


def main():
    d = config.env_diagnostics()
    log.info("prisma-sase plugin v%s", config.PLUGIN_VERSION)
    _stale = config.stale_version_check()
    if _stale:
        log.warning("A newer version (v%s) is installed at %s but this process "
                    "runs v%s -- restart the app to load it.",
                    _stale["installed"], _stale["install_root"],
                    _stale["running"])
    log.info("interpreter: Python %s at %s", d["python"], d["executable"])
    if d["env_file"]:
        log.info("env file: %s (supplied: %s)", d["env_file"],
                 ", ".join(d["env_file_keys"]) or "none")
    if d["unexpanded_placeholders"]:
        log.warning("literal ${...} placeholders received for %s -- %s",
                    ", ".join(d["unexpanded_placeholders"]),
                    config.placeholder_hint())
    if config.MOCK_MODE:
        log.info("Starting in MOCK mode (PRISMA_MOCK set) -- no live API calls.")
    elif d["missing"]:
        log.warning("Missing env vars %s -- live calls will return actionable "
                    "errors until these are set. Set PRISMA_MOCK=1 to demo "
                    "offline, or run with --selfcheck to diagnose.", d["missing"])
    log.info("prisma-sase MCP server ready (stdio). Tools: get_sase_status, "
             "query_alerts, get_remote_networks, get_connected_users, "
             "get_user_experience, discover_insights.")
    mcp.run()


if __name__ == "__main__":
    main()
