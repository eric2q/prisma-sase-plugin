"""Guided credential setup for the Local MCP server panel.

    uvx --from git+https://github.com/eric2q/prisma-sase-plugin prisma-sase-setup

Why this exists
---------------
The Local MCP servers panel is a perfectly good form -- name, command, args,
and a list of environment variables. Two things it does not give you:

  1. Any explanation of what to type. It shows an empty key field, so you have
     to already know the variable is called PRISMA_TSG_ID, and that its value
     is the digits after the "@" in your Client ID.
  2. Anywhere safe to put the secret. Panel values are stored in plaintext in
     claude_desktop_config.json. That file is chmod 600, but it rides along in
     Time Machine, iCloud, and any backup that copies your home directory.

This wizard supplies both: it prompts with explanations, puts the secret in the
OS keychain, and emits a panel block whose only secret-shaped entry is a
PRISMA_SECRET_CMD that fetches from the keychain at launch.

It is optional. Typing four variables into the panel by hand works fine -- you
just end up with the secret in plaintext, exactly like most MCP servers do.

Stdlib only: this must run before any dependency is installed.
"""

import getpass
import json
import os
import platform
import shutil
import subprocess
import sys

SERVICE = "prisma-sase"
ACCOUNT = "client_secret"

# Matches plugin/setup-keychain.sh -- same service/account, so the two are
# interchangeable and neither strands a secret the other cannot find.
GIT_URL = "git+https://github.com/eric2q/prisma-sase-plugin"
SERVER_NAME = "prisma-sase"


# --------------------------------------------------------------------------
# secret backends
# --------------------------------------------------------------------------

def _backend():
    """Pick a secret store. Returns (name, fetch_argv) or (None, None)."""
    if platform.system() == "Darwin" and shutil.which("security"):
        return "keychain", ["security", "find-generic-password",
                            "-s", SERVICE, "-a", ACCOUNT, "-w"]
    if shutil.which("secret-tool"):
        return "secret-tool", ["secret-tool", "lookup",
                               "service", SERVICE, "key", ACCOUNT]
    if shutil.which("pass"):
        return "pass", ["pass", "show", "%s/%s" % (SERVICE, ACCOUNT)]
    return None, None


def _store_secret(backend, secret):
    """Write the secret to the keychain. Never passes it as an argv element
    where a backend offers stdin -- argv is world-readable via `ps`."""
    if backend == "keychain":
        # `security` has no stdin mode for add-generic-password. The -w value
        # is visible in `ps` for the lifetime of this call. macOS restricts
        # argv visibility to the same UID, and the window is milliseconds.
        subprocess.run(["security", "add-generic-password",
                        "-s", SERVICE, "-a", ACCOUNT, "-U", "-w", secret],
                       check=True)
    elif backend == "secret-tool":
        subprocess.run(["secret-tool", "store",
                        "--label=Prisma SASE client secret",
                        "service", SERVICE, "key", ACCOUNT],
                       input=secret.encode(), check=True)
    elif backend == "pass":
        subprocess.run(["pass", "insert", "-m", "-f",
                        "%s/%s" % (SERVICE, ACCOUNT)],
                       input=(secret + "\n").encode(), check=True,
                       stdout=subprocess.DEVNULL)


def _fetch_secret(fetch_argv):
    try:
        out = subprocess.run(fetch_argv, capture_output=True, timeout=15)
    except Exception:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace").strip() or None


def _quote(argv):
    """Render argv as the single shell string PRISMA_SECRET_CMD expects."""
    import shlex
    return " ".join(shlex.quote(a) for a in argv)


# --------------------------------------------------------------------------
# prompting
# --------------------------------------------------------------------------

def _header(title, explain):
    """Print a prompt's heading.

    Flushed explicitly: getpass writes to /dev/tty, bypassing stdout's buffer,
    so without this the hidden-input prompt appears *above* the text
    explaining what to type.
    """
    print("")
    print("  %s" % title)
    for line in explain:
        print("    %s" % line)
    sys.stdout.flush()


def _abort():
    print("\naborted -- nothing was changed.")
    sys.exit(130)


