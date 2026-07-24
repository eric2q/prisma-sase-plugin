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
    if score["overall"] is None:
        # Field report 2026-07-23: live tenant returned score=null. Surface the
        # response's actual shape (keys only, no values/PII) so the mapping can
        # be corrected instead of reporting a bare null.
        if isinstance(data, dict):
            out["no_data_debug"] = {"response_keys": list(data.keys())[:20]}
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
    if not isinstance(data, dict):
        return {"overall": None, "components": None, "worst_component": None}
    overall = data.get("overall_score", data.get("score"))
    comps = data.get("components") or data.get("score_components")
    worst = data.get("worst_component")
    if not worst and isinstance(comps, dict) and comps:
        # lowest-scoring component is the likely culprit
        worst = min(comps, key=lambda k: comps[k])
    return {"overall": overall, "components": comps, "worst_component": worst}


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
