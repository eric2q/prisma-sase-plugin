<#
    Verify the Windows secret path on a real Windows machine.

    The DPAPI backend in setup_wizard.py was written on macOS. Everything in
    tools/test-regressions.py that covers it runs against a patched
    platform.system(), so those tests pin the *shape* of what gets emitted --
    that the quoting suits cmd.exe, that the secret never reaches a command
    line -- and cannot tell you whether the PowerShell actually round-trips a
    secret through DPAPI. Only Windows can answer that.

    Run this in a Windows VM:

        powershell -ExecutionPolicy Bypass -File tools\verify-windows.ps1

    It uses a throwaway blob path and its own service name, so it will not
    touch a secret you already stored. Nothing is written outside $env:TEMP.

    Exit code 0 means every check passed.
#>

$ErrorActionPreference = 'Stop'
$script:failed = 0

function Check($name, [scriptblock]$body) {
    Write-Host -NoNewline ("  {0,-52}" -f $name)
    try {
        $result = & $body
        if ($result -eq $true) { Write-Host "PASS" -ForegroundColor Green }
        else {
            Write-Host "FAIL" -ForegroundColor Red
            if ($result) { Write-Host "        $result" -ForegroundColor Red }
            $script:failed++
        }
    } catch {
        Write-Host "ERROR" -ForegroundColor Red
        Write-Host "        $_" -ForegroundColor Red
        $script:failed++
    }
}

Write-Host ""
Write-Host "== prisma-sase Windows verification =="
Write-Host ""

# --- what we are testing against -----------------------------------------

# No ?? here: this has to run under Windows PowerShell 5.1, which is what
# ships with Windows. Null-coalescing is 7.0+.
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { throw "python not on PATH -- install it or add it" }

$repo = Split-Path -Parent $PSScriptRoot
$tempBase = Join-Path $env:TEMP "prisma-sase-verify"
$secret = "test-secret-" + [guid]::NewGuid().ToString("N").Substring(0, 12)

# Absolute, because several checks run with PATH emptied to prove the launch
# path does not depend on inheriting one.
$cmdExe = Join-Path $env:SystemRoot "System32\cmd.exe"

function RunCmd($commandLine) {
    <#
        Run a command line through cmd.exe and return everything it printed.

        The $ErrorActionPreference='Stop' at the top of this script is right for
        the checks themselves but wrong here. Windows PowerShell 5.1 turns a
        native command's stderr into ErrorRecords when it is redirected with
        2>&1, and under 'Stop' the first one throws. Plenty of well-behaved
        tools write progress to stderr -- uv announces every package it builds
        there -- so without this a check aborts on a status line and reports it
        as though it were the failure.
    #>
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { (& $cmdExe /c $commandLine 2>&1 | Out-String) }
    finally { $ErrorActionPreference = $saved }
}

Write-Host "  python : $($py.Source)"
Write-Host "  repo   : $repo"
Write-Host "  temp   : $tempBase  (throwaway LOCALAPPDATA)"
Write-Host ""

# Ask the wizard itself for the scripts, so this verifies the shipped code
# rather than a copy of it that could drift.
#
# LOCALAPPDATA is redirected at a throwaway directory first. _backend() builds
# its fetch command from _dpapi_blob_path(), so without this the command under
# test would point at the real blob while store/fetch used the temp one -- the
# two would disagree and the failure would look like a cmd.exe problem.
$gen = @"
import sys, os, json
os.environ['LOCALAPPDATA'] = r'$tempBase'
sys.path.insert(0, r'$repo\src')
from prisma_sase_mcp import setup_wizard as w
blob = w._dpapi_blob_path()
print(json.dumps({
    'blob': blob,
    'store': w._dpapi_store_script(blob),
    'fetch': w._dpapi_fetch_script(blob),
    'backend': w._backend()[0],
    'cmd': w._quote(w._backend()[1]) if w._backend()[0] == 'dpapi' else '',
    'path': w._panel_path(),
    'uvxargs': ' '.join(w._uvx_args()),
    'machine': w.platform.machine(),
    'pathext': w._panel_entry('c', '1', 'sg', None)['env'].get('PATHEXT', ''),
}))
"@
$g = & $py.Source -c $gen | ConvertFrom-Json
$blob = $g.blob

