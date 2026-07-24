"""Central configuration for the Prisma SASE MCP server (Phase 1, read-only).

Design notes
------------
* Secrets come from environment variables ONLY -- never hard-coded, never logged
  (design doc sec.4.1 / sec.7).
* The fixed auth/API facts below are the *verified* values from design doc sec.3
  and must not be changed (handoff note sec.10.2).
* Endpoint resource/view names and filter property names are kept here because
  they are tenant/version dependent and must be confirmed against a live tenant
  (design doc sec.10.3 / sec.11.1). Each carries a ``verified`` flag; anything
  still ``False`` is a documented best-guess default. They can be corrected
  WITHOUT editing code via the ``PRISMA_INSIGHTS_MAP`` / ``PRISMA_*`` env vars.

v0.2.0 hardening (from the first real-world install report)
-----------------------------------------------------------
* **Placeholder detection**: some MCP hosts pass ``${VAR}`` strings from a
  config env block through *literally* instead of expanding them. Any env value
  that looks like ``${...}`` is treated as UNSET and recorded in
  ``PLACEHOLDER_VARS`` so errors can say exactly what happened instead of
  surfacing a confusing downstream 401.
* **Env-file fallback**: if a variable is absent from the environment, values
  are read from ``$PRISMA_ENV_FILE`` or ``~/.prisma-sase.env`` (simple
  ``KEY=VALUE`` lines). Real environment variables always win. This gives users
  a supported path when their host does not forward their shell/launchctl
  environment to the server process.
"""
import json
import os
import re
import sys

# --- Fixed, verified facts (design doc sec.3 -- do NOT change) ---------------
AUTH_URL = "https://auth.apps.paloaltonetworks.com/oauth2/access_token"
API_BASE = "https://api.sase.paloaltonetworks.com"
INSIGHTS_QUERY_PATH = "/insights/v3.0/resource/query/{resource}/{view}"
ADEM_BASE_PATH = "/adem/telemetry/v2"

# --- v0.2.0: placeholder detection + env-file fallback -----------------------
_PLACEHOLDER_RE = re.compile(r"^\s*\$\{[A-Za-z_][A-Za-z0-9_]*\}\s*$")

PLACEHOLDER_VARS = []   # names whose value arrived as a literal ${...}
ENV_FILE_USED = None    # path of the env file actually loaded, if any
ENV_FILE_KEYS = []      # keys adopted from that file


def _is_placeholder(value):
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


def _raw_env(name):
    """Read an env var; a literal ``${...}`` value counts as unset (recorded)."""
    value = os.environ.get(name)
    if value is None:
        return None
    if _is_placeholder(value):
        if name not in PLACEHOLDER_VARS:
            PLACEHOLDER_VARS.append(name)
        return None
    return value


def _load_env_file():
    """Adopt KEY=VALUE pairs from an env file for vars not already set.

    Search order: $PRISMA_ENV_FILE (if set), then ~/.prisma-sase.env.
    Only fills gaps -- a real environment value (non-placeholder) always wins.
    """
    global ENV_FILE_USED
    paths = []
    explicit = _raw_env("PRISMA_ENV_FILE")
    if explicit:
        paths.append(os.path.expanduser(explicit))
    paths.append(os.path.expanduser("~/.prisma-sase.env"))

    for path in paths:
        if not path or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if not key or not value:
                # Empty values (e.g. an unfilled template line) are skipped so
                # they never mask a variable arriving from the environment.
                continue
            current = os.environ.get(key)
            if current is None or current == "" or _is_placeholder(current):
                os.environ[key] = value
                if key not in ENV_FILE_KEYS:
                    ENV_FILE_KEYS.append(key)
        ENV_FILE_USED = path
        return  # first existing file wins


_load_env_file()


def _env(name, default=""):
    value = _raw_env(name)
    return default if value is None else value


# --- Credentials / tenant context (env, with env-file fallback) --------------
CLIENT_ID = _env("PRISMA_CLIENT_ID")
CLIENT_SECRET = _env("PRISMA_CLIENT_SECRET")
DEFAULT_TSG_ID = _env("PRISMA_TSG_ID")
DEFAULT_REGION = _env("PRISMA_REGION")
DEFAULT_SUBTENANT = _env("PRISMA_SUBTENANT_ID")

# --- Behaviour flags ---------------------------------------------------------
MOCK_MODE = _env("PRISMA_MOCK").strip().lower() in ("1", "true", "yes", "on")
try:
    HTTP_TIMEOUT = float(_env("PRISMA_HTTP_TIMEOUT", "30") or "30")
except ValueError:
    HTTP_TIMEOUT = 30.0

# --- Response slimming (design doc sec.4.3) ----------------------------------
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

# --- Token management (design doc sec.3 / sec.4.1) ---------------------------
TOKEN_LIFETIME_FALLBACK = 900   # 15 min, used only if 'expires_in' is absent
TOKEN_RENEW_MARGIN = 120        # refresh when <=2 min remain -> ~13 min effective TTL

