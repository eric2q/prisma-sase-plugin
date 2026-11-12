"""query_incidents / get_incident -- SCM Unified Incident Framework (read-only).

Why this exists: Insights 3.0 `alerts/alerts_list` is an AGGREGATE view on the
live tenant (counts only, no per-alert severity), and every `alerts_detail`
candidate has returned DATA10003 there. PANW's own answer is that incident
data lives in the Strata Cloud Manager Unified Incident Framework REST API
(pan.dev, spec 3.0.0, 2026-03-30), which is documented as read-only:

    POST /incidents/v1/search                 search with filter + pagination
    GET  /incidents/v1/details/{incident-id}  one incident in full

WHAT IS AND IS NOT VERIFIED (2026-11-12). The two paths above come from
pan.dev. The pages do NOT state the host, the request-body schema or the
response fields. So this module ships as an explicitly UNVERIFIED integration,
in the same spirit as the Insights mappings before their first live run:

* host       -- tries config.SCM_BASES in order (api.strata, then api.sase)
                and remembers the one that answered, per tenant.
* body       -- leads with the filter+pagination shape used by the community
                pan-scm-sdk models; falls back to pagination-only, then {}.
                When a fallback is used, severity/status are filtered locally.
* fields     -- read through candidate lists; if none match, the response
                carries a field_note listing the record's real field names.

Every response says so in `_verify` until PRISMA_INCIDENTS_VERIFIED=1 is set.
Run discover_scm against a live tenant first; it reports which host and body
shape work and the real field names, without printing any incident values.
"""
import config
from client import SaseClient, SaseApiError, mock_notice, records_of

_SEV_ORDER = ["critical", "high", "medium", "low", "warning", "informational"]

# Candidate field names, most-likely first (schema unverified -- see above).
_FIELDS = {
    "incident_id":  ["incident_id", "id", "incidentId", "uuid"],
    "title":        ["title", "name", "summary", "incident_name"],
    "severity":     ["severity", "incident_severity", "priority"],
    "status":       ["status", "state", "incident_status"],
    "product":      ["product", "product_name", "source"],
    "category":     ["category", "sub_category", "type"],
    "code":         ["code", "incident_code", "code_id"],
    "raised_time":  ["raised_time", "raised_at", "created_time", "created_at",
                     "creation_time", "start_time"],
    "updated_time": ["updated_time", "updated_at", "last_updated_time",
                     "modified_time"],
}

_working_base = {}      # tsg -> base URL that answered (process lifetime only)

_UNVERIFIED = (
    "SCM Incidents integration is UNVERIFIED on a live tenant: the paths are "
    "documented on pan.dev, but the host, request body and field names are "
    "not. Treat counts and fields as provisional. Run discover_scm, report "
    "what it finds, and set PRISMA_INCIDENTS_VERIFIED=1 once confirmed.")


def _first(record, candidates):
    for f in candidates:
        v = record.get(f)
        if v not in (None, ""):
            return v
    return None


def _as_list(value):
    if value in (None, ""):
        return []
    return [value] if isinstance(value, str) else list(value)


def _title_case(values):
    """'critical' -> 'Critical'. The community SDK examples use capitalised
    values (Critical / Raised); mixed-case input is passed through as given."""
    return [v[:1].upper() + v[1:] if isinstance(v, str) and v.islower() else v
            for v in values]


def incident_records(raw):
    """Record list from a search response, whatever the wrapper key."""
    records = records_of(raw)
    if not records and isinstance(raw, dict):
        val = raw.get("incidents")
        if isinstance(val, list):
            records = val
    if not records and isinstance(raw, list):
        records = raw
    return [r for r in records if isinstance(r, dict)]


def _reported_total(raw):
    """Server-side total when the response states one; None otherwise."""
    if not isinstance(raw, dict):
        return None
    for holder in (raw, raw.get("pagination"), raw.get("meta"),
                   raw.get("metadata")):
        if not isinstance(holder, dict):
            continue
        for key in ("total", "total_count", "totalCount", "total_records"):
            val = holder.get(key)
            if isinstance(val, int) and not isinstance(val, bool):
                return val
    return None


