"""get_connected_users -- connected Mobile Users via Insights 3.0 (read-only)."""
import config
from client import (SaseClient, SaseApiError, mock_notice, records_of,
                    slim_records, verify_note)

_WHITELIST = ["location", "region", "connected_users"]


def get_connected_users(hours=24, limit=config.DEFAULT_LIMIT, tsg_id=None, region=None):
    limit = config.clamp_limit(limit)
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 24

    rules = [{"property": config.FILTER_PROP_TIME,
              "operator": "last_n_hours", "values": [hours]}]
    client = SaseClient()
    try:
        raw = client.insights_query("connected_users", filter_rules=rules,
                                    tsg_id=tsg_id, region=region)
    except SaseApiError as e:
        return e.as_dict(tool="get_connected_users")

    records = records_of(raw)
    rows, total = slim_records(records, _WHITELIST, limit)
    summary = raw.get("summary") or {} if isinstance(raw, dict) else {}

    per_user_view = False
    total_connected = summary.get("total_connected")
    if total_connected is None:
        if records and not any("connected_users" in r for r in records
                               if isinstance(r, dict)):
            # Round-2: users/users_list appears to be a per-user view (one row
            # per connected user), not per-location aggregates -- the row count
            # IS the connected count. (0 rows = 0 connected, also correct.)
            per_user_view = True
            total_connected = total
        else:
            total_connected = sum((r.get("connected_users") or 0) for r in records)

    out = {
        "ok": True,
        "window_hours": hours,
        "total_connected": total_connected,
        "locations_returned": len(rows),
        "by_location": rows,
    }
    if per_user_view:
        out["counting"] = "per_user_rows"
        first = records[0] if isinstance(records[0], dict) else {}
        out["field_note"] = ("users/users_list returned per-user rows without a "
                             "'connected_users' field; counted rows as connected "
                             "users. Row fields: %s -- report them so the "
                             "location grouping can be mapped."
                             % list(first.keys())[:25])
    if "trend_1h_pct" in summary:
        out["trend_1h_pct"] = summary["trend_1h_pct"]
    if total > len(rows):
        out["note"] = ("Showing %d of %d locations; raise 'limit' (max %d)."
                       % (len(rows), total, config.MAX_LIMIT))
    note = verify_note(raw)
    if note:
        out["_verify"] = note
    mock = mock_notice()
    if mock:
        out["mock_mode"] = True
        out["mock_notice"] = mock
    return out