# Asked separately, and deliberately so: the block above redirects LOCALAPPDATA
# to a temp directory to keep the DPAPI blob out of the real one, and the panel
# search reads LOCALAPPDATA too. Sharing that process would have the search look
# in the temp tree and find nothing, every time, on every machine.
#
# It reports what *exists*, not what would be computed. The computed path was
# all this script printed before, and it printed Roaming\Claude on a machine
# whose only config was in Local -- a wrong answer that eleven green checks
# said nothing about, because none of them ever looked at the disk.
$scan = @"
import sys, os, json
sys.path.insert(0, r'$repo\src')
from prisma_sase_mcp import setup_wizard as w
print(json.dumps({
    'dirs': w._panel_config_dirs(),
    'found': w._existing_panel_configs(),
    'target': w._panel_config_path(),
    'flavours': [w._flavour(p) for p in w._existing_panel_configs()],
}))
"@
$c = & $py.Source -c $scan | ConvertFrom-Json

Write-Host "-- what the wizard reports on this machine --"
# platform.machine(), not $env:PROCESSOR_ARCHITECTURE. The two differ on ARM
# Windows: the env var gives the *process* architecture and reads AMD64 inside
# an emulated x64 shell, while platform.machine() prefers PROCESSOR_ARCHITEW6432
# and so reports the real machine. The code branches on the latter, so that is
# what has to be shown here -- printing the other one told us nothing.
Write-Host "  backend      : $($g.backend)"
Write-Host "  machine      : $($g.machine)   (process: $env:PROCESSOR_ARCHITECTURE)"
Write-Host "  uvx args     : $($g.uvxargs)"
Write-Host "  panel PATH   : $($g.path)"
if ($c.found) {
    for ($i = 0; $i -lt $c.found.Count; $i++) {
        $label = if ($i -eq 0) { "  configs found:" } else { "                " }
        Write-Host "$label $($c.found[$i])  [$($c.flavours[$i])]"
    }
    # Deliberately not "would write". With more than one build installed the
    # wizard asks rather than picks -- both are real installs ("-3p" is the
    # custom-gateway build, unsuffixed is subscription) and only the user
    # knows which they work in. Printing a single path here read as though
    # the choice had already been made, and made wrongly.
    if ($c.found.Count -gt 1) {
        Write-Host "                 -> more than one build: the wizard will ask which"
    } else {
        Write-Host "  would write  : $($c.target)"
    }
} else {
    Write-Host "  configs found: (none) -- would create $($c.target)"
}
Write-Host ""

Write-Host "-- checks --"

Check "backend is dpapi" {
    if ($g.backend -eq 'dpapi') { $true }
    else { "got '$($g.backend)' -- is powershell.exe on PATH?" }
}

Check "the wizard can see every config on this machine" {
    # Independent of the wizard: walk AppData directly and compare. Asking the
    # wizard whether it found everything would only ever confirm its own view,
    # which is exactly how a Local-only install stayed invisible while every
    # check passed.
    #
    # A miss here is the silent one -- the wizard writes to a file no running
    # app reads, reports success, and no tools appear with nothing to explain
    # why -- so it fails rather than warns.
    $real = @()
    foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
        if (-not $base) { continue }
        Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq 'Claude' -or $_.Name -like 'Claude-*' } |
            ForEach-Object {
                $f = Join-Path $_.FullName 'claude_desktop_config.json'
                if (Test-Path -LiteralPath $f) { $real += $f }
            }
    }
    if (-not $real) {
        Write-Host -NoNewline "(no Claude config on this machine) "
        return $true
    }
    # -notin needs PowerShell 3+, which is fine, but -contains on the left
    # reads the same and matches the 5.1 style used elsewhere here.
    $missed = @($real | Where-Object { -not ($c.found -contains $_) })
    if (-not $missed) {
        Write-Host -NoNewline "($($real.Count) found) "
        $true
    } else {
        ("the wizard does not search where these live:`n  " +
         ($missed -join "`n  ") +
         "`nit would write to $($c.target) instead, which the running app " +
         "may never read")
    }
}

Check "store script encrypts a secret" {
    $secret | & powershell -NoProfile -NonInteractive -Command $g.store
    if (Test-Path $blob) { $true } else { "no blob at $blob" }
}

Check "the blob on disk is not the plaintext secret" {
    $raw = Get-Content -LiteralPath $blob -Raw
    if ($raw -notmatch [regex]::Escape($secret)) { $true }
    else { "the secret is readable in the file" }
}

Check "fetch script returns exactly what was stored" {
    $got = & powershell -NoProfile -NonInteractive -Command $g.fetch
    if ($got -eq $secret) { $true }
    else { "round-trip mismatch (lengths $($got.Length) vs $($secret.Length))" }
}

Check "the command survives cmd.exe verbatim" {
    # The real launch path: config.py runs PRISMA_SECRET_CMD with shell=True,
    # which on Windows is cmd.exe. This is the check the macOS tests cannot do.
    $got = (RunCmd $g.cmd).Trim()
    if ($got -eq $secret) { $true }
    else { "cmd.exe mangled it -- got '$got'" }
}

