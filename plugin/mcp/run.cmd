@echo off
rem Launcher for the prisma-sase MCP server (Windows).
rem Mirrors mcp/run.sh: picks a Python >= 3.10, in order:
rem   1. %PRISMA_PYTHON%                       (explicit override, full path)
rem   2. %USERPROFILE%\.prisma-sase-venv\Scripts\python.exe   (install.bat venv)
rem   3. py -3.13 / -3.12 / -3.11 / -3.10      (python.org launcher)
rem   4. python                                 (PATH; server.py still guards the version)
rem
rem NOTE: a bare "python" that opens the Microsoft Store is the Store alias
rem stub -- install real Python from python.org or disable the alias
rem (Settings > Apps > Advanced app settings > App execution aliases).

set "DIR=%~dp0"
set "ARGS=%*"

if defined PRISMA_PYTHON call :try "%PRISMA_PYTHON%"
call :try "%USERPROFILE%\.prisma-sase-venv\Scripts\python.exe"
call :try py -3.13
call :try py -3.12
call :try py -3.11
call :try py -3.10
call :try python

echo ERROR: prisma-sase MCP server needs Python ^>= 3.10 and none was found. 1>&2
echo   Fix one of: 1>&2
echo    - run the plugin's install.bat (creates %%USERPROFILE%%\.prisma-sase-venv), or 1>&2
echo    - install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), or 1>&2
echo    - set PRISMA_PYTHON to the full path of a python.exe ^>= 3.10. 1>&2

rem Last resort (0.8.0 field report P1): serve the stdlib-only setup server
rem with any python available, so the failure reaches the conversation
rem instead of the tools silently not existing.
if "%ARGS%"=="" (
  for %%p in (python py) do (
    %%p -c "import sys" >nul 2>&1 && (
      %%p "%DIR%setup_server.py"
      exit /b %errorlevel%
    )
  )
)
exit /b 1

:try
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
%* "%DIR%server.py" %ARGS%
exit %errorlevel%
