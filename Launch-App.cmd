@echo off
setlocal
rem Clear any inherited PYTHONPATH that could shadow the stdlib.
set "PYTHONPATH="
rem Fix PYTHONHOME: a stray or empty PYTHONHOME makes venv\Scripts\python.exe
rem fail with "No module named 'encodings'". The venv itself has no Lib\encodings;
rem the stdlib lives in the base Python dir recorded in venv\pyvenv.cfg ("home").
rem Point PYTHONHOME there so the venv interpreter can find its stdlib.
set "PYHOME="
for /f "tokens=1,* delims==" %%A in ('findstr /i "^home" "%~dp0venv\pyvenv.cfg"') do (
    set "PYHOME=%%B"
)
if defined PYHOME (
    set "PYTHONHOME=%PYHOME: =%"
) else (
    set "PYTHONHOME="
)

rem ============================================================
rem First-open on a new PC: auto-register "logon autostart" tasks.
rem   - cw-preview      : Flask 保活 (tools/start_preview.cmd)
rem   - CRM-TrayMonitor : tray status monitor          (tools/tray-monitor.cmd)
rem   - existing tasks are kept (never overwritten)
rem   - registration logic lives in tools/register_autostart.py
rem ============================================================
"%~dp0venv\Scripts\python.exe" "%~dp0tools\register_autostart.py"
if errorlevel 1 (
    echo [hint] autostart registration incomplete (try running Launch-App.cmd as admin once).
    echo        the app still works; for boot autostart, manually create each task:
    echo        schtasks /Create /TN "cw-preview" /TR "\"%~dp0tools\start_preview.cmd\"" /SC ONLOGON
    echo        schtasks /Create /TN "CRM-TrayMonitor" /TR "\"%~dp0tools\tray-monitor.cmd\"" /SC ONLOGON
) else (
    echo [done] logon autostart tasks ready (cw-preview + CRM-TrayMonitor); they start on next boot.
)

rem CRM one-click launcher - this is the only file you need to open.
rem Double-click it in Explorer, or run with args: fix / check / open
"%~dp0venv\Scripts\python.exe" "%~dp0tools\launcher.py" %*
endlocal
pause