def _ask(title, explain, default=None):
    _header(title, explain)
    suffix = " [%s]" % default if default else ""
    while True:
        try:
            val = input("  > value%s: " % suffix)
        except (EOFError, KeyboardInterrupt):
            _abort()
        val = val.strip()
        if not val and default:
            return default
        if val:
            return val
        print("    (required)")


def _ask_hidden(prompt):
    """Read a secret without echoing. Returns None if there is no terminal.

    Piped or redirected stdin has no tty, so getpass falls back to echoing
    input and then raises EOFError at end of stream. Callers get None and can
    carry on without a secret rather than dying in a traceback.
    """
    try:
        return getpass.getpass(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None
    except Exception:
        return None


def _panel_config_dirs():
    """Every directory a Claude desktop build might keep its config in.

    The app name is not always "Claude": third-party/enterprise distributions
    use a suffixed directory (Claude-3p is the one seen in the field), and a
    machine can carry several side by side. Writing blindly to "Claude" on
    such a machine puts the entry in a file the running app never reads --
    the setup reports success and no tools appear.
    """
    home = os.path.expanduser("~")
    if platform.system() == "Darwin":
        base = os.path.join(home, "Library", "Application Support")
    elif platform.system() == "Windows":
        base = os.environ.get("APPDATA", home)
    else:
        base = os.path.join(home, ".config")
    dirs = [os.path.join(base, "Claude")]
    try:
        for name in sorted(os.listdir(base)):
            if name.startswith("Claude-"):
                dirs.append(os.path.join(base, name))
    except OSError:
        pass
    return dirs


def _panel_config_path():
    """Pick the config file to write.

    PRISMA_PANEL_CONFIG wins outright. Otherwise: the one existing file if
    there is exactly one, the most recently modified if there are several
    (that is the app actually in use), and the plain "Claude" path if none
    exists yet.
    """
    override = os.environ.get("PRISMA_PANEL_CONFIG")
    if override:
        return os.path.expanduser(override)
    candidates = [os.path.join(d, "claude_desktop_config.json")
                  for d in _panel_config_dirs()]
    existing = [p for p in candidates if os.path.exists(p)]
    if not existing:
        return candidates[0]
    if len(existing) == 1:
        return existing[0]
    return max(existing, key=lambda p: os.path.getmtime(p))


def _uvx_path():
    return shutil.which("uvx") or "uvx"


def _panel_entry(client_id, tsg_id, region, secret_cmd):
    """The block the user pastes -- or that we write for them."""
    env = {
        # uvx and its resolved interpreter must be findable; the app does not
        # pass a login shell's PATH to MCP servers.
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "PRISMA_CLIENT_ID": client_id,
        "PRISMA_TSG_ID": tsg_id,
        "PRISMA_REGION": region,
    }
    if secret_cmd:
        env["PRISMA_SECRET_CMD"] = secret_cmd
    else:
        env["PRISMA_CLIENT_SECRET"] = "<paste your client secret here>"
    if platform.system() == "Windows":
        env.pop("PATH")
    return {
        "command": _uvx_path(),
        "args": ["--from", GIT_URL, "prisma-sase-mcp"],
        "env": env,
    }


def _write_panel_config(entry):
    """Merge the entry into claude_desktop_config.json, backing it up first.

    Returns (path, action) where action is 'created' | 'updated' | 'added'.
    """
    path = _panel_config_path()
    data = {}
    action = "created"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)          # a parse error must stop us, not
                                          # silently overwrite their servers
        shutil.copy2(path, path + ".bak")
        action = "updated" if SERVER_NAME in (data.get("mcpServers") or {}) \
                 else "added"
    data.setdefault("mcpServers", {})[SERVER_NAME] = entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path, action


# --------------------------------------------------------------------------

