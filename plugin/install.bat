@echo off
rem One-shot setup for the prisma-sase MCP server (Windows).
rem Mirrors install.sh:
rem   1. Finds a Python >= 3.10 (py launcher or python on PATH).
rem   2. Creates a venv at %USERPROFILE%\.prisma-sase-venv (override: PRISMA_VENV).
rem   3. Installs mcp\requirements.txt into it.
rem   4. Creates the %USERPROFILE%\.prisma-sase.env credential template.
rem   5. Runs a mock-mode selfcheck to prove the server starts.

setlocal
set "DIR=%~dp0"
if defined PRISMA_VENV (set "VENV=%PRISMA_VENV%") else (set "VENV=%USERPROFILE%\.prisma-sase-venv")

echo == prisma-sase install (Windows) ==

rem -- 1) find a suitable python -------------------------------------------
set "PYCMD="
call :find py -3.13
call :find py -3.12
call :find py -3.11
call :find py -3.10
call :find python
if not defined PYCMD (
  echo ERROR: no Python ^>= 3.10 found. 1>&2
  echo   Install from https://www.python.org/downloads/ and tick "Add python.exe to PATH". 1>&2
  echo   If "python" opens the Microsoft Store, that is the Store alias stub -- 1>&2
  echo   install real Python or disable the alias in App execution aliases. 1>&2
  exit /b 1
)
echo -- using: %PYCMD%

rem -- 2) venv --------------------------------------------------------------
if not exist "%VENV%\Scripts\python.exe" (
  echo -- creating venv at %VENV%
  %PYCMD% -m venv "%VENV%" || exit /b 1
) else (
  echo -- reusing existing venv at %VENV%
)

rem -- 3) dependencies ------------------------------------------------------
echo -- installing dependencies (fastmcp, httpx)
"%VENV%\Scripts\python.exe" -m pip install --quiet --upgrade pip || exit /b 1
"%VENV%\Scripts\python.exe" -m pip install --quiet -r "%DIR%mcp\requirements.txt" || exit /b 1

rem -- 4) credential template ----------------------------------------------
set "ENVF=%USERPROFILE%\.prisma-sase.env"
if not exist "%ENVF%" (
  (
    echo # prisma-sase credentials -- fill in the values below ^(KEY=VALUE, no quotes needed^).
    echo # This file is the recommended way to provide credentials.
    echo PRISMA_CLIENT_ID=
    echo PRISMA_CLIENT_SECRET=
    echo PRISMA_TSG_ID=
    echo PRISMA_REGION=sg
  ) > "%ENVF%"
  echo -- created credential template %ENVF% -- fill in your values
) else (
  echo -- keeping existing %ENVF%
)

rem -- 5) selfcheck (offline, no credentials needed) ------------------------
echo -- running selfcheck (mock mode)
set "PRISMA_MOCK=1"
"%VENV%\Scripts\python.exe" "%DIR%mcp\server.py" --selfcheck
set "PRISMA_MOCK="

echo.
echo == install complete ==
echo venv python : %VENV%\Scripts\python.exe
echo next steps  :
echo   1. Fill in your read-only service-account values in %ENVF%
echo   2. In Claude Desktop: Settings ^> Plugins ^> Upload from file
echo      -- upload prisma-sase-windows.plugin (the Windows variant).
echo      (mcp\run.cmd finds this venv automatically -- no config edits needed.)
echo   3. Verify:  "%VENV%\Scripts\python.exe" "%DIR%mcp\server.py" --selfcheck
echo   4. First run against a new tenant: ask Claude to run discover_insights
exit /b 0

:find
if defined PYCMD goto :eof
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
set "PYCMD=%*"
goto :eof
