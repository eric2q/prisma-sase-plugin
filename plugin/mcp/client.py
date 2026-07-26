"""Shared read-only HTTP client for the Prisma SASE APIs.

Common responsibilities (design doc sec.4):
* Build auth + region + tenant headers (``X-PANW-Region``, ``Prisma-Tenant``,
  optional ``Prisma-SubTenant``).
* 401 -> refresh the token once and retry (sec.4.2).
* 429 -> honour ``Retry-After`` with bounded backoff (sec.4.2).
* Turn other failures into *actionable* messages, e.g. a region hint (sec.4.2).
* Response-slimming helper used by every tool (sec.4.3).
* ``PRISMA_MOCK`` short-circuits to local sample data (no network at all).

READ-ONLY GUARANTEE (handoff note sec.10.1): this client only ever issues
Insights *query* POSTs and ADEM GETs. There is no write/commit/push code path
anywhere -- ``insights_query`` can only build the read-only query URL, and
``adem_get`` only performs GETs.
"""
import logging
import time
import urllib.parse

import httpx

import config
import mock_data
from auth import AuthManager

log = logging.getLogger("prisma_sase.client")


class SaseApiError(RuntimeError):
    """An API failure with an operator-actionable message and optional hint."""

    def __init__(self, message, hint=None, status=None, api_code=None,
                 api_message=None):
        super().__init__(message)
        self.hint = hint
        self.status = status
        # Server-side error identity (issue #3): e.g. DATA10003 = invalid
        # resource/view name, GCP10002 = valid view but unrecognized field.
        # Discovery uses these to separate "does not exist" from "exists but
        # the payload/field name is wrong".
        self.api_code = api_code
        self.api_message = api_message

    def as_dict(self, tool=None):
        d = {"ok": False, "error": str(self)}
        if self.hint:
            d["hint"] = self.hint
        if self.status is not None:
            d["status"] = self.status
        if self.api_code:
            d["api_error_code"] = self.api_code
        if self.api_message:
            d["api_error_message"] = self.api_message
        if tool:
            d["tool"] = tool
        return d


def _headers(token, tsg, region, has_body):
    h = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "X-PANW-Region": region,
        "Prisma-Tenant": tsg,
    }
    if has_body:
        h["Content-Type"] = "application/json"
    if config.DEFAULT_SUBTENANT:
        h["Prisma-SubTenant"] = config.DEFAULT_SUBTENANT
    return h


def _require_ctx(tsg, region):
    missing = []
    if not tsg:
        missing.append("PRISMA_TSG_ID (or the tsg_id argument)")
    if not region:
        missing.append("PRISMA_REGION (or the region argument)")
    if missing:
        hint = ("Easiest fix: fill in the plugin's enable dialog (Desktop: "
                "Settings -> Plugins -> prisma-sase; the Claude Code CLI "
                "prompts for the same four values on enable), then fully "
                "restart the app. Without "
                "that dialog (cloud session, CI, standalone install), put the "
                "values in ~/.prisma-sase.env (KEY=VALUE lines, chmod 600) or "
                "set the environment variable(s) -- on macOS, GUI apps often "
                "do NOT inherit launchctl setenv variables. Or run with "
                "PRISMA_MOCK=1 to try the tool offline.")
        # When the host is the cause, lead with that -- the generic advice
        # above points at a dialog that may be exactly what never ran.
        # userconfig_diagnosis() subsumes placeholder_hint().
        diag = config.userconfig_diagnosis()
        if diag:
            hint = diag["message"]
        raise SaseApiError("Missing required context: " + ", ".join(missing),
                           hint=hint)


