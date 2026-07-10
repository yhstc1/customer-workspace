@echo off
cd /d "%~dp0"

title 客户管理工作空间

echo ==========================================
echo   客户管理工作空间 - 正在启动...
echo ==========================================
echo.

REM 查找 Python 解释器
set "PY="

REM 1) 优先使用 WorkBuddy 托管 Python（确定可用）
if exist "C:\Users\123\.workbuddy\binaries\python\versions\3.13.12\python.exe" (
    set "PY=C:\Users\123\.workbuddy\binaries\python\versions\3.13.12\python.exe"
    goto :FOUND
)

REM 2) 检查常见安装位置
if exist "C:\Python313\python.exe" (
    set "PY=C:\Python313\python.exe"
    goto :FOUND
)
if exist "C:\Python312\python.exe" (
    set "PY=C:\Python312\python.exe"
    goto :FOUND
)
if exist "C:\Python311\python.exe" (
    set "PY=C:\Python311\python.exe"
    goto :FOUND
)
if exist "C:\Python310\python.exe" (
    set "PY=C:\Python310\python.exe"
    goto :FOUND
)

REM 3) 最后尝试 PATH 中的 python / python3 / py
for %%C in (python python3 py) do (
    where %%C >nul 2>&1
    if not errorlevel 1 (
        set "PY=%%C"
        goto :FOUND
    )
)

echo [错误] 未找到 Python 解释器
echo 请从 https://www.python.org/downloads/ 下载 Python 3.11+
echo 安装时务必勾选 "Add Python to PATH"
echo.
echo 也可以手动运行：
echo   python app.py
echo.
pause
exit /b 1

:FOUND
echo [信息] 使用 Python: %PY%
echo.

REM 检查依赖是否已安装（已装则跳过，避免重复联网）
%PY% -c "import flask, requests" >nul 2>&1
if not errorlevel 1 (
    echo [信息] 依赖已满足，跳过安装
    goto :START
)

REM 首次运行需要安装依赖（显示进度，超时自动失败不卡死）
echo [信息] 首次运行需要下载依赖，可能需要几分钟，请耐心等待...
echo.
%PY% -m pip install -r requirements.txt --timeout 60 --retries 2
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，通常是网络问题。请确认能联网后重试。
    echo 也可手动在命令行执行：
    echo   %PY% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

:START
REM 启动应用
echo.
echo 启动中，请稍候...
echo 启动后请在浏览器打开: http://localhost:5000
echo 移动端入口: http://localhost:5000/m
echo.
echo 按 Ctrl+C 可停止服务
echo ==========================================
echo.

%PY% app.py
pause
