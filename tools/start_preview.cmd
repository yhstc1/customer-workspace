@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..") do set "PROJ=%%~fI"
set "PY=%PROJ%\venv\Scripts\python.exe"
set "PORT=5000"
set "LOG=%PROJ%\tools\preview_supervisor.log"
set "HB=%PROJ%\tools\preview_heartbeat.log"
rem 本脚本循环保活本地 Flask 服务。
rem Point PYTHONHOME to venv base python so venv python finds its stdlib (encodings)
for /f "tokens=1,* delims==" %%A in ('findstr /i "^home" "%PROJ%\venv\pyvenv.cfg"') do set "PYHOME=%%B"
set "PYTHONHOME=%PYHOME: =%"
set "PYTHONPATH="
rem Change to project dir so waitress can resolve app:app module
cd /d "%PROJ%"
echo [%date% %time%] Preview keeper started, watching Flask >> "%LOG%"
:loop
  rem check Flask on port 5000
  netstat -ano | findstr /R /C:":5000 " /C:":5000$" >nul
  if errorlevel 1 (
    echo [%date% %time%] Flask down, starting >> "%LOG%"
    "%PY%" "%PROJ%\tools\launch_bg.py" "%PY%" -m waitress --host=0.0.0.0 --port=5000 app:app
    timeout /t 5 >nul
  )
  rem heartbeat, write latest timestamp each loop
  echo [%date% %time%] heartbeat ok >> "%HB%"
  timeout /t 30 >nul
goto loop