def _bases_for(tsg):
    bases = list(config.SCM_BASES)
    known = _working_base.get(tsg)
    if known in bases:
        bases.remove(known)
        bases.insert(0, known)
    return bases


def _variants(severity, status, page_size, page_number):
    """(name, body, server_filtered) -- most specific first."""
    rules = []
    if severity:
        rules.append({"property": config.INCIDENT_PROP_SEVERITY,
                      "operator": "in", "values": _title_case(severity)})
    if status:
        rules.append({"property": config.INCIDENT_PROP_STATUS,
                      "operator": "in", "values": _title_case(status)})
    pagination = {"page_size": page_size, "page_number": page_number}
    out = [("filter_and_pagination",
            {"filter": {"rules": rules}, "pagination": pagination}, True)]
    if rules:
        out.append(("pagination_only",
                    {"filter": {"rules": []}, "pagination": pagination}, False))
    out.append(("empty_body", {}, False))
    return out


def _search(client, variants, tsg_id, region):
    """Try host x body-shape until one answers.

    404/403 -> the path is not served (or not permitted) on that host: move to
    the next host. 400/422 -> the body shape was rejected: try the next shape
    on the same host. Anything else is not something a retry can fix.
    """
    tsg = config.resolve_tsg(tsg_id)
    attempts = []
    last = None
    for base in _bases_for(tsg):
        for name, body, server_filtered in variants:
            try:
                raw = client.incidents_search(body, tsg_id=tsg_id,
                                              region=region, base=base)
            except SaseApiError as e:
                last = e
                attempts.append({"base": base, "payload": name,
                                 "status": e.status, "error": str(e)})
                if e.status in (400, 422):
                    continue            # next body shape, same host
                if e.status in (403, 404):
                    break               # next host
                raise
            _working_base[tsg] = base
            return raw, base, name, server_filtered, attempts
    if last is None:
        last = SaseApiError("No SCM base URL is configured.")
    last.attempts = attempts
    raise last


def _row(record):
    row = {}
    for key, candidates in _FIELDS.items():
        v = _first(record, candidates)
        if v is not None:
            row[key] = v
    return row


def _matches(record, severity, status):
    if severity:
        sev = str(_first(record, _FIELDS["severity"]) or "").lower()
        if sev not in {s.lower() for s in severity}:
            return False
    if status:
        st = str(_first(record, _FIELDS["status"]) or "").lower()
        if st not in {s.lower() for s in status}:
            return False
    return True


def _count_by_severity(records):
    counts = {}
    for r in records:
        sev = _first(r, _FIELDS["severity"])
        sev = str(sev).lower() if sev not in (None, "") else "unknown"
        counts[sev] = counts.get(sev, 0) + 1
    ordered = {k: counts[k] for k in _SEV_ORDER if k in counts}
    ordered.update({k: v for k, v in counts.items() if k not in ordered})
    return ordered


def _stamp(out):
    if not config.INCIDENTS_VERIFIED:
        out["_verify"] = _UNVERIFIED
    mock = mock_notice()
    if mock:
        out["mock_mode"] = True
        out["mock_notice"] = mock
    return out


def _error(e, tool):
    out = e.as_dict(tool=tool)
    out["hint"] = (
        "The SCM Incidents API is an unverified integration. Run discover_scm "
        "to see which host/body shape this tenant accepts. 403 usually means "
        "the service account's role does not include Incidents; 404 on every "
        "host means the API is not served for this tenant.")
    attempts = getattr(e, "attempts", None)
    if attempts:
        out["attempts"] = attempts
    return _stamp(out)


