"""PAN-OS XML API tools for NGFW tenants -- a firewall or Panorama reached
DIRECTLY, as opposed to a Prisma Access tenant reached through the SASE APIs.

Merged in 0.10.0 from edoscars/pan-os-mcp (MIT, (c) 2025 Edoardo Scarsini; see
THIRD_PARTY_NOTICES.md). The five tools and the way each request is built are
that project's; what changed is everything around them, to meet the rules the
rest of this server already lives by:

* The host and API key are CONFIGURATION, never tool arguments. A tool call
  names a tenant; where that tenant lives and how to authenticate to it come
  from the operator's own machine. Nothing in a conversation can point the
  key at another host. (Upstream hard-coded both in the source file.)
* The key travels in the X-PAN-KEY header of a POST, never in a URL.
* TLS verification is ON. A tenant can trust a private CA (``ca_bundle``) or,
  explicitly, switch verification off -- and then every response says so.
  (Upstream disabled it unconditionally.)
* WRITES ARE OFF BY DEFAULT, per tenant. Without ``allow_write`` a tenant
  accepts only ``<show>`` operational commands and config get/show; commits,
  config changes and every other operational command are refused, and the two
  commit tools are not even registered unless some tenant allows writes.
* Config reads redact secret-bearing elements (password hashes, keys) before
  the result reaches the conversation.
"""
import json
import ssl
import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

import httpx

import config
from client import mock_notice

READ_CONFIG_ACTIONS = ("get", "show", "complete")
WRITE_CONFIG_ACTIONS = ("set", "edit", "delete", "rename", "clone", "move",
                        "override", "multi-move", "multi-clone")
_MOVE_WHERE = ("before", "after", "top", "bottom")

# Leaf elements whose text is credential material in a PAN-OS config.
_SECRET_TAGS = frozenset((
    "phash", "password", "private-key", "key", "bind-password", "secret",
    "auth-password", "priv-password", "authpwd", "privpwd", "passphrase",
    "pre-shared-key", "shared-secret", "api-key", "token", "client-secret",
    "community", "md5", "authentication-key", "password-hash", "public-key",
))
_MAX_CHARS = 60000

_MOCK_TENANT = {"name": "sample-ngfw", "kind": config.KIND_NGFW,
                "host": "sample-fw.invalid", "api_key": "", "api_key_cmd": "",
                "verify_tls": True, "ca_bundle": "", "allow_write": False,
                "source": "mock"}


class PanosError(RuntimeError):
    def __init__(self, message, hint=None):
        super().__init__(message)
        self.hint = hint


# -- shared plumbing ----------------------------------------------------------
def _tenant(name):
    try:
        return config.get_tenant(name, config.KIND_NGFW)
    except config.TenantError:
        # Offline demo with nothing configured: a labelled stand-in firewall.
        if config.MOCK_MODE and name in (None, ""):
            return dict(_MOCK_TENANT)
        raise


def _stamp(out, tenant=None):
    if tenant:
        out["tenant"] = tenant["name"]
        out["environment"] = "ngfw"
        out["host"] = tenant["host"]
        if not tenant["verify_tls"]:
            out["tls_verification"] = (
                "DISABLED for this tenant -- the firewall's identity was not "
                "checked. Set ca_bundle to its CA instead of verify_tls:false.")
    mock = mock_notice()
    if mock:
        out["mock_mode"] = True
        out["mock_notice"] = mock
    return out


def _fail(tool, message, hint=None, tenant=None, **extra):
    out = {"ok": False, "tool": tool, "error": message}
    if hint:
        out["hint"] = hint
    out.update(extra)
    return _stamp(out, tenant)


def _write_blocked(tool, tenant, what):
    return _fail(
        tool,
        "%s changes the firewall, and tenant '%s' is read-only."
        % (what, tenant["name"]),
        hint="Writes are off unless the operator sets \"allow_write\": true "
             "for this tenant in the tenants file (or PANOS_ENABLE_WRITE=1 "
             "for the environment-defined tenant) and restarts the app. That "
             "is a decision made on the operator's machine, not something to "
             "work around from the conversation.",
        tenant=tenant, write_blocked=True)


def _parse_fragment(xml_text):
    """Parse caller-supplied XML, refusing DTDs and entity declarations."""
    text = (xml_text or "").strip()
    if not text:
        raise ValueError("it is empty")
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise ValueError("DTD and entity declarations are not accepted")
    try:
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError("not well-formed: %s" % e)


def _to_obj(elem):
    """ElementTree -> plain dict/str. Attributes keep an '@' prefix; repeated
    child tags become lists; secret-bearing leaves are redacted."""
    node = {"@" + k: v for k, v in elem.attrib.items()}
    children = list(elem)
    if not children:
        text = (elem.text or "").strip()
        if text and elem.tag.lower() in _SECRET_TAGS:
            text = "<redacted>"
        if not node:
            return text
        if text:
            node["#text"] = text
        return node
    for child in children:
        value = _to_obj(child)
        if child.tag in node:
            if not isinstance(node[child.tag], list):
                node[child.tag] = [node[child.tag]]
            node[child.tag].append(value)
        else:
            node[child.tag] = value
    return node


