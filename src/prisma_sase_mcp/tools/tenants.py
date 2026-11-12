"""list_tenants -- which environments this server can reach, and of what kind.

A tenant is a named environment. There are two kinds, and they are reached in
completely different ways:

* ``prisma_access`` -- a Prisma Access / SASE tenant (a TSG), reached through
  the cloud SASE APIs with an OAuth service account. Served by the SASE tools
  (get_sase_status, query_alerts, query_incidents, ...).
* ``ngfw`` -- an on-prem firewall or Panorama, reached DIRECTLY over its PAN-OS
  XML API with an API key. Served by the panos_* tools.

This tool reports names, kinds and non-secret identifiers only. It never
returns a secret, and never the command that fetches one.
"""
import config
from client import mock_notice

_SASE_TOOLS = ("get_sase_status, query_alerts, get_remote_networks, "
               "get_connected_users, get_user_experience, query_incidents, "
               "get_incident")
_NGFW_TOOLS = "panos_system_info, panos_op_command, panos_config_action"


def list_tenants():
    rows = []
    notes = []
    for name in sorted(config.TENANTS):
        t = config.TENANTS[name]
        row = {"name": name, "kind": t["kind"],
               "default": config.TENANT_DEFAULTS.get(t["kind"]) == name,
               "defined_in": t["source"],
               "credentials": config.tenant_secret_source(t)}
        if t["kind"] == config.KIND_SASE:
            row.update(tsg_id=t["tsg_id"], region=t["region"],
                       use_with=_SASE_TOOLS)
        else:
            tls = "on"
            if not t["verify_tls"]:
                tls = "DISABLED"
            elif t["ca_bundle"]:
                tls = "on (private CA)"
            row.update(host=t["host"], write_enabled=bool(t["allow_write"]),
                       tls_verification=tls, use_with=_NGFW_TOOLS + (
                           ", panos_commit_config, "
                           "panos_commit_all_shared_policy"
                           if t["allow_write"] else ""))
        if row["credentials"] == "plaintext_in_file":
            notes.append(
                "Tenant '%s' keeps its secret as plaintext in the tenants "
                "file. Prefer a command that reads it from the OS keychain "
                "(secret_cmd / api_key_cmd)." % name)
        if row["credentials"] == "missing":
            notes.append("Tenant '%s' has no usable credentials yet." % name)
        rows.append(row)

    notes.extend(config.TENANT_PROBLEMS)
    if not rows:
        notes.append(
            "No tenants are configured. A single Prisma Access tenant needs "
            "only the usual setup; several tenants, or any on-prem firewall, "
            "go in ~/.prisma-sase-tenants.json (see the README).")
    for kind, label in ((config.KIND_SASE, "Prisma Access"),
                        (config.KIND_NGFW, "NGFW")):
        names = [r["name"] for r in rows if r["kind"] == kind]
        if len(names) > 1 and not config.TENANT_DEFAULTS.get(kind):
            notes.append(
                "Several %s tenants and no default: every call must pass "
                "tenant=<name> (%s)." % (label, ", ".join(names)))

    out = {"ok": True, "tenants": rows,
           "defaults": dict(config.TENANT_DEFAULTS),
           "tenants_file": config.TENANTS_FILE_USED, "notes": notes}
    mock = mock_notice()
    if mock:
        out["mock_mode"] = True
        out["mock_notice"] = mock
    return out
