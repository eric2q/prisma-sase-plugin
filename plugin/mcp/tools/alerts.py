"""query_alerts -- Prisma Access alerts via Insights 3.0 (read-only).

Round-2 live finding (the live tenant (sg)): `alerts/alerts_list` is an AGGREGATE
view -- fields are sub_tenant_id / total_count / mu_count / rn_count / sc_count
(one row PER SUB-TENANT; total_count = alerts RAISED within the time window,
not currently-active -- PANW guidance 2026-07-24). Counts only; no per-alert
severity. The per-alert view, per the same guidance, is the single-segment
resource `prisma_sase_external_alerts_current` (fields incl. alert_id,
severity, severity_id, state, updated_time) -- now the shipped alerts_detail
default, pending live verification.

Strategy:
1. Try the `alerts_detail` mapping first (prisma_sase_external_alerts_current;
   candidates probed by discover_insights(kind="alerts_detail")). If it works
   and returns per-alert rows, use the full severity path.
2. Otherwise fall back to `alerts`:
   - aggregate shape  -> honest summary_counts + severity_unavailable flag
   - per-alert shape  -> full severity path (tenants where alerts_list IS a
     detail view keep working unchanged).
"""
import config
from client import SaseClient, SaseApiError, records_of, slim_records, verify_note

_WHITELIST = ["alert_id", "severity", "severity_id", "state", "category",
              "message", "raised_time", "updated_time", "location"]
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
        # We queried without the severity/state rules; re-apply them locally
        # BEFORE slimming/truncation so matches beyond the first `limit` rows
        # are not lost and total_matched reflects the full record set.
        if severity or state:
            records = _filter_records(records, severity, state)
        out = _detail_output(raw, records, hours, limit, source="alerts")
        if (severity or state) and out.get("ok"):
            out["filter_note"] = ("severity/state filtered locally (the "
                                  "fallback view was queried with the time "
                                  "filter only).")
        return out

    # --- aggregate summary (honest counts, no severity) ----------------------
    # Issue #3 (low): the view returns ONE ROW PER SUB-TENANT. Sum across all
    # rows and say so -- a single-row read both under-counted multi-sub-tenant
    # tenants and made the number mismatch the per-tenant figure in the UI.
    agg_rows = [r for r in records if isinstance(r, dict)]
    summary = {
        "total": sum(_int_of(r, "total_count") for r in agg_rows),
        "mobile_users": sum(_int_of(r, "mu_count") for r in agg_rows),
        "remote_networks": sum(_int_of(r, "rn_count") for r in agg_rows),
        "service_connections": sum(_int_of(r, "sc_count") for r in agg_rows),
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
        "note": ("Fell back to alerts/alerts_list, an AGGREGATE view (counts "
                 "by MU/RN/SC only, no per-alert severity). The per-alert "
                 "view -- prisma_sase_external_alerts_current, per PANW "
                 "guidance -- was tried first but did not return usable rows "
                 "on this tenant (see detail_view_error if present). Run "
                 "discover_insights(kind=\"alerts_detail\") to probe it "
                 "directly; if it works there, report the outcome so the "
                 "mapping can be marked verified. If it does not exist on "
                 "this tenant, severity is an API limitation, not a missing "
                 "setting."),
    }
    if len(agg_rows) > 1:
        out["sub_tenant_count"] = len(agg_rows)
        out["by_sub_tenant"] = [
            {"sub_tenant_id": r.get("sub_tenant_id"),
             "total": _int_of(r, "total_count")}
            for r in agg_rows[:config.MAX_LIMIT]]
        out["aggregation_note"] = (
            "Counts are summed across %d sub-tenants; the SASE UI shows "
            "per-sub-tenant numbers, so a single sub-tenant's figure will be "
            "lower. Per-sub-tenant totals: see by_sub_tenant."
            % len(agg_rows))
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


def _filter_records(records, severity, state):
    """Re-apply severity/state filters client-side on the raw record list.

    Runs on the full, pre-truncation records so counts and pagination stay
    correct. Severity is read through the same field candidates used for
    output; state through the whitelisted 'state' field.
    """
    want_sev = {s.lower() for s in
                ([severity] if isinstance(severity, str) else (severity or []))}
    want_state = {s.lower() for s in
                  ([state] if isinstance(state, str) else (state or []))}
    out = []
    for r in records:
        if not isinstance(r, dict):
            continue
        if want_sev:
            sev = _first(r, _SEV_FIELDS)
            if str(sev or "").lower() not in want_sev:
                continue
        if want_state:
            if str(r.get("state", "")).lower() not in want_state:
                continue
        out.append(r)
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
