"""Offline sample data for PRISMA_MOCK=1.

Lets the server start, be smoke-tested, and be demoed without a live tenant or
credentials. Shapes mirror the LIVE tenant findings (round-2 field report,
2026-07-23): tunnels/tunnel_list field names (tunnel_state_name etc.), the
aggregate alerts/alerts_list shape, and a per-alert detail view. The tool layer
slims these the same way it slims real responses, so a mock run exercises the
real code path end-to-end.
"""

_ALERT_ROWS = [
    {"alert_id": "A-10231", "severity": "critical", "state": "raised",
     "category": "connectivity",
     "message": "Service Connection SC-TPE-01 tunnel down",
     "raised_time": "2026-07-23T01:12:00Z", "location": "tpe"},
    {"alert_id": "A-10230", "severity": "high", "state": "raised",
     "category": "capacity", "message": "RN-US-EAST bandwidth > 85%",
     "raised_time": "2026-07-22T20:40:00Z", "location": "us-east"},
    {"alert_id": "A-10228", "severity": "medium", "state": "raised",
     "category": "adem",
     "message": "Experience score degraded for app o365",
     "raised_time": "2026-07-22T16:05:00Z", "location": "de"},
    {"alert_id": "A-10225", "severity": "low", "state": "cleared",
     "category": "info", "message": "Config push completed",
     "raised_time": "2026-07-22T09:30:00Z", "location": "-"},
]

# NOTE: throughput values are Kbps (matching the live API) -- e.g. 8042.58
# Kbps ~= 8 Mbps. The tool layer renames these to *_kbps on output.
_TUNNEL_ROWS = [
    {"node_type": "remote_network", "site_name": "US-East-Branch",
     "edge_location_display_name": "US East", "tunnel_name": "RN-US-EAST-ipsec1",
     "transport_type": "ipsec", "avg_throughput": 5210.4,
     "peak_throughput": 8042.58, "p95_throughput": 7103.9,
     "source_ip": "203.0.113.10", "destination_ip": "198.51.100.1",
     "tunnel_state": 1, "tunnel_state_name": "Up",
     "tunnel_monitoring_state": 1, "tunnel_monitoring_state_name": "Enabled"},
    {"node_type": "remote_network", "site_name": "EU-Central-Branch",
     "edge_location_display_name": "Frankfurt", "tunnel_name": "RN-EU-CENTRAL-ipsec1",
     "transport_type": "ipsec", "avg_throughput": 962.1,
     "peak_throughput": 1504.7, "p95_throughput": 1287.3,
     "source_ip": "203.0.113.20", "destination_ip": "198.51.100.2",
     "tunnel_state": 1, "tunnel_state_name": "Up",
     "tunnel_monitoring_state": 1, "tunnel_monitoring_state_name": "Enabled"},
    {"node_type": "service_connection", "site_name": "TPE-DC",
     "edge_location_display_name": "Taipei", "tunnel_name": "SC-TPE-01-ipsec1",
     "transport_type": "ipsec", "avg_throughput": 0.0,
     "peak_throughput": 0.0, "p95_throughput": 0.0,
     "source_ip": "203.0.113.30", "destination_ip": "198.51.100.3",
     "tunnel_state": 0, "tunnel_state_name": "Down",
     "tunnel_monitoring_state": 0, "tunnel_monitoring_state_name": "Disabled"},
]


def insights(kind, filter_rules=None):
    """Return canned Insights 3.0-style payloads keyed by query kind."""
    if kind == "alerts":
        # Live shape: alerts_list is an AGGREGATE view (counts only).
        return {"data": [
            {"sub_tenant_id": "-", "total_count": 4, "mu_count": 1,
             "rn_count": 2, "sc_count": 1},
        ]}
    if kind == "alerts_detail":
        # Per-alert detail view (severity/message) -- the happy path.
        return {"data": list(_ALERT_ROWS)}
    if kind == "connected_users":
        return {"data": [
            {"location": "Taipei", "region": "as", "connected_users": 512},
            {"location": "Singapore", "region": "as", "connected_users": 341},
            {"location": "Frankfurt", "region": "de", "connected_users": 220},
            {"location": "New York", "region": "us", "connected_users": 167},
        ], "summary": {"total_connected": 1240, "trend_1h_pct": -3.5}}
    if kind in ("remote_networks", "tunnels"):
        return {"data": list(_TUNNEL_ROWS)}
    return {"data": []}


def probe(resource, view):
    """Canned discovery probes mirroring the live tenant's acceptance set."""
    ok_views = {
        ("applications", "application_list"): ["app_name", "num_users",
                                               "risk_score"],
        ("alerts", "alerts_list"): ["sub_tenant_id", "total_count", "mu_count",
                                    "rn_count", "sc_count"],
        ("alerts", "alert_list"): ["alert_id", "severity", "state", "message",
                                   "raised_time", "location"],
        ("users", "users_list"): ["user_name", "location", "source_ip",
                                  "login_time"],
        ("tunnels", "tunnel_list"): ["node_type", "site_name", "tunnel_name",
                                     "transport_type", "tunnel_state",
                                     "tunnel_state_name",
                                     "tunnel_monitoring_state_name"],
    }
    fields = ok_views.get((resource, view))
    if fields is None:
        from client import SaseApiError
        # Mirror the live error identity (issue #3) so discovery's failure
        # classification is exercised in mock mode too.
        raise SaseApiError("Not found (mock 400) on %s/%s." % (resource, view),
                           status=400, api_code="DATA10003",
                           api_message="Invalid resource '/%s/%s.json'"
                                       % (resource, view))
    return {"data": [dict((f, "sample") for f in fields)]}


def adem(subpath, params):
    """Return a canned ADEM telemetry payload for the score endpoint."""
    if "score" in subpath:
        user = params.get("user") or params.get("agent")
        data = {
            "overall_score": 74 if user else 82,
            "components": {"lan": 91, "wifi": 78, "dns": 69, "app": 80},
            "endpoint_type": params.get("endpoint-type", "muAgent"),
            "window": {"start": params.get("start"), "end": params.get("end")},
        }
        if user:
            data["user"] = user
        return {"data": data}
    return {"data": {}}
