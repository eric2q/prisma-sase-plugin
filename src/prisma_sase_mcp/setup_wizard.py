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

def _ps_exe():
    """Windows PowerShell, or PowerShell 7 if that is all there is.

    powershell.exe ships with every supported Windows; pwsh is the optional
    modern one. Either can do DPAPI, so prefer the one guaranteed present.
    """
    return shutil.which("powershell") or shutil.which("pwsh")


def _ps_quote(s):
    """Quote a string as a PowerShell single-quoted literal.

    Inside single quotes PowerShell expands nothing -- no $variable, no
    backtick escapes -- so a Windows path with backslashes survives as typed.
    The one character that needs care is the quote itself, which is escaped by
    doubling.
    """
    return "'" + s.replace("'", "''") + "'"


def _dpapi_blob_path():
    """Where the DPAPI-encrypted secret is kept on Windows.

    LOCALAPPDATA rather than APPDATA: the blob is decryptable only by this
    user on this machine, so roaming it to another machine would just produce
    a file that cannot be read.
    """
    import ntpath          # os.path is posixpath when simulating Windows
    base = os.environ.get("LOCALAPPDATA") or ntpath.join(
        os.path.expanduser("~"), "AppData", "Local")
    return ntpath.join(base, "prisma-sase", "client_secret.bin")


def _dpapi_fetch_script(blob):
    """PowerShell that prints the decrypted secret to stdout.

    This ends up inside PRISMA_SECRET_CMD, which config.py runs with
    shell=True -- cmd.exe on Windows. Two consequences shape it:

      * It is passed with -Command, not -File. Execution policy applies only
        to script *files*, so an inline command still runs under the AllSigned
        or Restricted policy an enterprise GPO is likely to impose.
      * It must contain no double quote and no '%'. cmd.exe strips the former
        and expands the latter even inside a quoted argument. Single-quoted
        PowerShell literals keep both out.
    """
    return (
        "$ErrorActionPreference='Stop';"
        "$b=Get-Content -LiteralPath %s -Raw;"
        "$s=ConvertTo-SecureString $b.Trim();"
        "[Runtime.InteropServices.Marshal]::PtrToStringBSTR("
        "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))"
        % _ps_quote(blob)
    )


def _dpapi_store_script(blob):
    """PowerShell that reads the secret from stdin and writes it encrypted.

    stdin, not an argument: anything on a command line is visible to every
    process running as this user via the process list.

    ConvertFrom-SecureString with no -Key encrypts with DPAPI under the
    current user's key, so the file on disk is useless to another account and
    useless on another machine -- which is the property we want from a thing
    that has to sit in the filesystem at all.
    """
    return (
        "$ErrorActionPreference='Stop';"
        "$p=%s;"
        "New-Item -ItemType Directory -Force -Path (Split-Path -Parent $p)"
        " | Out-Null;"
        "$s=[Console]::In.ReadLine();"
        "ConvertTo-SecureString $s -AsPlainText -Force"
        " | ConvertFrom-SecureString"
        " | Set-Content -LiteralPath $p -Encoding ascii"
        % _ps_quote(blob)
    )


