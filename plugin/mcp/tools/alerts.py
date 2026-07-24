"""query_alerts -- Prisma Access alerts via Insights 3.0 (read-only).

Round-2 live finding (the live tenant (sg)): `alerts/alerts_list` is an AGGREGATE
view -- fields are sub_tenant_id / total_count / mu_count / rn_count / sc_count.
Counts only; structurally NO per-alert severity/message/time. The per-alert
"detail" view for this tenant is not yet identified.

Strategy:
1. Try the `alerts_detail` mapping first (candidates probed by
   discover_insights(kind="alerts_detail")). If it works and returns per-alert
   rows, use the full severity path.
2. Otherwise fall back to `alerts`:
   - aggregate shape  -> honest summary_counts + severity_unavailable flag
   - per-alert shape  -> full severity path (tenants where alerts_list IS a
     detail view keep working unchanged).
"""
import config
from client import SaseClient, SaseApiError, records_of, slim_records, verify_note

_WHITELIST = ["alert_id", "severity", "state", "category", "message",
              "raised_time", "location"]
_SEV_ORDER = ["critical", "high", "medium", "low", "informational"]

# Candidate field names, most-likely first (tenant/version dependent).
_SEV_FIELDS = ["severity", "alert_severity", "sev", "priority", "severity_level"]
_MSG_FIELDS = ["message", "alert_message", "description", "alert_name", "name"]
_ID_FIELDS = ["alert_id", "id", "alert_uuid"]
_TIME_FIELDS = ["raised_time", "event_time", "timestamp", "created_time",
                "updated_time"]

# Aggregate-view signature (round-2 live finding).
_AGG_FIELDS = ("total_count", "mu_count", "rn_count", "sc_count")


def _first(record, candidates):
    for f in candidates:
        v = record.get(f)
        if v not in (None, ""):
            return v
    return None


def _is_aggregate(records):
    if not records or not isinstance(records[0], dict):
        return False
    first = records[0]
    has_counts = any(f in first for f in _AGG_FIELDS)
    has_severity = _first(first, _SEV_FIELDS) is not None
    return has_counts and not has_severity


def _int_of(record, field):
    try:
        return int(record.get(field) or 0)
    except (TypeError, ValueError):
        return 0


def query_alerts(severity=None, state=None, hours=24, limit=config.DEFAULT_LIMIT,
                 tsg_id=None, region=None):
    limit = config.clamp_limit(limit)
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 24

    rules = [{"property": config.FILTER_PROP_TIME,
              "operator": "last_n_hours", "values": [hours]}]
    if severity:
        vals = [severity] if isinstance(severity, str) else list(severity)
        rules.append({"property": config.FILTER_PROP_SEVERITY,
                      "operator": "in", "values": vals})
    if state:
        vals = [state] if isinstance(state, str) else list(state)
        rules.append({"property": config.FILTER_PROP_STATE,
                      "operator": "in", "values": vals})

    client = SaseClient()

    # --- 1) detail view first (per-alert rows with severity) -----------------
    detail_error = None
    if "alerts_detail" in config.INSIGHTS_MAP:
        try:
            raw = client.insights_query("alerts_detail", filter_rules=rules,
                                        tsg_id=tsg_id, region=region)
            records = records_of(raw)
            if not _is_aggregate(records):
                return _detail_output(raw, records, hours, limit,
                                      source="alerts_detail")
        except SaseApiError as e:
            detail_error = str(e)

    # --- 2) fall back to the base alerts view --------------------------------
    # A severity filter rule can 400 on views without that property; retry
    # without it since the aggregate path cannot honour it anyway.
    base_rules = [r for r in rules
                  if r.get("property") == config.FILTER_PROP_TIME]
    try:
        raw = client.insights_query("alerts", filter_rules=base_rules
                                    if severity or state else rules,
                                    tsg_id=tsg_id, region=region)
    except SaseApiError as e:
        out = e.as_dict(tool="query_alerts")
        if detail_error:
            out["detail_view_error"] = detail_error
        return out

    records = records_of(raw)
    if not _is_aggregate(records):
        out = _detail_output(raw, records, hours, limit, source="alerts")
        if (severity or state) and out.get("ok"):
            # We queried without the severity/state rules; re-apply locally.
            out = _local_filter(out, severity, state, limit)
        return out

    # --- aggregate summary (honest counts, no severity) ----------------------
    agg = records[0]
    summary = {
        "total": _int_of(agg, "total_count"),
        "mobile_users": _int_of(agg, "mu_count"),
        "remote_networks": _int_of(agg, "rn_count"),
        "service_connections": _int_of(agg, "sc_count"),
    }
    out = {
        "ok": True,
        "window_hours": hours,
        "total_matched": summary["total"],
        "returned": 0,
        "severity_unavailable": True,
        "summary_counts": summary,
        "counts_by_severity": {},
        "alerts": [],
        "note": ("This tenant's alerts/alerts_list is an AGGREGATE view "
                 "(counts by MU/RN/SC only) -- per-alert severity/message is "
                 "structurally unavailable here. Run "
                 "discover_insights(kind=\"alerts_detail\") to find the "
                 "per-alert view, then set PRISMA_INSIGHTS_MAP with an "
                 "\"alerts_detail\" entry."),
    }
    if severity or state:
        out["filter_note"] = ("severity/state filters cannot be applied on the "
                              "aggregate view; showing totals instead.")
    if detail_error:
        out["detail_view_error"] = detail_error
    note = verify_note(raw)
    if note:
        out["_verify"] = note
    return out