Check "it works with no PATH inherited" {
    # The app does not give MCP servers a login shell's environment, so the
    # command has to stand on its own. cmd.exe is invoked by absolute path
    # here for the same reason -- with PATH empty, nothing is on it.
    $saved = $env:PATH
    try {
        $env:PATH = ""
        $got = (RunCmd $g.cmd).Trim()
        if ($got -eq $secret) { $true }
        else { "failed with an empty PATH -- got '$got'" }
    } finally { $env:PATH = $saved }
}

Check "a restrictive execution policy does not block it" {
    # This script runs under -ExecutionPolicy Bypass, so the ambient policy
    # proves nothing. Force the strictest one onto the child process instead:
    # policy governs script *files*, and the fetch uses -Command, so it should
    # survive. An enterprise GPO setting AllSigned is the case being modelled.
    $strict = $g.cmd -replace '(?i)-NoProfile', '-ExecutionPolicy Restricted -NoProfile'
    if ($strict -eq $g.cmd) { return "could not inject a policy flag" }
    $got = (RunCmd $strict).Trim()
    if ($got -eq $secret) { $true }
    else { "blocked under Restricted -- got '$got'" }
}

Check "uvx is reachable via the PATH the wizard emits" {
    $saved = $env:PATH
    try {
        $env:PATH = $g.path
        $v = (RunCmd "uvx --version").Trim()
        if ($LASTEXITCODE -eq 0) { $true }
        else { "uvx not found on the emitted PATH: $v" }
    } finally { $env:PATH = $saved }
}

Check "git is reachable too (uvx needs it for the git+ ref)" {
    $saved = $env:PATH
    try {
        $env:PATH = $g.path
        $v = (RunCmd "git --version").Trim()
        if ($LASTEXITCODE -eq 0) { $true }
        else { "git not on the emitted PATH -- uvx cannot resolve the ref" }
    } finally { $env:PATH = $saved }
}

Check "git is still reachable with only the vars the host passes" {
    # The check above passes with a broken config, and did. It swaps PATH and
    # leaves everything else inherited -- including PATHEXT, which the host
    # does *not* pass on. Claude hands the child a fixed allow-list (APPDATA,
    # HOMEDRIVE, HOMEPATH, LOCALAPPDATA, PATH, PROCESSOR_ARCHITECTURE,
    # SYSTEMDRIVE, SYSTEMROOT, TEMP, USERNAME, USERPROFILE, PROGRAMFILES)
    # merged with the entry's own env, and PATHEXT is not on it.
    #
    # Absent PATHEXT, Windows appends nothing when resolving a bare name, so
    # "git" is looked up literally and never matches git.exe. uv then reports
    # "Git executable not found. Ensure that Git is installed and available"
    # on a machine where git is installed and on PATH -- which reads as a PATH
    # problem and is not one.
    #
    # So this runs git in a *child* whose environment is built from the
    # allow-list plus the entry's env, and nothing else.
    $allow = @('APPDATA', 'HOMEDRIVE', 'HOMEPATH', 'LOCALAPPDATA',
               'PROCESSOR_ARCHITECTURE', 'SYSTEMDRIVE', 'SYSTEMROOT',
               'TEMP', 'USERNAME', 'USERPROFILE', 'PROGRAMFILES')
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $cmdExe
    $psi.Arguments = '/c git --version'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.EnvironmentVariables.Clear()
    foreach ($n in $allow) {
        $v = [Environment]::GetEnvironmentVariable($n)
        if ($v) { $psi.EnvironmentVariables[$n] = $v }
    }
    # Exactly what the wizard writes, no more.
    $psi.EnvironmentVariables['PATH'] = $g.path
    if ($g.pathext) { $psi.EnvironmentVariables['PATHEXT'] = $g.pathext }

    $p = [Diagnostics.Process]::Start($psi)
    $out = $p.StandardOutput.ReadToEnd() + $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    if ($p.ExitCode -eq 0) { $true }
    elseif (-not $g.pathext) {
        "the entry sets no PATHEXT, so git.exe is invisible to uvx even " +
        "though PATH is right. uv will say `"Git executable not found`"."
    } else {
        "git did not run under the host's environment:`n$($out.Trim())"
    }
}