def _backend():
    """Pick a secret store. Returns (name, fetch_argv) or (None, None)."""
    if platform.system() == "Darwin" and shutil.which("security"):
        return "keychain", ["security", "find-generic-password",
                            "-s", SERVICE, "-a", ACCOUNT, "-w"]
    if platform.system() == "Windows" and _ps_exe():
        # No Windows equivalent of `security` exists: cmdkey stores into
        # Credential Manager but will not print a password back, so it cannot
        # serve as a fetch command. DPAPI is the built-in primitive underneath
        # Credential Manager anyway, and PowerShell exposes it directly.
        return "dpapi", [_ps_exe(), "-NoProfile", "-NonInteractive",
                         "-Command", _dpapi_fetch_script(_dpapi_blob_path())]
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
    elif backend == "dpapi":
        subprocess.run([_ps_exe(), "-NoProfile", "-NonInteractive",
                        "-Command", _dpapi_store_script(_dpapi_blob_path())],
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
    """Render argv as the single shell string PRISMA_SECRET_CMD expects.

    config.py runs that string with shell=True, so the quoting has to match
    whichever shell will receive it. shlex.quote speaks POSIX sh and its
    single quotes are literal characters to cmd.exe, which would hand
    PowerShell an argument beginning with a stray quote.

    cmd.exe has only double quotes, and no escape for a double quote inside
    them. The callers above avoid producing one -- the PowerShell scripts are
    written with single-quoted literals for exactly this reason -- so wrapping
    is enough. An embedded double quote would be unrepresentable, so refuse
    rather than emit a command that fails at launch with no clue why.

    Anything containing a cmd.exe metacharacter is quoted, not just anything
    containing a space: `&`, `|` and `<>` split a command line without needing
    one. `%` is refused outright, since cmd.exe expands %VAR% even inside
    double quotes and there is no way to escape it from here.
    """
    if platform.system() == "Windows":
        out = []
        for a in argv:
            if '"' in a:
                raise ValueError(
                    "cannot express %r in a cmd.exe command line" % a)
            if "%" in a:
                raise ValueError(
                    "cmd.exe would expand %% in %r and cannot be stopped" % a)
            out.append('"%s"' % a
                       if any(c in a for c in ' \t&|<>^()')
                       else a)
        return " ".join(out)
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

    Nor is the parent directory fixed on Windows. Electron's app.getPath
    ('userData') resolves to %APPDATA% (Roaming), which is where the standard
    build keeps its config; a Claude-3p install was found in the field under
    %LOCALAPPDATA% instead. Both are searched, because guessing one and
    missing produces exactly the silent failure above.
    """
    home = os.path.expanduser("~")
    if platform.system() == "Darwin":
        bases = [os.path.join(home, "Library", "Application Support")]
    elif platform.system() == "Windows":
        import ntpath      # os.path is posixpath when simulating Windows
        bases = [os.environ.get("APPDATA")
                 or ntpath.join(home, "AppData", "Roaming"),
                 os.environ.get("LOCALAPPDATA")
                 or ntpath.join(home, "AppData", "Local")]
    else:
        bases = [os.path.join(home, ".config")]

    dirs = [os.path.join(bases[0], "Claude")]
    for base in bases:
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            # "Claude" only from a non-primary base -- the primary one is
            # already first in the list, and it must stay first: it is the
            # default written on a machine with no config at all.
            if name == "Claude" or name.startswith("Claude-"):
                d = os.path.join(base, name)
                if d not in dirs:
                    dirs.append(d)
    return dirs


def _existing_panel_configs():
    """Config files that actually exist, most recently modified first."""
    candidates = [os.path.join(d, "claude_desktop_config.json")
                  for d in _panel_config_dirs()]
    return sorted((p for p in candidates if os.path.exists(p)),
                  key=os.path.getmtime, reverse=True)


def _panel_config_path():
    """The file to write when nobody is around to be asked.

    PRISMA_PANEL_CONFIG wins outright. Otherwise the most recently modified
    existing config (the app most likely in use), or the plain "Claude" path
    on a machine that has none yet. `_choose_panel_config` asks instead when
    there is a terminal and the answer is not obvious.
    """
    override = os.environ.get("PRISMA_PANEL_CONFIG")
    if override:
        return os.path.expanduser(override)
    existing = _existing_panel_configs()
    if existing:
        return existing[0]
    return os.path.join(_panel_config_dirs()[0], "claude_desktop_config.json")


def _flavour(path):
    """Which Claude build a config belongs to, from its directory name.

    A "-3p" suffix means the custom-gateway build; the unsuffixed directory is
    the subscription one. Both are legitimate installs and a machine can have
    both, so this is not a case of one being right -- it is the fact the user
    needs in order to answer which of the two they want configured. Without
    it the prompt lists two indistinguishable paths.
    """
    parent = os.path.basename(os.path.dirname(path))
    if parent.endswith("-3p"):
        return "custom gateway"
    if parent == "Claude":
        return "subscription"
    return parent


def _describe_config(path):
    """A one-line hint of what lives in a config, to tell two apart.

    Server names only -- never a value. A config that will not parse is worth
    saying so about: it is the one _write_panel_config will refuse.

    The build comes first because it is the part that decides the answer. Two
    fresh installs both hold zero servers, so on the machine this matters most
    the server list distinguishes nothing at all.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return "%s -- unreadable / not valid JSON" % _flavour(path)
    names = list((data.get("mcpServers") or {}).keys())
    if not names:
        return "%s -- no MCP servers yet" % _flavour(path)
    shown = ", ".join(names[:4])
    return "%s -- servers: %s%s" % (_flavour(path), shown,
                                    ", ..." if len(names) > 4 else "")


def _choose_panel_config():
    """Ask which config to write when the machine has more than one.

    Several Claude builds can be installed side by side, each with its own
    directory (Claude, Claude-3p, ...). Only the running one reads its file,
    and picking wrong is invisible: the write succeeds, the entry looks
    perfect, and no tools ever appear. So when the answer is not forced, ask.
    """
    override = os.environ.get("PRISMA_PANEL_CONFIG")
    if override:
        path = os.path.expanduser(override)
        print("\nUsing PRISMA_PANEL_CONFIG: %s" % path)
        return path

    existing = _existing_panel_configs()
    if not existing:
        return os.path.join(_panel_config_dirs()[0],
                            "claude_desktop_config.json")
    if len(existing) == 1:
        return existing[0]

    print("")
    print("  More than one Claude build is installed on this machine.")
    print("  Each reads only its own config -- writing to the other one looks")
    print("  like it worked and produces no tools.")
    print("")
    for i, p in enumerate(existing, 1):
        print("    %d) %s" % (i, p))
        print("       %s" % _describe_config(p))
    print("")
    # Not "the most recent is usually the one in use". Both builds are real
    # installs -- "-3p" is the custom-gateway one, unsuffixed is subscription
    # -- and which to configure is a choice about which you work in, not
    # something a timestamp can answer. Ordering still puts the recently
    # touched one first; that is a tiebreak, not a recommendation.
    print("  Pick the build you actually use. Both are ordinary installs;")
    print("  you can re-run this later for the other one.")

    while True:
        try:
            answer = input("  > which one? [1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            # No terminal (piped stdin): fall back rather than die, but say
            # which was picked so a wrong guess is visible.
            print("\n  no answer available -- defaulting to %s" % existing[0])
            return existing[0]
        if not answer:
            return existing[0]
        if answer.isdigit() and 1 <= int(answer) <= len(existing):
            return existing[int(answer) - 1]
        print("    (enter 1-%d)" % len(existing))


def _uvx_path():
    return shutil.which("uvx") or "uvx"


def _panel_path():
    """A PATH for the server process, since the app does not supply one.

    `command` is absolute, so this is not about finding uvx -- it is about
    what uvx itself then needs: git, to resolve the ref, and the interpreter
    it installs. Built around the directory uvx was actually found in, so a
    non-standard install location works without anyone editing this list.
    """
    found = shutil.which("uvx")
    here = [os.path.dirname(found)] if found else []
    home = os.path.expanduser("~")
    if platform.system() == "Windows":
        # ntpath rather than os.path: os.path is posixpath when this runs
        # anywhere but Windows, and would join these with forward slashes.
        import ntpath
        sysroot = os.environ.get("SystemRoot", r"C:\Windows")
        usual = [ntpath.join(home, ".local", "bin"),
                 r"C:\Program Files\Git\cmd",
                 ntpath.join(sysroot, "System32"),
                 sysroot]
        sep = ";"
    else:
        # ~/.local/bin is where the official uv installer puts things;
        # /opt/homebrew/bin is Apple silicon, /usr/local/bin Intel and the
        # common Linux prefix.
        usual = [os.path.join(home, ".local", "bin"), "/opt/homebrew/bin",
                 "/usr/local/bin", "/usr/bin", "/bin"]
        sep = ":"
    ordered = []
    for d in here + usual:
        if d and d not in ordered:
            ordered.append(d)
    return sep.join(ordered)


def _uvx_args():
    """The arguments for uvx, with an interpreter named only where it matters.

    Normally uv picks the interpreter and picking it for uv would be rude. ARM64
    Windows is the exception. `cryptography` arrives transitively (fastmcp ->
    mcp -> pyjwt[crypto]) and publishes no win_arm64 wheel for the current
    version, so a native interpreter sends uv off to build it from source --
    which needs Rust and MSVC, and without them the launch dies with a cargo
    error that says nothing about this plugin.

    An x64 interpreter avoids all of it: Windows on ARM emulates x64, the
    win_amd64 wheels exist, nothing is compiled. uv publishes no ARM64 Windows
    build in the first place, so asking for a managed Python here can only
    return x64 anyway -- naming it just makes that explicit instead of leaving
    it to whatever happens to be on PATH.
    """
    args = []
    if (platform.system() == "Windows"
            and platform.machine().lower() in ("arm64", "aarch64")):
        args += ["--managed-python", "--python", "cpython-3.12-windows-x86_64"]
    return args + ["--from", GIT_URL, "prisma-sase-mcp"]


def _panel_entry(client_id, tsg_id, region, secret_cmd):
    """The block the user pastes -- or that we write for them."""
    env = {
        "PATH": _panel_path(),
        "PRISMA_CLIENT_ID": client_id,
        "PRISMA_TSG_ID": tsg_id,
        "PRISMA_REGION": region,
    }
    if secret_cmd:
        env["PRISMA_SECRET_CMD"] = secret_cmd
    else:
        env["PRISMA_CLIENT_SECRET"] = "<paste your client secret here>"
    return {
        "command": _uvx_path(),
        "args": _uvx_args(),
        "env": env,
    }


def _write_panel_config(entry, path=None):
    """Merge the entry into claude_desktop_config.json, backing it up first.

    Returns (path, action) where action is 'created' | 'updated' | 'added'.
    """
    path = path or _panel_config_path()
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
        existing = _existing_panel_configs()
        if not existing:
            print("panel config   : %s (does not exist)"
                  % _panel_config_path())
        for i, p in enumerate(existing):
            print("%s: %s" % ("panel config   " if i == 0
                              else "  also present ", p))
            print("                 %s" % _describe_config(p))
        if len(existing) > 1:
            print("  (setup will ask which of these to write)")
        return 0

    print(BANNER)
    if backend:
        print("  secret store: %s" % backend)
    else:
        print("  secret store: NONE FOUND -- the secret will have to go into")
        print("  the panel in plaintext.")
        if platform.system() == "Windows":
            print("  (expected powershell.exe on PATH and did not find it)")
        elif platform.system() != "Darwin":
            print("  Install one: apt install libsecret-tools  (or `pass`)")

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
        existing = _existing_panel_configs()
        if len(existing) > 1:
            print("  one of these -- whichever app you actually run:")
            for p in existing:
                print("    %s" % p)
        else:
            print("  %s" % _panel_config_path())
        return 0

    target = _choose_panel_config()

    print("")
    print("Write this into %s ?" % target)
    try:
        answer = input("  [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = ""
    if answer not in ("y", "yes"):
        print("Not written. The block above is ready to paste by hand.")
        return 0

    try:
        path, action = _write_panel_config(entry, target)
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
