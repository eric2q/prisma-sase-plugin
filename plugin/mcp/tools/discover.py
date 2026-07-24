"""discover_insights -- probe the tenant's real Insights 3.0 resource/view names.

Field report 2026-07-23 #2: the tenant rejected the best-guess names for
mobile-users and remote-networks with HTTP 400, and finding the real ones by
hand means trial-and-error against 400s. This tool automates that: it probes a
candidate list (all READ-ONLY query POSTs -- the same endpoint the normal tools
use), reports what works, shows each working view's field names (which also
solves severity/property mapping), and emits a paste-ready PRISMA_INSIGHTS_MAP.

Candidate naming rationale: public docs confirm ``applications/application_list``
-- note the SINGULAR "application" in the view -- so for every family we try
both ``<singular>_list`` and ``<plural>_list``, plus resources named in the
Insights 3.0 docs navigation (users / agent_users / sites / tunnels ...).
``applications/application_list`` itself is probed as a CONTROL: if even that
fails, the problem is auth/region/payload -- not names -- and the tool says so.
"""
import config
from client import SaseClient, SaseApiError, records_of

# (kind, resource, view) candidates, most-likely first.
# Round-2 live results (the live tenant (sg)): users/users_list ✅ (time_filter),
# tunnels/tunnel_list ✅ 13 rows (time_filter), alerts/alerts_list ✅ but
# AGGREGATE (counts only). Rejected there: mobile_users/*, remote_networks/*,
# sites/site_list, agent_users/*, branch_users/*, tunnels/tunnels_list.
# Verified names lead; rejected ones stay as later candidates for other tenants.
CANDIDATES = [
    # control -- documented, should work if auth/region/payload are right
    ("control",         "applications",    "application_list"),
    # alerts (aggregate view -- counts by MU/RN/SC)
    ("alerts",          "alerts",          "alerts_list"),
    # alerts detail -- the per-alert view (severity/message) is NOT yet
    # identified on the live tenant; these are the candidates to probe.
    ("alerts_detail",   "alerts",          "alert_list"),
    ("alerts_detail",   "alerts",          "alert_detail"),
    ("alerts_detail",   "alerts",          "alerts_detail"),
    ("alerts_detail",   "alerts",          "alert_event_list"),
    ("alerts_detail",   "alerts",          "active_alert_list"),
    ("alerts_detail",   "alerts",          "raised_alert_list"),
    # connected users -- users/users_list live-verified
    ("connected_users", "users",           "users_list"),
    ("connected_users", "users",           "user_list"),
    ("connected_users", "mobile_users",    "mobile_user_list"),
    ("connected_users", "mobile_users",    "mobile_users_list"),
    ("connected_users", "agent_users",     "agent_user_list"),
    ("connected_users", "branch_users",    "branch_user_list"),
    # remote networks / tunnels -- tunnels/tunnel_list live-verified
    ("remote_networks", "tunnels",         "tunnel_list"),
    ("remote_networks", "remote_networks", "remote_network_list"),
    ("remote_networks", "remote_networks", "remote_networks_list"),
    ("remote_networks", "sites",           "site_list"),
    ("remote_networks", "tunnels",         "tunnels_list"),
]

_MAX_SAMPLE_FIELDS = 25


def discover_insights(kind=None, tsg_id=None, region=None):
    """Probe candidates (optionally one kind) and report what this tenant accepts."""
    valid_kinds = sorted({c[0] for c in CANDIDATES if c[0] != "control"})
    if kind not in (None, "") and kind not in valid_kinds:
        return {"ok": False,
                "error": "Unknown kind '%s'. Valid kinds: %s"
                         % (kind, ", ".join(valid_kinds))}
    wanted = [c for c in CANDIDATES
              if kind in (None, "") or c[0] in (kind, "control")]

    client = SaseClient()
    time_rules = [{"property": config.FILTER_PROP_TIME,
                   "operator": "last_n_hours", "values": [1]}]
    probes = []
    working = {}

    for probe_kind, resource, view in wanted:
        entry = {"kind": probe_kind, "resource": resource, "view": view}
        outcome = None
        # Try the empty filter first (isolates NAME problems from FILTER
        # problems), then the time filter -- some views require one.
        for variant, rules in (("empty_filter", []), ("time_filter", time_rules)):
            try:
                raw = client.insights_probe(resource, view, filter_rules=rules,
                                            tsg_id=tsg_id, region=region)
            except SaseApiError as e:
                outcome = {"status": "http_%s" % (e.status or "error"),
                           "error": str(e)}
                continue  # try the next payload variant
            records = records_of(raw)
            fields = []
            if records and isinstance(records[0], dict):
                fields = list(records[0].keys())[:_MAX_SAMPLE_FIELDS]
            outcome = {"status": "ok", "payload_variant": variant,
                       "record_count": len(records), "sample_fields": fields}
            break
        entry.update(outcome or {"status": "error"})
        probes.append(entry)
        if entry["status"] == "ok" and probe_kind != "control":
            working.setdefault(probe_kind, []).append(entry)

    control_ok = any(p["kind"] == "control" and p["status"] == "ok" for p in probes)

    notes = []
    if not control_ok and not config.MOCK_MODE:
        notes.append(
            "CONTROL FAILED: even the documented applications/application_list "
            "probe did not succeed -- the problem is auth, region, permissions "
            "or payload, NOT resource/view names. Fix that first (run "
            "--selfcheck) before trusting any probe result.")
    suggested = {}
    for k, entries in working.items():
        best = entries[0]
        suggested[k] = {"resource": best["resource"], "view": best["view"],
                        "verified": True,
                        "payload": best.get("payload_variant", "time_filter")}
    if suggested:
        notes.append(
            "To adopt these permanently, set the environment variable "
            "PRISMA_INSIGHTS_MAP to the suggested_insights_map JSON below "
            "(e.g. add one line to ~/.prisma-sase.env: "
            "PRISMA_INSIGHTS_MAP=<the JSON on a single line>). "
            "sample_fields shows each view's real field names -- if severity/"
            "state/time properties differ from the defaults, override them via "
            "PRISMA_FILTER_SEVERITY_PROP / _STATE_PROP / _TIME_PROP.")
    missing = sorted({c[0] for c in wanted if c[0] != "control"} - set(working))
    if missing:
        notes.append(
            "No working candidate found for: %s. The tenant may expose these "
            "under other names -- capture one working query from the SASE UI "
            "(browser dev tools) or the API reference for this tenant version, "
            "then set PRISMA_INSIGHTS_MAP manually." % ", ".join(missing))

    return {"ok": True,
            "control_probe_ok": control_ok,
            "probes": probes,
            "working": {k: [{"resource": e["resource"], "view": e["view"],
                             "payload_variant": e["payload_variant"],
                             "record_count": e["record_count"]}
                            for e in v] for k, v in working.items()},
            "suggested_insights_map": suggested,
            "notes": notes}