def _bound(obj):
    if isinstance(obj, dict):
        return {k: _bound(v) for k, v in obj.items()}
    if isinstance(obj, list):
        cut = [_bound(v) for v in obj[:config.MAX_LIMIT]]
        if len(obj) > config.MAX_LIMIT:
            cut.append("<%d more omitted>" % (len(obj) - config.MAX_LIMIT))
        return cut
    return obj


def _message(root):
    lines = [(e.text or "").strip() for e in root.iter("line")]
    lines = [t for t in lines if t]
    if lines:
        return " ".join(lines)[:500]
    msg = root.find(".//msg")
    return ((msg.text or "").strip()[:500]) if msg is not None else ""


def _post(tenant, params):
    """One XML API call; returns the parsed <response> element."""
    if config.MOCK_MODE:
        return ET.fromstring(_mock_response(params))

    key = config.tenant_secret(tenant)
    if not key:
        raise PanosError(
            "No API key is available for tenant '%s'." % tenant["name"],
            hint="Give the tenant an api_key_cmd that prints the key (e.g. a "
                 "keychain lookup). The key is deliberately not a tool "
                 "argument: credentials must never travel through the "
                 "conversation.")
    verify = True
    if not tenant["verify_tls"]:
        verify = False
    elif tenant["ca_bundle"]:
        try:
            verify = ssl.create_default_context(cafile=tenant["ca_bundle"])
        except (OSError, ssl.SSLError) as e:
            raise PanosError("ca_bundle for tenant '%s' could not be loaded "
                             "(%s)." % (tenant["name"], e.__class__.__name__))
    try:
        resp = httpx.post("https://%s/api/" % tenant["host"], data=params,
                          headers={"X-PAN-KEY": key,
                                   "Accept": "application/xml"},
                          timeout=config.HTTP_TIMEOUT, verify=verify)
    except httpx.HTTPError as e:
        text = str(e)[:200]
        hint = "Check that %s is reachable from this machine." % tenant["host"]
        if "CERTIFICATE" in text.upper() or "SSL" in text.upper():
            hint = ("The firewall's certificate is not trusted by this "
                    "machine. Point the tenant's ca_bundle at the CA that "
                    "signed it; verify_tls:false is the last resort.")
        raise PanosError("Request to %s failed: %s: %s"
                         % (tenant["host"], e.__class__.__name__, text),
                         hint=hint)
    body = resp.text or ""
    if not body.lstrip().startswith("<"):
        raise PanosError("%s answered HTTP %d with a non-XML body."
                         % (tenant["host"], resp.status_code),
                         hint="Is this the firewall's management address, "
                              "and is the XML API enabled for this admin?")
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        raise PanosError("%s returned XML that could not be parsed."
                         % tenant["host"])


def _result(tenant, root):
    status = root.get("status")
    out = {"ok": status == "success", "status": status}
    if root.get("code"):
        out["code"] = root.get("code")
    body = _bound(_to_obj(root))
    if isinstance(body, dict):
        result = body.get("result")
        if result is None:
            result = {k: v for k, v in body.items() if not k.startswith("@")}
    else:
        result = body
    if len(json.dumps(result, ensure_ascii=False)) > _MAX_CHARS:
        text = json.dumps(result, ensure_ascii=False)
        result = {"truncated": True, "total_chars": len(text),
                  "preview": text[:_MAX_CHARS]}
        out["note"] = ("The result was too large to return whole -- narrow "
                       "the command or the XPath.")
    out["result"] = result
    if not out["ok"]:
        out["error"] = _message(root) or "PAN-OS reported an error."
        if out.get("code") == "403":
            out["hint"] = ("Invalid API key, or this admin's role does not "
                           "allow the request.")
    return _stamp(out, tenant)


def _run(tool, tenant_name, params, write=None):
    try:
        tenant = _tenant(tenant_name)
    except config.TenantError as e:
        return _fail(tool, str(e),
                     hint="list_tenants shows every configured environment.")
    if write and not tenant["allow_write"]:
        return _write_blocked(tool, tenant, write)
    try:
        root = _post(tenant, params)
    except PanosError as e:
        return _fail(tool, str(e), hint=e.hint, tenant=tenant)
    return _result(tenant, root)


def _job_hint(out):
    job = out.get("result", {}).get("job") if isinstance(out.get("result"),
                                                          dict) else None
    if out.get("ok") and job:
        out["next_step"] = (
            "The commit runs as job %s and is NOT finished yet. Check it with "
            "panos_op_command('<show><jobs><id>%s</id></jobs></show>')."
            % (job, job))
    return out