def _detail_output(raw, records, hours, limit, source):
    rows, total = slim_records(records, _WHITELIST, limit)
    for row, rec in zip(rows, records):
        if not row.get("severity"):
            v = _first(rec, _SEV_FIELDS)
            if v is not None:
                row["severity"] = v
        if not row.get("message"):
            v = _first(rec, _MSG_FIELDS)
            if v is not None:
                row["message"] = v
        if not row.get("alert_id"):
            v = _first(rec, _ID_FIELDS)
            if v is not None:
                row["alert_id"] = v
        if not row.get("raised_time"):
            v = _first(rec, _TIME_FIELDS)
            if v is not None:
                row["raised_time"] = v

    counts = _count_by_severity(records)
    out = {
        "ok": True,
        "window_hours": hours,
        "total_matched": total,
        "returned": len(rows),
        "counts_by_severity": counts,
        "alerts": rows,
        "source_view": source,
    }
    if total and counts.get("unknown") == total:
        sample = records[0] if isinstance(records[0], dict) else {}
        out["field_note"] = (
            "None of the severity field candidates %s matched this tenant's "
            "records. First record's fields: %s. Set "
            "PRISMA_FILTER_SEVERITY_PROP (filter property) and report the "
            "record field so the mapping can be fixed."
            % (_SEV_FIELDS, list(sample.keys())[:25]))
    if total > len(rows):
        out["note"] = ("Showing %d of %d; raise 'limit' (max %d) or narrow the "
                       "filter." % (len(rows), total, config.MAX_LIMIT))
    note = verify_note(raw)
    if note:
        out["_verify"] = note
    return out


def _local_filter(out, severity, state, limit):
    """Re-apply severity/state filters client-side after a broad fallback query."""
    want_sev = {s.lower() for s in
                ([severity] if isinstance(severity, str) else (severity or []))}
    want_state = {s.lower() for s in
                  ([state] if isinstance(state, str) else (state or []))}
    rows = out.get("alerts") or []
    if want_sev:
        rows = [r for r in rows
                if str(r.get("severity", "")).lower() in want_sev]
    if want_state:
        rows = [r for r in rows
                if str(r.get("state", "")).lower() in want_state]
    out["alerts"] = rows[:limit]
    out["returned"] = len(out["alerts"])
    out["total_matched"] = len(rows)
    out["filter_note"] = ("severity/state filtered locally (the fallback view "
                          "was queried with the time filter only).")
    return out


def _count_by_severity(records):
    counts = {}
    for r in records:
        sev = _first(r, _SEV_FIELDS) or "unknown"
        sev = sev.lower() if isinstance(sev, str) else str(sev)
        counts[sev] = counts.get(sev, 0) + 1
    ordered = {}
    for key in _SEV_ORDER:
        if key in counts:
            ordered[key] = counts[key]
    for key, val in counts.items():
        if key not in ordered:
            ordered[key] = val
    return ordered