# --- Insights 3.0 resource/view map ------------------------------------------
# 'verified: False' == documented best-guess from the <resource>/<resource>_list
# naming convention (only applications/application_list is confirmed in public
# docs). Confirm against a live tenant and flip to True (design doc sec.11.1).
# The verify flag is surfaced in tool responses so callers know when a name is
# still unconfirmed.
# Live-verification state (the live tenant (region sg), 2026-07-23, round 2):
#   * connected_users -> users/users_list       CONFIRMED (needs a time filter)
#   * remote_networks -> tunnels/tunnel_list    CONFIRMED, 13 rows (needs a time filter)
#   * alerts -> alerts/alerts_list              CONFIRMED but it is an AGGREGATE
#     view (fields: sub_tenant_id/total_count/mu_count/rn_count/sc_count) --
#     counts only, NO per-alert severity/message.
#   * alerts_detail: the per-alert view is NOT yet identified -- candidates are
#     probed by discover_insights(kind="alerts_detail").
# "payload" records which filter shape the view accepts (informational; the
# client auto-injects a time filter when the caller provides no rules).
INSIGHTS_MAP = {
    "alerts":          {"resource": "alerts", "view": "alerts_list", "verified": True,
                        "payload": "empty_filter", "aggregate": True},
    "alerts_detail":   {"resource": "alerts", "view": "alert_list", "verified": False},
    "connected_users": {"resource": "users",   "view": "users_list",  "verified": True,
                        "payload": "time_filter"},
    "remote_networks": {"resource": "tunnels", "view": "tunnel_list", "verified": True,
                        "payload": "time_filter"},
    "tunnels":         {"resource": "tunnels", "view": "tunnel_list", "verified": True,
                        "payload": "time_filter"},
}

# Optional whole-or-partial override via env (JSON). Lets a tenant be corrected
# without touching code, e.g.:
#   PRISMA_INSIGHTS_MAP='{"alerts":{"resource":"alerts","view":"alert_list","verified":true}}'
_env_map = _env("PRISMA_INSIGHTS_MAP").strip()
if _env_map:
    try:
        _override = json.loads(_env_map)
        if isinstance(_override, dict):
            for _k, _v in _override.items():
                if isinstance(_v, dict):
                    INSIGHTS_MAP.setdefault(_k, {}).update(_v)
    except ValueError:
        # Malformed override is ignored; documented defaults stand.
        pass

# --- Insights filter property names (tenant/version dependent) ---------------
FILTER_PROP_TIME = _env("PRISMA_FILTER_TIME_PROP", "event_time")
FILTER_PROP_SEVERITY = _env("PRISMA_FILTER_SEVERITY_PROP", "severity")
FILTER_PROP_STATE = _env("PRISMA_FILTER_STATE_PROP", "state")

# --- ADEM defaults (design doc sec.3; confirmed shape from pan.dev) -----------
ADEM_DEFAULT_ENDPOINT_TYPE = _env("PRISMA_ADEM_ENDPOINT_TYPE", "muAgent")
ADEM_DEFAULT_RESPONSE_TYPE = _env("PRISMA_ADEM_RESPONSE_TYPE", "summary")


def resolve_tsg(tsg_id=None):
    """Explicit tsg_id wins, else the default tenant (design doc sec.4.4)."""
    return (tsg_id or DEFAULT_TSG_ID or "").strip()


def resolve_region(region=None):
    return (region or DEFAULT_REGION or "").strip()


def clamp_limit(limit):
    """Clamp a caller-supplied limit into [1, MAX_LIMIT], default on garbage."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    if limit < 1:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)


def missing_credentials():
    """Return the required env vars that are unset (used for actionable errors)."""
    missing = []
    if not CLIENT_ID:
        missing.append("PRISMA_CLIENT_ID")
    if not CLIENT_SECRET:
        missing.append("PRISMA_CLIENT_SECRET")
    if not DEFAULT_TSG_ID:
        missing.append("PRISMA_TSG_ID")
    if not DEFAULT_REGION:
        missing.append("PRISMA_REGION")
    return missing


def placeholder_hint():
    """A precise explanation when the host passed literal ${...} values."""
    if not PLACEHOLDER_VARS:
        return None
    return (
        "Values for %s arrived as literal ${...} placeholders -- the MCP host "
        "passed them through without expanding. Upgrade to plugin >= 0.2.0 "
        "(its .mcp.json no longer uses an env block; variables are inherited "
        "from your environment), or put the values in ~/.prisma-sase.env "
        "(KEY=VALUE lines, chmod 600)." % ", ".join(PLACEHOLDER_VARS)
    )


def env_diagnostics():
    """Structured snapshot used by --selfcheck and startup logging."""
    return {
        "python": "%d.%d.%d" % sys.version_info[:3],
        "executable": sys.executable,
        "mock_mode": MOCK_MODE,
        "missing": missing_credentials(),
        "unexpanded_placeholders": list(PLACEHOLDER_VARS),
        "env_file": ENV_FILE_USED,
        "env_file_keys": list(ENV_FILE_KEYS),
        "region": DEFAULT_REGION or None,
    }
