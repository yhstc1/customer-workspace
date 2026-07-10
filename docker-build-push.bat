@echo off
cd /d "%~dp0"

echo ============================================================
echo Route A: Build image locally and push to Docker Hub
echo ============================================================
echo NOTE: Requires Docker Desktop installed and running.
echo       (If you do NOT have Docker, use Route B in the guide:
echo        deploy via Koyeb CLI from local folder, no Docker needed)
echo.

set /p DOCKER_USER=Enter your Docker Hub username: 
if "%DOCKER_USER%"=="" (
  echo [ERROR] Docker Hub username cannot be empty.
  pause
  exit /b 1
)

set IMAGE=docker.io/%DOCKER_USER%/customer-workspace
set TAG=latest

echo.
echo Step 1: docker login
docker login
if errorlevel 1 (
  echo [ERROR] docker login failed.
  pause
  exit /b 1
)

echo.
echo Step 2: build image
docker build -t %IMAGE%:%TAG% .
if errorlevel 1 (
  echo [ERROR] docker build failed.
  pause
  exit /b 1
)

echo.
echo Step 3: push to Docker Hub
docker push %IMAGE%:%TAG%
if errorlevel 1 (
  echo [ERROR] docker push failed.
  pause
  exit /b 1
)

echo.
echo ============================================================
echo SUCCESS. Image published at:
echo   %IMAGE%:%TAG%
echo.
echo Next: Koyeb console -> Create App -> Container -> fill:
echo   Image : %IMAGE%:%TAG%
echo   Port  : 8000
echo   Env   : PORT=8000  DATA_DIR=/data  FLASK_SECRET_KEY=^<your-secret^>
echo   Volume: mount /data   (so SQLite survives restarts)
echo ============================================================
pause