def query_incidents(severity=None, status=None, limit=config.DEFAULT_LIMIT,
                    page=1, tsg_id=None, region=None):
    """Search SCM incidents; returns per-incident rows WITH severity."""
    limit = config.clamp_limit(limit)
    try:
        page = max(int(page), 1)
    except (TypeError, ValueError):
        page = 1
    severity = _as_list(severity)
    status = _as_list(status)

    client = SaseClient()
    try:
        raw, base, payload, server_filtered, attempts = _search(
            client, _variants(severity, status, limit, page), tsg_id, region)
    except SaseApiError as e:
        return _error(e, "query_incidents")

    records = incident_records(raw)
    filtered_locally = bool(severity or status) and not server_filtered
    if filtered_locally:
        records = [r for r in records if _matches(r, severity, status)]

    reported = None if filtered_locally else _reported_total(raw)
    rows = [_row(r) for r in records[:limit]]
    out = {
        "ok": True,
        "total_matched": reported if reported is not None else len(records),
        "returned": len(rows),
        "page": page,
        "counts_by_severity": _count_by_severity(records),
        "incidents": rows,
        "source": "scm_incidents",
        "_meta": {"base": base, "payload_used": payload},
    }
    if reported is not None and reported > len(records):
        out["counts_note"] = (
            "counts_by_severity covers only the %d incident(s) on this page, "
            "not all %d matched -- do not present it as the tenant-wide "
            "breakdown." % (len(records), reported))
    if filtered_locally:
        out["filter_note"] = (
            "The server rejected the filter body, so severity/status were "
            "applied locally to ONE page of unfiltered results. Matches on "
            "other pages are not included; total_matched is this page only.")
    if records and not any("severity" in r for r in rows):
        out["field_note"] = (
            "None of the severity field candidates %s matched. First record's "
            "fields: %s. Report these so the mapping can be fixed."
            % (_FIELDS["severity"], sorted(records[0].keys())[:30]))
    if attempts:
        out["_meta"]["fallbacks_tried"] = len(attempts)
    return _stamp(out)


def _trim(obj, depth=0):
    """Bound a detail payload: long lists and strings are cut, with a marker."""
    if depth > 6:
        return "<nested too deep; omitted>"
    if isinstance(obj, dict):
        return {k: _trim(v, depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        cut = [_trim(v, depth + 1) for v in obj[:config.DEFAULT_LIMIT]]
        if len(obj) > config.DEFAULT_LIMIT:
            cut.append("<%d more item(s) omitted>"
                       % (len(obj) - config.DEFAULT_LIMIT))
        return cut
    if isinstance(obj, str) and len(obj) > 2000:
        return obj[:2000] + "<truncated>"
    return obj


def get_incident(incident_id, tsg_id=None, region=None):
    """Full detail for one incident (alerts, impacted objects, remediation)."""
    if incident_id in (None, ""):
        return _stamp({"ok": False, "tool": "get_incident",
                       "error": "incident_id is required (take it from "
                                "query_incidents)."})
    client = SaseClient()
    tsg = config.resolve_tsg(tsg_id)
    attempts = []
    last = None
    for base in _bases_for(tsg):
        try:
            raw = client.incident_details(incident_id, tsg_id=tsg_id,
                                          region=region, base=base)
        except SaseApiError as e:
            last = e
            attempts.append({"base": base, "status": e.status,
                             "error": str(e)})
            if e.status in (403, 404):
                continue
            break
        _working_base[tsg] = base
        detail = raw
        if isinstance(raw, dict) and isinstance(raw.get("data"), dict):
            detail = raw["data"]
        return _stamp({"ok": True, "incident_id": incident_id,
                       "incident": _trim(detail),
                       "source": "scm_incidents", "_meta": {"base": base}})
    last.attempts = attempts
    out = _error(last, "get_incident")
    if last.status == 404:
        out["hint"] = ("404 on every host: either this incident_id does not "
                       "exist (ids come from query_incidents), or the "
                       "Incidents API is not served for this tenant -- "
                       "discover_scm tells the two apart.")
    return out