BANNER = """
== prisma-sase setup ==

Collects the four values the MCP server needs, puts the Client Secret in your
OS keychain, and prepares the Local MCP servers entry.
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    show = "--show" in argv
    print_only = "--print" in argv

    if "-h" in argv or "--help" in argv:
        print(__doc__)
        print("Options:")
        print("  --print   show the panel JSON, do not write any file")
        print("  --show    report what is already stored, change nothing")
        return 0

    backend, fetch_argv = _backend()

    if show:
        print("secret backend : %s" % (backend or "none available"))
        if backend:
            got = _fetch_secret(fetch_argv)
            print("client secret  : %s" %
                  ("STORED (value not printed)" if got else "not stored"))
            print("fetch command  : %s" % _quote(fetch_argv))
        path = _panel_config_path()
        print("panel config   : %s" %
              (path if os.path.exists(path) else "%s (does not exist)" % path))
        others = [p for p in
                  (os.path.join(d, "claude_desktop_config.json")
                   for d in _panel_config_dirs())
                  if os.path.exists(p) and p != path]
        for p in others:
            print("  also present : %s (not written to)" % p)
        return 0

    print(BANNER)
    if backend:
        print("  secret store: %s" % backend)
    else:
        print("  secret store: NONE FOUND -- the secret will have to go into")
        print("  the panel in plaintext. On Linux: apt install libsecret-tools")

    client_id = _ask(
        "Client ID",
        ["The service account's Client ID, which looks like",
         "  apikey@1234567890.iam.panserviceaccount.com",
         "Strata Cloud Manager > Settings > Identity & Access > Service Accounts"])

    default_tsg = ""
    if "@" in client_id:
        tail = client_id.split("@", 1)[1].split(".", 1)[0]
        if tail.isdigit():
            default_tsg = tail

    tsg_id = _ask(
        "TSG ID",
        ["Tenant Service Group ID -- the digits between '@' and '.iam' in the",
         "Client ID above." +
         ("  Detected from what you typed." if default_tsg else "")],
        default=default_tsg or None)

    region = _ask(
        "Region",
        ["The X-PANW-Region value for your tenant, e.g. americas, europe, sg,",
         "de, uk. This is the tenant's region, not where you happen to be."])

    secret_cmd = None
    if backend:
        _header("Client Secret",
                ["Shown only once, when the service account was created.",
                 "It goes into the %s -- not into any config file." % backend])
        secret = _ask_hidden("  > (hidden, nothing echoes): ")
        if not secret:
            print("    (skipped -- no secret stored)")
        else:
            _store_secret(backend, secret)
            del secret
            back = _fetch_secret(fetch_argv)
            if not back:
                print("    ERROR: stored it but could not read it back.")
                print("    Not writing a PRISMA_SECRET_CMD that would fail at")
                print("    launch. Try: %s" % _quote(fetch_argv))
                return 1
            print("    stored and verified (length %d, value not printed)"
                  % len(back))
            secret_cmd = _quote(fetch_argv)

    entry = _panel_entry(client_id, tsg_id, region, secret_cmd)

    print("")
    print("-- Local MCP server entry --")
    print(json.dumps({"mcpServers": {SERVER_NAME: entry}}, indent=2))

    if print_only:
        print("")
        print("--print given: nothing was written. Paste the block above into")
        print("  %s" % _panel_config_path())
        return 0

    print("")
    target = _panel_config_path()
    rivals = [p for p in
              (os.path.join(d, "claude_desktop_config.json")
               for d in _panel_config_dirs())
              if os.path.exists(p) and p != target]
    if rivals:
        # Several Claude builds installed. Picking silently is how the entry
        # ends up in a file the running app never reads.
        print("More than one Claude config exists on this machine:")
        for p in rivals:
            print("    %s" % p)
        print("  Choosing the most recently modified one (the app in use).")
        print("  Override with PRISMA_PANEL_CONFIG=<path> if that is wrong.")
    print("Write this into %s ?" % target)
    try:
        answer = input("  [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        print("Not written. The block above is ready to paste by hand.")
        return 0

    try:
        path, action = _write_panel_config(entry)
    except Exception as exc:
        print("Could not write it: %s" % exc)
        print("Paste the block above by hand instead.")
        return 1

    print("%s %s" % (action, path))
    if action != "created":
        print("previous file kept as %s.bak" % path)
    print("")
    print("Restart the app, then ask it about your SASE tenant.")
    if not secret_cmd:
        print("NOTE: no secret is configured -- replace the placeholder in the")
        print("      panel, or re-run this once a keychain is available.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