# -- the five tools -----------------------------------------------------------
def panos_system_info(tenant=None):
    """show system info: hostname, model, serial, PAN-OS version, uptime."""
    return _run("panos_system_info", tenant,
                {"type": "op",
                 "cmd": "<show><system><info></info></system></show>"})


def panos_op_command(xml_cmd, tenant=None):
    """An operational command in XML form. <show> is always allowed; anything
    else (request, clear, test, debug, ...) needs a write-enabled tenant."""
    try:
        root = _parse_fragment(xml_cmd)
    except ValueError as e:
        return _fail("panos_op_command", "xml_cmd was refused: %s." % e,
                     hint="Pass the XML form of the CLI command, e.g. "
                          "<show><system><info></info></system></show>.")
    write = None if root.tag == "show" else (
        "The operational command <%s>" % root.tag)
    return _run("panos_op_command", tenant,
                {"type": "op", "cmd": xml_cmd.strip()}, write=write)


def panos_config_action(action, xpath, element_xml=None, newname=None,
                        from_path=None, dst=None, where=None, tenant=None):
    """A config API action on an XPath. get/show/complete are reads; set,
    edit, delete, rename, clone, move, override need a write-enabled tenant."""
    tool = "panos_config_action"
    action = (action or "").strip().lower()
    valid = READ_CONFIG_ACTIONS + WRITE_CONFIG_ACTIONS
    if action not in valid:
        return _fail(tool, "Unknown config action '%s'." % action,
                     hint="Valid actions: %s." % ", ".join(valid))
    if not xpath or not str(xpath).strip().startswith("/"):
        return _fail(tool, "xpath must be an absolute XPath starting with "
                           "/config.")
    params = {"type": "config", "action": action, "xpath": str(xpath).strip()}
    if element_xml:
        try:
            _parse_fragment(element_xml)
        except ValueError as e:
            return _fail(tool, "element_xml was refused: %s." % e)
        params["element"] = element_xml.strip()
    if newname:
        params["newname"] = str(newname)
    if from_path:
        params["from"] = str(from_path)
    if dst:
        params["dst"] = str(dst)
    if where:
        if where not in _MOVE_WHERE:
            return _fail(tool, "where must be one of: %s."
                               % ", ".join(_MOVE_WHERE))
        params["where"] = where
    write = None if action in READ_CONFIG_ACTIONS else (
        "The config action '%s'" % action)
    return _run(tool, tenant, params, write=write)


def panos_commit_config(force=False, partial_xml=None, tenant=None):
    """Commit the candidate configuration (optionally forced or partial)."""
    cmd = "<commit>"
    if force:
        cmd += "<force></force>"
    if partial_xml:
        try:
            root = _parse_fragment(partial_xml)
        except ValueError as e:
            return _fail("panos_commit_config",
                         "partial_xml was refused: %s." % e)
        if root.tag != "partial":
            return _fail("panos_commit_config",
                         "partial_xml must be a <partial>...</partial> "
                         "element.")
        cmd += partial_xml.strip()
    cmd += "</commit>"
    return _job_hint(_run("panos_commit_config", tenant,
                          {"type": "commit", "cmd": cmd}, write="A commit"))


def panos_commit_all_shared_policy(device_group=None, validate_only=False,
                                   tenant=None):
    """Panorama: push shared policy to managed devices (or validate only)."""
    cmd = "<commit-all><shared-policy>"
    if validate_only:
        cmd += "<validate-only></validate-only>"
    if device_group:
        cmd += ("<device-group><entry name=%s/></device-group>"
                % quoteattr(str(device_group)))
    cmd += "</shared-policy></commit-all>"
    return _job_hint(_run("panos_commit_all_shared_policy", tenant,
                          {"type": "commit", "action": "all", "cmd": cmd},
                          write="A Panorama push"))


# -- sample responses for PRISMA_MOCK=1 ---------------------------------------
_MOCK_SYSINFO = (
    '<response status="success"><result><system>'
    "<hostname>sample-fw</hostname><model>PA-440</model>"
    "<serial>000000000000</serial><sw-version>11.2.4</sw-version>"
    "<uptime>12 days, 3:04:05</uptime>"
    "<operational-mode>normal</operational-mode>"
    "</system></result></response>")


def _mock_response(params):
    kind = params.get("type")
    if kind == "op":
        if "<system><info>" in params.get("cmd", ""):
            return _MOCK_SYSINFO
        return ('<response status="success"><result><msg>sample output for '
                "an operational command</msg></result></response>")
    if kind == "config":
        if params.get("action") in READ_CONFIG_ACTIONS:
            return ('<response status="success" code="19"><result count="1">'
                    '<entry name="sample-admin"><phash>$1$sample$hash</phash>'
                    "<permissions><role-based><superreader>yes</superreader>"
                    "</role-based></permissions></entry></result></response>")
        return ('<response status="success" code="20"><msg>command succeeded'
                "</msg></response>")
    return ('<response status="success" code="19"><result><msg><line>Commit '
            "job enqueued with jobid 42</line></msg><job>42</job></result>"
            "</response>")
