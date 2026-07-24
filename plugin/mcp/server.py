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

# --- Hard floor FIRST: fastmcp needs Python >= 3.10 (v0.2.0, install report #3/#5).
# On macOS the system python3 is often 3.9 -- without this guard the server just
# dies and the tools silently never appear.
if sys.version_info < (3, 10):
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

    print("prisma-sase selfcheck")
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
    if d["unexpanded_placeholders"]:
        print("  placeholders: WARNING -- literal ${...} received for: %s"
              % ", ".join(d["unexpanded_placeholders"]))
        print("                %s" % config.placeholder_hint())
    else:
        print("  placeholders: none detected")

    if missing_pkgs:
        print("\nRESULT: NOT READY -- install deps into THIS interpreter:")
        print("  %s -m pip install -r %s" % (
            d["executable"],
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")))
        return 1
    if d["mock_mode"]:
        print("\nRESULT: READY (mock mode -- no live API calls)")
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
    sys.stderr.write(
        "ERROR: missing package(s) %s for this interpreter:\n"
        "       %s\n"
        "Fix:   %s -m pip install -r %s\n"
        "       (or run the plugin's install.sh, or point PRISMA_PYTHON at a\n"
        "       Python >= 3.10 that has the dependencies installed)\n"
        % (", ".join(_missing_pkgs), sys.executable, sys.executable, _req))
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
    vague "how is SASE doing / any problems right now?" questions. Read-only.
    Optional tsg_id/region override the default tenant (handy for multi-customer
    demos)."""
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
