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
    'config': w._panel_config_dirs()[0],
}))
"@
$g = & $py.Source -c $gen | ConvertFrom-Json
$blob = $g.blob

Write-Host "-- what the wizard reports on this machine --"
Write-Host "  backend      : $($g.backend)"
Write-Host "  config dir   : $($g.config)"
Write-Host "  panel PATH   : $($g.path)"
Write-Host ""

Write-Host "-- checks --"

Check "backend is dpapi" {
    if ($g.backend -eq 'dpapi') { $true }
    else { "got '$($g.backend)' -- is powershell.exe on PATH?" }
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
    $got = (& $cmdExe /c $g.cmd 2>&1 | Out-String).Trim()
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
        $got = (& $cmdExe /c $g.cmd 2>&1 | Out-String).Trim()
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
    $got = (& $cmdExe /c $strict 2>&1 | Out-String).Trim()
    if ($got -eq $secret) { $true }
    else { "blocked under Restricted -- got '$got'" }
}

Check "uvx is reachable via the PATH the wizard emits" {
    $saved = $env:PATH
    try {
        $env:PATH = $g.path
        $v = (& $cmdExe /c "uvx --version" 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0) { $true }
        else { "uvx not found on the emitted PATH: $v" }
    } finally { $env:PATH = $saved }
}

Check "git is reachable too (uvx needs it for the git+ ref)" {
    $saved = $env:PATH
    try {
        $env:PATH = $g.path
        $v = (& $cmdExe /c "git --version" 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -eq 0) { $true }
        else { "git not on the emitted PATH -- uvx cannot resolve the ref" }
    } finally { $env:PATH = $saved }
}

Check "the server launches and answers --selfcheck" {
    # Needs the network: uvx resolves the git ref on every launch. A failure
    # here on an offline VM is the network, not the code.
    $saved = $env:PATH
    try {
        $env:PATH = $g.path
        $out = (& $cmdExe /c "uvx --from git+https://github.com/eric2q/prisma-sase-plugin@uvx-local-mcp prisma-sase-mcp --selfcheck" 2>&1 | Out-String)
        if ($out -match "RESULT:") { $true }
        else { "no RESULT line:`n$($out.Trim())" }
    } finally { $env:PATH = $saved }
}

# --- clean up -------------------------------------------------------------

Remove-Item -LiteralPath $tempBase -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($script:failed -eq 0) {
    Write-Host "all checks passed" -ForegroundColor Green
    Write-Host ""
    Write-Host "The Windows secret path works. Next: run the real thing --"
    Write-Host "  uvx --from git+https://github.com/eric2q/prisma-sase-plugin@uvx-local-mcp prisma-sase-setup"
    Write-Host "then restart the app and ask it to run get_sase_status."
    exit 0
} else {
    Write-Host "$($script:failed) check(s) failed" -ForegroundColor Red
    exit 1
}
