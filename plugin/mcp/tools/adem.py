"""get_user_experience -- ADEM Telemetry v2 experience score (read-only).

Endpoint shape confirmed from pan.dev:
    GET /adem/telemetry/v2/measure/agent/score
        ?start=<epoch>&end=<epoch>&endpoint-type=muAgent&response-type=summary

Per PANW guidance (2026-07-24):
* Per-user scoping uses the ``filter`` query parameter with
  ``userName==<user_email>`` (urlencoded by the client automatically).
* Valid ``endpoint-type`` values: ``muAgent`` (Mobile Users) and ``rnAgent``
  (Remote Networks).
The per-app parameter remains a best-guess pending confirmation.
"""
import time

import config
from client import SaseClient, SaseApiError

# ADEM score rating bands (see skills/prisma-sase-ops/references/thresholds.md).
# <70 is the documented "degraded" action line (design doc sec.2).
_BANDS = [(90, "excellent"), (80, "good"), (70, "fair"), (50, "poor")]


def get_user_experience(user=None, app=None, hours=24, start=None, end=None,
                        endpoint_type=None, tsg_id=None, region=None):
    endpoint_type = endpoint_type or config.ADEM_DEFAULT_ENDPOINT_TYPE
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 24
    if end is None:
        end = int(time.time())
    if start is None:
        start = int(end) - hours * 3600

    params = {
        "start": int(start),
        "end": int(end),
        "endpoint-type": endpoint_type,
        "response-type": config.ADEM_DEFAULT_RESPONSE_TYPE,
    }
    if user:
        # PANW guidance (2026-07-24): per-user scoping is filter=userName==<email>
        # (urlencode turns == into %3D%3D automatically).
        params["filter"] = "userName==" + str(user)
    if app:
        params["app"] = app   # NOTE: per-app param still a best-guess

    client = SaseClient()
    try:
        raw = client.adem_get("/measure/agent/score", params=params,
                              tsg_id=tsg_id, region=region)
    except SaseApiError as e:
        return e.as_dict(tool="get_user_experience")

    data = raw.get("data") if isinstance(raw, dict) and "data" in raw else raw
    score = _extract_score(data)
    out = {
        "ok": True,
        "scope": {"user": user, "app": app, "endpoint_type": endpoint_type},
        "window": {"start": int(start), "end": int(end), "hours": hours},
        "overall_score": score["overall"],
        "rating": _rate(score["overall"]),
        "components": score["components"],
    }
    if score["worst_component"]:
        out["worst_component"] = score["worst_component"]
    if score["row_count"] is not None:
        out["row_count"] = score["row_count"]

    if score["overall"] is None:
        # Field report 2026-07-23: live tenant returned score=null. Surface the
        # response's actual shape (keys only, no values/PII) so the mapping can
        # be corrected instead of reporting a bare null.
        if isinstance(data, dict):
            out["no_data_debug"] = {"response_keys": list(data.keys())[:20]}
            avg = data.get("average")
            if isinstance(avg, dict):
                out["no_data_debug"]["average_keys"] = list(avg.keys())[:20]
        # 0.8.0 field report P2: rowCount == 0 means the API had NO agent
        # samples in the window -- an empty window, not a broken mapping.
        # Saying which one it is prevents a wild goose chase.
        if score["row_count"] == 0:
            out["no_data_reason"] = "empty_window"
            out["note"] = (
                "ADEM returned rowCount=0: there is no agent telemetry in this "
                "window, so there is no score to report (this is NOT a mapping "
                "problem). Widen 'hours', or check that ADEM-enabled agents "
                "were connected -- if get_connected_users also shows 0, that "
                "explains it.")
            return out
        if score["row_count"]:
            out["no_data_reason"] = "shape_mismatch"
        # Per-segment averages without an aggregate: report what IS there
        # rather than calling the whole thing "no data" (0.8.1 CLI test saw
        # wlan / lan / vpnUnderlay populated while overall stayed null).
        if isinstance(score["components"], dict) and score["components"]:
            out["no_data_reason"] = "no_aggregate_score"
            out["note"] = (
                "This response carries NO aggregate experience score, but it "
                "does carry per-segment averages (%s) -- report those and the "
                "weakest one (%s) instead of saying there is no data, and say "
                "plainly that an overall score is unavailable from this "
                "endpoint shape. Do not average them yourself into a fake "
                "overall score."
                % (", ".join(sorted(score["components"])),
                   score["worst_component"]))
            return out
        elif isinstance(data, list):
            first = data[0] if data and isinstance(data[0], dict) else None
            out["no_data_debug"] = {
                "response_shape": "list[%d]" % len(data),
                "first_item_keys": list(first.keys())[:20] if first else []}
        if user:
            out["note"] = ("No score returned for this user. The query used "
                           "filter=userName==<email> (PANW guidance) -- check "
                           "the exact user email/spelling, whether this user "
                           "has an ADEM-enabled agent, and see no_data_debug "
                           "for the response shape.")
        else:
            out["note"] = ("No score in the ADEM response -- either no agent "
                           "data in this window, or the response shape differs "
                           "for this tenant. See no_data_debug for the actual "
                           "keys and report them so the mapping can be fixed.")
    return out


def _extract_score(data):
    """Pull the overall score + components out of the ADEM payload.

    Live shape (0.8.0 field report P2, macOS/sg tenant): the response carries
    ``startTime / endTime / endpointType / tenantServiceGroup / rowCount /
    average`` -- no top-level ``score``. The score lives under ``average``,
    which is either a bare number or a dict of per-metric averages (in which
    case a 'score'-ish key is the overall and the rest are components).
    """
    if not isinstance(data, dict):
        return {"overall": None, "components": None, "worst_component": None,
                "row_count": None}
    overall = data.get("overall_score", data.get("score"))
    comps = data.get("components") or data.get("score_components")

    average = data.get("average")
    if overall is None and isinstance(average, (int, float)):
        overall = average
    elif isinstance(average, dict) and average:
        # Prefer an explicit score-ish key; otherwise the sole numeric value.
        for key in ("score", "experience_score", "overallScore", "value"):
            if isinstance(average.get(key), (int, float)):
                if overall is None:
                    overall = average[key]
                break
        numeric = {k: v for k, v in average.items()
                   if isinstance(v, (int, float))}
        if overall is None and len(numeric) == 1:
            overall = list(numeric.values())[0]
        if not comps and numeric:
            # Live shape (0.8.1 CLI test): average holds PER-SEGMENT scores
            # (wlan / lan / vpnUnderlay / ...). Those are genuine, useful
            # measurements -- expose them as components even though the
            # response carries no aggregate score.
            comps = numeric

    worst = data.get("worst_component")
    if not worst and isinstance(comps, dict) and comps:
        numeric_comps = {k: v for k, v in comps.items()
                         if isinstance(v, (int, float))}
        if numeric_comps:
            # lowest-scoring component is the likely culprit
            worst = min(numeric_comps, key=lambda k: numeric_comps[k])

    row_count = data.get("rowCount", data.get("row_count"))
    return {"overall": overall, "components": comps, "worst_component": worst,
            "row_count": row_count if isinstance(row_count, int) else None}


def _rate(score):
    if score is None:
        return None
    try:
        val = float(score)
    except (TypeError, ValueError):
        return None
    for floor, label in _BANDS:
        if val >= floor:
            return label
    return "critical"
