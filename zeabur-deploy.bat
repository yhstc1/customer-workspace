@echo off
cd /d "%~dp0"
set "NODE_DIR=C:\Users\123\.workbuddy\binaries\node\versions\22.22.2"
set "PATH=%NODE_DIR%;%PATH%"

echo ============================================
echo Step 1: Zeabur login
echo Browser will open. Login with EMAIL, then click Confirm.
echo ============================================
call "%NODE_DIR%\npx.cmd" zeabur@latest auth login

echo.
echo ============================================
echo Step 2: Deploy
echo When asked "create one now? (Y/n)" -> type Y and press Enter.
echo Then enter a project name, choose Hong Kong region, Enter for default env.
echo Do NOT press Ctrl+C. Follow prompts until a URL appears.
echo ============================================
call "%NODE_DIR%\npx.cmd" zeabur@latest deploy

echo.
echo ============================================
echo Deploy process ended. Check the logs above for the service URL or errors.
echo ============================================
pause
