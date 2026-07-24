"""get_sase_status -- one-shot Prisma SASE health overview (read-only).

Aggregates several read-only families into a single answer: alert counts by
severity, tunnel up/down for remote networks & service connections, connected
Mobile Users, and the overall ADEM experience score (design doc sec.4).

Each sub-query is best-effort: if one family fails (e.g. an unverified resource
name 400s), that section carries an error/hint and the others still return.

v0.3.0 (field report 2026-07-23, issue 3): the headline is now derived from the
ACTUAL section outcomes. Failed or data-less checks make the headline say
UNKNOWN/PARTIAL -- it never claims "Healthy" unless all four checks succeeded
with interpretable data.
"""
import config
from tools.alerts import query_alerts
from tools.networks import get_remote_networks
from tools.users import get_connected_users
from tools.adem import get_user_experience

_CHECKS = ("alerts", "connectivity", "connected_users", "experience")


def get_sase_status(tsg_id=None, region=None):
    sections = {}

    # --- alerts (last 24h, counted by severity) ---
    a = query_alerts(hours=24, limit=config.MAX_LIMIT, tsg_id=tsg_id, region=region)
    if a.get("ok"):
        sections["alerts"] = {"total": a.get("total_matched"),
                              "by_severity": a.get("counts_by_severity")}
        if a.get("severity_unavailable"):
            sections["alerts"]["severity_unavailable"] = True
            sections["alerts"]["summary"] = a.get("summary_counts")
        if a.get("sub_tenant_count"):
            # Issue #3: the total is summed across sub-tenants -- label it so
            # it doesn't read as a mismatch against the UI's per-tenant number.
            sections["alerts"]["sub_tenant_count"] = a["sub_tenant_count"]
            sections["alerts"]["aggregation_note"] = a.get("aggregation_note")
        if a.get("field_note"):
            sections["alerts"]["field_note"] = a["field_note"]
    else:
        sections["alerts"] = {"error": a.get("error"), "hint": a.get("hint")}

    # --- connectivity (remote networks / service connections) ---
    sections["connectivity"] = _tunnels(tsg_id, region)

    # --- connected users (last hour) ---
    u = get_connected_users(hours=1, tsg_id=tsg_id, region=region)
    if u.get("ok"):
        sections["connected_users"] = {"total_connected": u.get("total_connected"),
                                       "trend_1h_pct": u.get("trend_1h_pct")}
    else:
        sections["connected_users"] = {"error": u.get("error"), "hint": u.get("hint")}

    # --- experience (overall ADEM score) ---
    ex = get_user_experience(hours=24, tsg_id=tsg_id, region=region)
    if ex.get("ok"):
        sections["experience"] = {"overall_score": ex.get("overall_score"),
                                  "rating": ex.get("rating")}
        if ex.get("note"):
            sections["experience"]["note"] = ex["note"]
    else:
        sections["experience"] = {"error": ex.get("error"), "hint": ex.get("hint")}

    headline, checks = _headline(sections)
    return {"ok": True, "plugin_version": config.PLUGIN_VERSION,
            "headline": headline, "checks": checks, "sections": sections}


def _tunnels(tsg_id, region):
    # Round-2 BUG-1 fix: go through get_remote_networks, which sends the time
    # filter that tunnels/tunnel_list requires (an empty filter is a 400).
    r = get_remote_networks(hours=1, limit=config.MAX_LIMIT,
                            tsg_id=tsg_id, region=region)
    if not r.get("ok"):
        return {"error": r.get("error"), "hint": r.get("hint")}
    out = {"total": r.get("total"), "tunnels_up": r.get("tunnels_up"),
           "tunnels_down": r.get("tunnels_down"),
           "down_names": (r.get("down_names") or [])[:config.DEFAULT_LIMIT]}
    if r.get("other_states"):
        out["other_states"] = r["other_states"]
    return out


def _headline(sections):
    """Build an honest headline + a machine-readable checks summary.

    Never says "Healthy" unless every check succeeded AND produced
    interpretable data (field report issue 3).
    """
    failed = [name for name in _CHECKS if "error" in (sections.get(name) or {})]
    no_data = []
    problems = []

    # alerts (only if the check succeeded)
    a = sections.get("alerts") or {}
    if "error" not in a:
        if a.get("severity_unavailable"):
            # Aggregate view (round-2 BUG-2): counts only, no severity. A
            # non-zero count is still worth attention; never call it benign.
            # Issue #3: say the severity gap is the tenant's Insights API, not
            # a missing mapping, and label cross-sub-tenant totals.
            if a.get("total"):
                scope = (" across %d sub-tenants" % a["sub_tenant_count"]
                         if a.get("sub_tenant_count") else "")
                problems.append("%d alert(s) raised%s (severity breakdown "
                                "not exposed by this tenant's Insights API)"
                                % (a["total"], scope))
        else:
            by_sev = a.get("by_severity") or {}
            if by_sev.get("critical"):
                problems.append("%d critical alert(s)" % by_sev["critical"])
            if by_sev.get("high"):
                problems.append("%d high alert(s)" % by_sev["high"])
            if by_sev.get("unknown"):
                # Severity field not recognized -- cannot classify, so do not
                # treat these as benign.
                problems.append("%d alert(s) with unrecognized severity "
                                "(field mapping unconfirmed)" % by_sev["unknown"])

    # connectivity
    c = sections.get("connectivity") or {}
    if "error" not in c and c.get("tunnels_down"):
        problems.append("%d tunnel(s) down" % c["tunnels_down"])

    # experience
    e = sections.get("experience") or {}
    if "error" not in e:
        score = e.get("overall_score")
        if score is None:
            no_data.append("experience")
        elif isinstance(score, (int, float)) and score < 70:
            problems.append("experience score %s (<70)" % score)

    checks = {"total": len(_CHECKS), "failed": len(failed),
              "failed_sections": failed, "no_data_sections": no_data}

    if len(failed) == len(_CHECKS):
        return ("UNKNOWN: all %d checks failed (%s) -- tenant status cannot be "
                "determined. See the per-section errors/hints."
                % (len(_CHECKS), ", ".join(failed)), checks)

    if failed or no_data:
        frags = []
        if problems:
            frags.append("; ".join(problems))
        if failed:
            frags.append("%d/%d checks failed (%s)"
                         % (len(failed), len(_CHECKS), ", ".join(failed)))
        if no_data:
            frags.append("no data for %s" % ", ".join(no_data))
        label = "ATTENTION" if problems else "PARTIAL"
        return ("%s: %s -- overall health cannot be confirmed."
                % (label, "; ".join(frags)), checks)

    if problems:
        return ("ATTENTION: " + "; ".join(problems), checks)

    return ("Healthy: no critical/high alerts, all tunnels up, experience "
            "nominal.", checks)