Check "the interpreter uvx resolves is one with wheels" {
    # A green --selfcheck does not prove the ARM64 branch worked: uv caches, so
    # a run that compiled cryptography once will pass instantly ever after, and
    # look identical to a run that never needed to. Ask the resolved interpreter
    # what it is instead. On ARM64 this must come back x86, because that is the
    # whole point -- win_amd64 wheels exist and win_arm64 ones do not.
    #
    # sysconfig.get_platform(), not platform.machine(). On Windows the latter is
    # literally PROCESSOR_ARCHITEW6432 or PROCESSOR_ARCHITECTURE -- it describes
    # the machine, and answers ARM64 even from an x64 interpreter, which is the
    # very property relied on to detect ARM64 in the first place. The former is
    # baked in when the interpreter is built and is what pip matches wheels
    # against, so it is the thing that actually decides whether cryptography
    # arrives as a wheel or as a source build.
    $saved = $env:PATH
    try {
        $env:PATH = $g.path
        # The probe goes in a file rather than after -c. Inline, it would be a
        # Python string inside a cmd.exe argument inside a PowerShell string,
        # and the escaping needed at each layer differs -- PowerShell wants a
        # backtick where C and sh want a backslash. A file has no inner quotes
        # at all, so no layer has anything to mangle.
        # The store script creates $tempBase\prisma-sase, not $tempBase itself,
        # and this check must not depend on an earlier one having run.
        New-Item -ItemType Directory -Force -Path $tempBase | Out-Null
        $probe = Join-Path $tempBase "probe.py"
        Set-Content -LiteralPath $probe -Encoding ascii -Value @(
            "import sysconfig"
            "print('TARGET=' + sysconfig.get_platform())"
        )

        # Everything the wizard passes uvx except the package itself. `uv run`
        # resolves an interpreter by the same rules and needs no package, so it
        # answers the question without installing anything.
        $sel = $g.uvxargs -replace ' --from .*$', ''
        # A here-string: literal double quotes need no escaping inside one,
        # which is the whole reason for using it here.
        $line = @"
uv run $sel python "$probe"
"@
        $out = RunCmd $line.Trim()
        if ($out -notmatch 'TARGET=(\S+)') { return "no answer from the interpreter:`n$($out.Trim())" }
        $got = $Matches[1]
        Write-Host -NoNewline "($got) "

        if ($g.machine -match '(?i)arm|aarch') {
            if ($got -match '(?i)amd64|x86') { $true }
            else { "resolved a $got interpreter -- no cryptography wheel is published for it, so it would be built from source" }
        } else {
            Write-Host -NoNewline "(n/a on $($g.machine)) "
            $true
        }
    } finally { $env:PATH = $saved }
}

Check "the server launches and answers --selfcheck" {
    # Launched with the arguments the wizard itself would write, rather than a
    # copy of them -- on ARM64 those include an x64 interpreter, and hardcoding
    # the command here would test a launch nobody performs.
    #
    # Needs the network: uvx resolves the git ref on every launch. A failure
    # here on an offline VM is the network, not the code.
    #
    # The first run on a machine can take minutes rather than seconds, because
    # uv has to populate an empty cache. Later runs hit it and are quick.
    $saved = $env:PATH
    try {
        $env:PATH = $g.path
        # The branch under test, in place of the main this would ship pointing at.
        # Not $args -- that is an automatic variable in PowerShell.
        $uvxArgs = $g.uvxargs -replace 'prisma-sase-plugin ', 'prisma-sase-plugin@uvx-local-mcp '
        $out = RunCmd "uvx $uvxArgs --selfcheck"
        if ($out -match "RESULT:") { return $true }

        # Name the failure that is about this machine rather than about the
        # code, so it does not get mistaken for a defect in the server.
        if ($out -match "(?i)cargo|rust|Microsoft Visual C\+\+|vcvars|error: linker") {
            return ("a transitive dependency had no prebuilt wheel for " +
                    "$env:PROCESSOR_ARCHITECTURE and the source build failed. " +
                    "See the Windows on ARM note in plugin/README.md.`n$($out.Trim())")
        }
        "no RESULT line:`n$($out.Trim())"
    } finally { $env:PATH = $saved }
}

# --- clean up -------------------------------------------------------------

Remove-Item -LiteralPath $tempBase -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($script:failed -eq 0) {
    Write-Host "all checks passed" -ForegroundColor Green
    Write-Host ""
    Write-Host "The Windows secret path works. Next: run the real thing --"
    # Built from the wizard's own args, not typed out. prisma-sase-setup lives in
    # the same package as the server, so uvx installs the same dependency set for
    # it -- cryptography included. On ARM64 a bare command would hit the missing
    # win_arm64 wheel here, at the very first thing the user runs, before the
    # wizard exists to fix anything.
    $setupArgs = ($g.uvxargs `
        -replace 'prisma-sase-plugin ', 'prisma-sase-plugin@uvx-local-mcp ' `
        -replace 'prisma-sase-mcp$', 'prisma-sase-setup')
    Write-Host "  uvx $setupArgs"
    Write-Host "then restart the app and ask it to run get_sase_status."
    exit 0
} else {
    Write-Host "$($script:failed) check(s) failed" -ForegroundColor Red
    exit 1
}