class SaseClient:
    """Thin wrapper around httpx + the AuthManager. Cheap to construct."""

    def __init__(self):
        self._auth = AuthManager.instance()

    # -- Insights 3.0 (read-only POST query) ------------------------------
    def insights_query(self, kind, filter_rules=None, tsg_id=None, region=None):
        tsg = config.resolve_tsg(tsg_id)
        region = config.resolve_region(region)
        mapping = config.INSIGHTS_MAP.get(kind)
        if not mapping:
            raise SaseApiError("Unknown Insights query kind '%s'." % kind)

        payload_used = "custom_filter" if filter_rules else "time_filter"
        if config.MOCK_MODE:
            data = mock_data.insights(kind, filter_rules)
        else:
            _require_ctx(tsg, region)
            path = config.insights_path(mapping["resource"], mapping.get("view"))
            # Round-2 field report BUG-1: some views (tunnels/tunnel_list)
            # REJECT an empty filter with HTTP 400 and require a time window.
            # When the caller supplies no rules, inject a default 24h time
            # filter; if that 400s, retry once with a truly empty filter (some
            # views only accept that). Both variants are what discover_insights
            # probes, so behaviour matches discovery.
            injected = False
            rules = filter_rules
            if not rules:
                rules = default_time_rules(24)
                injected = True
            try:
                data = self._request("POST", path, tsg, region,
                                     json_body={"filter": {"rules": rules}})
            except SaseApiError as e:
                if injected and e.status == 400:
                    try:
                        data = self._request("POST", path, tsg, region,
                                             json_body={"filter": {"rules": []}})
                        payload_used = "empty_filter"
                    except SaseApiError as e2:
                        self._augment_mapping_error(e2, mapping)
                        raise e2
                else:
                    # Round-1 report: a 400/404 on an UNVERIFIED mapping is
                    # almost always a wrong resource/view name -- say so in the
                    # error itself.
                    self._augment_mapping_error(e, mapping)
                    raise

        # Carry resource identity + verification status for the tool layer.
        if isinstance(data, dict):
            data["_meta"] = {
                "resource": mapping["resource"],
                "view": mapping["view"],
                "verified_resource": mapping.get("verified", False),
                "payload_used": payload_used,
            }
        return data

    @staticmethod
    def _augment_mapping_error(err, mapping):
        if err.status in (400, 404) and not mapping.get("verified", False):
            extra = ("Likely cause: '%s/%s' is an unverified best-guess "
                     "resource/view for this tenant. Run the discover_insights "
                     "tool to find the real names, then set PRISMA_INSIGHTS_MAP."
                     % (mapping["resource"], mapping["view"]))
            err.hint = (err.hint + " " + extra) if err.hint else extra

    # -- Insights probe: query an explicit resource/view (read-only) -------
    def insights_probe(self, resource, view, filter_rules=None,
                       properties=None, tsg_id=None, region=None,
                       prefix=None):
        """POST a query at an explicit resource/view (used by discovery).

        Same read-only query endpoint as insights_query -- no mapping lookup,
        no error enrichment; the caller interprets failures.
        properties: optional explicit SELECT list. Issue #3: probing with
        ``["*"]`` (always a valid SELECT) lets the caller separate "view does
        not exist" (DATA10003/Invalid resource) from "view exists but a field
        name is wrong" (GCP10002/Unrecognized name). Omit to send the same
        filter-only shape the live-verified query tools use.
        prefix: query API family ("insights_v3" default, "sase_v2"). Selects
        the path prefix AND the host together -- they differ per family.
        """
        tsg = config.resolve_tsg(tsg_id)
        region = config.resolve_region(region)
        if config.MOCK_MODE:
            return mock_data.probe(resource, view)
        _require_ctx(tsg, region)
        path = config.insights_path(resource, view, prefix=prefix)
        base = config.query_base(prefix, region)
        body = {"filter": {"rules": filter_rules or []}}
        if properties is not None:
            body["properties"] = properties
        return self._request("POST", path, tsg, region, json_body=body,
                             base=base)

    # -- ADEM (read-only GET) ---------------------------------------------
    def adem_get(self, subpath, params=None, tsg_id=None, region=None):
        tsg = config.resolve_tsg(tsg_id)
        region = config.resolve_region(region)
        if config.MOCK_MODE:
            return mock_data.adem(subpath, params or {})
        _require_ctx(tsg, region)
        path = config.ADEM_BASE_PATH + subpath
        if params:
            path = path + "?" + urllib.parse.urlencode(params)
        return self._request("GET", path, tsg, region, json_body=None)

    # -- core request with retry ------------------------------------------
    def _request(self, method, path, tsg, region, json_body=None, _attempt=0,
                 base=None):
        # ``base`` overrides the default 3.0 host. The 2.0 query family lives
        # on a regional pa-<region>01.api.prismaaccess.com host (issue #15);
        # sending its path to API_BASE returns a bare 404.
        api_base = base or config.API_BASE
        url = api_base + path
        token = self._auth.get_token(tsg)
        headers = _headers(token, tsg, region, json_body is not None)
        try:
            resp = httpx.request(method, url, headers=headers, json=json_body,
                                 timeout=config.HTTP_TIMEOUT)
        except httpx.HTTPError as e:
            raise SaseApiError("Request to %s failed: %s" % (path, e),
                               hint="Check network reachability to " + api_base) from e

        # 401 -> refresh token once, then retry.
        if resp.status_code == 401 and _attempt == 0:
            log.info("401 on %s -- refreshing token and retrying once.", path)
            self._auth.invalidate(tsg)
            self._auth.get_token(tsg, force=True)
            return self._request(method, path, tsg, region, json_body,
                                 _attempt=1, base=base)

        # 429 -> bounded backoff.
        if resp.status_code == 429 and _attempt < 3:
            wait = _retry_after(resp, _attempt)
            log.info("429 on %s -- backing off %.1fs.", path, wait)
            time.sleep(wait)
            return self._request(method, path, tsg, region, json_body,
                                 _attempt=_attempt + 1, base=base)

        if resp.status_code == 403:
            raise SaseApiError(
                "Access denied (403) on %s." % path,
                hint="The service account likely lacks a read-only role on this "
                     "TSG, or the wrong TSG/region is set. If this appeared "
                     "suddenly during heavy querying: the gateway blocks a "
                     "source IP for 10 minutes above ~4000 calls/min -- wait "
                     "and retry (the normal limit is 1000 calls/min -> 429).",
                status=403)
        if resp.status_code == 404:
            raise SaseApiError(
                "Not found (404) on %s." % path,
                hint="The resource/view name may not match this tenant/version -- "
                     "confirm it against the live tenant (design doc sec.11.1).",
                status=404)
        if resp.status_code >= 400:
            # Round-2 field report BUG-1: do NOT lead with region -- a 400 here
            # is most often a filter-payload or resource/view mismatch.
            code, msg = _extract_api_error(resp)
            detail = ""
            if code or msg:
                detail = " [%s%s]" % (code or "", (": " + msg) if msg else "")
            raise SaseApiError(
                "API returned HTTP %d on %s.%s" % (resp.status_code, path, detail),
                hint="Most common causes: the filter payload shape is not "
                     "accepted by this view, or the resource/view name does not "
                     "match this tenant -- run discover_insights to probe both. "
                     "Only if other views also fail, re-check X-PANW-Region "
                     "(currently '%s')." % region, status=resp.status_code,
                api_code=code, api_message=msg)

        try:
            return resp.json()
        except ValueError:
            raise SaseApiError("Non-JSON response from %s." % path,
                               status=resp.status_code)


