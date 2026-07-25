"""get_remote_networks -- tunnel status rows via Insights 3.0 (read-only).

Round-2 field report: `tunnels/tunnel_list` is live-verified (13 rows on TSG
the live tenant (sg)) and requires a TIME filter. Its real fields (from discovery):
node_type, site_name, edge_location_display_name, tunnel_name, transport_type,
avg/peak/p95_throughput, ingress/egress bytes+packets, source/destination_ip,
tunnel_state(+_name), tunnel_monitoring_state(+_name).

UNITS (units report 2026-07-23 -- confirmed against SCM docs / pan.dev schema):
* ``avg_throughput`` / ``peak_throughput`` / ``p95_throughput`` are **Kbps**
  (kilobits per second). A bare 8042.58 is ~8 Mbps, NOT 8 Gbps -- misreading
  as Mbps is an 8000x error that contradicts physical uplink limits.
* ``peak`` = the highest per-minute polling sample within each time bucket,
  not an absolute instantaneous maximum.
* Bucket granularity grows with the window: <=1h ~1-3 min; 24h = 5 min;
  7-30d rolls up to 30 min - 3 h.
* ``ingress/egress_bytes`` are Bytes; avg can be derived as
  (bytes * 8) / (bucket_seconds * 1000) Kbps, but peak cannot.
To make the unit impossible to miss, output keys are RENAMED to carry it
(``avg_throughput_kbps`` etc.) and every response includes a ``units`` block.
The raw bytes/packets fields stay filtered out (response slimming); add them
here if a future use case needs byte-level detail -- with units labeled.

Up/down is read from tunnel_state_name (fallbacks: tunnel_state, tunnel_status);
tunnel_monitoring_state_name rides along as a secondary health signal.
"""
import config
from client import (SaseClient, SaseApiError, default_time_rules, records_of,
                    slim_records, verify_note)

_WHITELIST = ["site_name", "tunnel_name", "node_type", "transport_type",
              "tunnel_state_name", "tunnel_monitoring_state_name",
              "avg_throughput", "peak_throughput", "p95_throughput",  # Kbps (renamed below)
              "source_ip", "destination_ip", "edge_location_display_name"]
_STATE_FIELDS = ["tunnel_state_name", "tunnel_state", "tunnel_status", "state"]

# Unit-bearing output names (units report fix #3): the unit lives in the key
# itself so no reader -- human or LLM -- can drop it.
_KBPS_RENAME = {"avg_throughput": "avg_throughput_kbps",
                "peak_throughput": "peak_throughput_kbps",
                "p95_throughput": "p95_throughput_kbps"}

UNITS = {
    "throughput": "kbps",
    "throughput_note": ("avg/peak/p95_throughput_kbps are kilobits per second; "
                        "divide by 1000 for Mbps."),
    "peak_semantics": ("peak = highest per-minute polling sample within each "
                       "time bucket, not an absolute instantaneous maximum."),
    "bucket_granularity": ("<=1h: ~1-3 min buckets; 24h: 5 min; "
                           "7-30d: rolled up to 30 min - 3 h."),
}


# Exact state vocabulary. Substring matching used to be used here and it
# silently mis-classified any state name CONTAINING "up" or "down" --
# "Disrupted", "Setup", "backup" and "SUPERVISING" all counted as UP, so a
# disrupted tunnel made the status headline say "all tunnels up" (the very
# claim 0.8.4 set out to make honest). Anything not listed here falls through
# to other_states, where the headline reports it as "not up" -- an unknown
# state is never assumed healthy.
_UP_STATES = frozenset(("up", "active", "established", "connected", "enabled"))
_DOWN_STATES = frozenset(("down", "inactive", "disconnected", "failed",
                          "disabled"))


def _state_of(record):
    """Normalized tunnel state: 'up' / 'down' / raw-lowercased / 'unknown'.

    Matching is EXACT against the vocabularies above (numeric 1/0 included --
    the live tunnel_state field is an int). Unrecognized values are returned
    lowercased so the caller surfaces them in other_states rather than
    guessing; see the comment on _UP_STATES for why substring matching is
    unsafe here.
    """
    for f in _STATE_FIELDS:
        v = record.get(f)
        if v in (None, ""):
            continue
        s = str(v).strip().lower()
        if s in _UP_STATES or s == "1":
            return "up"
        if s in _DOWN_STATES or s == "0":
            return "down"
        return s
    return "unknown"


def get_remote_networks(state=None, hours=1, limit=config.DEFAULT_LIMIT,
                        tsg_id=None, region=None):
    """Tunnel rows for Remote Networks / Service Connections, filterable by state.

    hours: look-back window for the (required) time filter; 1h ~= current state.
    state: optional 'up' / 'down' filter on the normalized tunnel state.
    Throughput fields are returned as *_kbps (kilobits/sec) -- see UNITS.
    """
    limit = config.clamp_limit(limit)
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 1

    client = SaseClient()
    try:
        raw = client.insights_query("remote_networks",
                                    filter_rules=default_time_rules(hours),
                                    tsg_id=tsg_id, region=region)
    except SaseApiError as e:
        return e.as_dict(tool="get_remote_networks")

    records = records_of(raw)
    counts = {}
    down_names = []
    monitoring_down = []
    for r in records:
        s = _state_of(r)
        counts[s] = counts.get(s, 0) + 1
        if s == "down":
            down_names.append(r.get("tunnel_name") or r.get("site_name"))
        # A tunnel that is Up while its monitoring is Down still carries
        # traffic, but its health is unobserved -- a live tenant had two in
        # that state and nothing surfaced it. Track it as its own signal.
        mon = r.get("tunnel_monitoring_state_name") or r.get(
            "tunnel_monitoring_state")
        if s == "up" and str(mon).strip().lower() in ("down", "disabled", "0"):
            monitoring_down.append(r.get("tunnel_name") or r.get("site_name"))

    wanted = records
    norm_state = (state or "").strip().lower()
    if norm_state:
        wanted = [r for r in records if _state_of(r) == norm_state]

    rows, total_wanted = slim_records(wanted, _WHITELIST, limit)
    for row, rec in zip(rows, wanted):
        # Attach the normalized state so callers don't re-derive it.
        row["state"] = _state_of(rec)
        # Unit-bearing key names (Kbps) -- units report fix #3.
        for old, new in _KBPS_RENAME.items():
            if old in row:
                row[new] = row.pop(old)

    out = {
        "ok": True,
        "window_hours": hours,
        "units": UNITS,
        "total": len(records),
        "tunnels_up": counts.get("up", 0),
        "tunnels_down": counts.get("down", 0),
        "down_names": down_names[:config.MAX_LIMIT],
        "returned": len(rows),
        "tunnels": rows,
    }
    if monitoring_down:
        out["monitoring_down"] = len(monitoring_down)
        out["monitoring_down_names"] = monitoring_down[:config.MAX_LIMIT]
    other = {k: v for k, v in counts.items() if k not in ("up", "down")}
    if other:
        out["other_states"] = other
        # e.g. a tunnel stuck in 'init' has never come up -- neither up nor
        # down, and previously invisible to the status headline.
        out["not_up_names"] = [
            (r.get("tunnel_name") or r.get("site_name")) for r in records
            if _state_of(r) not in ("up", "down")][:config.MAX_LIMIT]
    if norm_state:
        out["state_filter"] = norm_state
    if total_wanted > len(rows):
        out["note"] = ("Showing %d of %d; raise 'limit' (max %d)."
                       % (len(rows), total_wanted, config.MAX_LIMIT))
    note = verify_note(raw)
    if note:
        out["_verify"] = note
    return out
