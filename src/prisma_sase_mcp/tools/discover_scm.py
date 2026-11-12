"""discover_scm -- find out how THIS tenant serves the SCM Incidents API.

The Unified Incident Framework paths are documented on pan.dev, but the host,
the request-body schema and the response field names are not (checked
2026-11-12). Rather than guess and ship, this probes them -- the same approach
discover_insights takes for resource/view names.

Every probe is the documented read-only search POST with page_size 1. The
output carries field NAMES and counts only, never incident values, so it is
safe to paste into an issue.
"""
import config
from client import SaseClient, SaseApiError, mock_notice
from tools.incidents import incident_records

_PAGE = {"page_size": 1, "page_number": 1}
_VARIANTS = (
    ("filter_and_pagination", {"filter": {"rules": []}, "pagination": _PAGE}),
    ("pagination_only", {"pagination": _PAGE}),
    ("empty_body", {}),
)
_MAX_FIELDS = 40


def discover_scm(tsg_id=None, region=None):
    """Probe each candidate SCM host with each body shape; report what works."""
    client = SaseClient()
    probes = []
    working = []

    for base in config.SCM_BASES:
        entry = {"api": "incidents_search", "base": base,
                 "path": config.SCM_INCIDENTS_SEARCH_PATH}
        failures = []
        for name, body in _VARIANTS:
            try:
                raw = client.incidents_search(body, tsg_id=tsg_id,
                                              region=region, base=base)
            except SaseApiError as e:
                failure = {"payload_variant": name, "status": e.status,
                           "error": str(e)}
                if e.api_code:
                    failure["api_error_code"] = e.api_code
                failures.append(failure)
                if e.status not in (400, 422):
                    break       # not a body-shape problem; other shapes won't help
                continue
            records = incident_records(raw)
            entry.update({
                "status": "ok",
                "payload_variant": name,
                "record_count": len(records),
                "response_keys": (sorted(raw.keys())[:_MAX_FIELDS]
                                  if isinstance(raw, dict) else []),
                "sample_fields": (sorted(records[0].keys())[:_MAX_FIELDS]
                                  if records else []),
            })
            working.append(entry)
            break
        if entry.get("status") != "ok":
            last = failures[-1] if failures else {}
            entry["status"] = "http_%s" % (last.get("status") or "error")
        if failures:
            entry["failures"] = failures
        probes.append(entry)

    notes = []
    suggested = {}
    if working:
        best = working[0]
        suggested = {"PRISMA_INCIDENTS_BASE": best["base"]}
        notes.append(
            "Incidents search answered on %s with the '%s' body. Please report "
            "payload_variant, response_keys and sample_fields (names only -- "
            "no incident data is included) so the field mapping can be "
            "confirmed and shipped as a verified default."
            % (best["base"], best["payload_variant"]))
        if best["payload_variant"] != "filter_and_pagination":
            notes.append(
                "The filter+pagination body was rejected, so query_incidents "
                "cannot filter server-side yet: severity/status are applied "
                "locally to one page. The accepted filter schema still needs "
                "to be captured (SCM UI -> Incidents -> browser dev tools -> "
                "Network -> the /incidents/v1/search request body).")
        if not best["record_count"]:
            notes.append(
                "The call succeeded but returned no incidents, so field names "
                "could not be sampled. Re-run when the tenant has at least one "
                "incident, or capture the response shape from the SCM UI.")
    else:
        statuses = sorted({str(p["status"]) for p in probes})
        notes.append(
            "No candidate host served /incidents/v1/search (%s). 403 = the "
            "service account's role lacks Incidents access; 404 on every host "
            "= the API is not served for this tenant/licence; 401 = fix auth "
            "first (run --selfcheck). query_alerts (Insights) is unaffected."
            % ", ".join(statuses))

    mock = mock_notice()
    if mock:
        notes.insert(0, mock + " The host and field names below are the "
                     "sample set; do NOT adopt them into PRISMA_INCIDENTS_BASE.")

    return {"ok": True,
            **({"mock_mode": True, "mock_notice": mock} if mock else {}),
            "incidents_api_reachable": bool(working),
            "probes": probes,
            "suggested_env": suggested,
            "notes": notes}