def _extract_api_error(resp):
    """Best-effort (code, message) from an error body; (None, None) otherwise.

    Insights error bodies carry an identity worth surfacing (issue #3), e.g.
    DATA10003 "Invalid resource" (name does not exist) vs GCP10002
    "Unrecognized name: X" (view exists, field name wrong). Shapes vary, so
    look in the common envelopes. Message is truncated -- it is diagnostic
    text, never echoed secrets (the token endpoint path never reaches here).
    """
    try:
        body = resp.json()
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    cand = body
    if isinstance(body.get("error"), dict):
        cand = body["error"]
    elif (isinstance(body.get("errors"), list) and body["errors"]
          and isinstance(body["errors"][0], dict)):
        cand = body["errors"][0]
    code = cand.get("errorCode") or cand.get("code")
    msg = cand.get("message") or cand.get("msg") or cand.get("detail")
    return (str(code) if code not in (None, "") else None,
            str(msg)[:200] if msg not in (None, "") else None)


def _retry_after(resp, attempt):
    ra = resp.headers.get("Retry-After")
    if ra:
        try:
            return min(float(ra), 30.0)
        except ValueError:
            pass
    return min(2.0 ** attempt, 30.0)


# -- shared helpers used by the tools -----------------------------------------
def default_time_rules(hours=24):
    """The standard last-N-hours filter rule set."""
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 24
    return [{"property": config.FILTER_PROP_TIME,
             "operator": "last_n_hours", "values": [hours]}]


def records_of(raw):
    """Pull the record list out of a response regardless of the wrapper key."""
    if not isinstance(raw, dict):
        return []
    for key in ("data", "items", "results", "records"):
        val = raw.get(key)
        if isinstance(val, list):
            return val
    return []


def slim_records(records, whitelist, limit):
    """Trim each record to whitelisted keys and cap to ``limit``.

    Returns ``(rows, total)`` where ``total`` is the pre-truncation count so the
    tool can tell the model how many matched (design doc sec.4.3).
    """
    total = len(records)
    rows = []
    for r in records[:limit]:
        if whitelist:
            rows.append({k: r.get(k) for k in whitelist if k in r})
        else:
            rows.append(r)
    return rows, total


def verify_note(raw):
    """If the queried Insights resource/view is an unverified default, say so."""
    meta = (raw or {}).get("_meta") or {} if isinstance(raw, dict) else {}
    if meta and not meta.get("verified_resource", True):
        return ("Insights resource/view '%s/%s' is a documented default not yet "
                "confirmed against this tenant (design doc sec.11.1); if this "
                "returns 404/empty, correct it via PRISMA_INSIGHTS_MAP."
                % (meta.get("resource"), meta.get("view")))
    return None
