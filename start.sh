#!/bin/bash
# 启动客户管理工作空间（macOS / Linux）
cd "$(dirname "$0")"

echo "=========================================="
echo "  客户管理工作空间 - 正在启动"
echo "=========================================="

# 检查 Python
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "[错误] 未检测到 Python，请先安装 Python 3.11+"
    exit 1
fi

# 安装依赖（首次）
echo "正在安装/检查依赖..."
pip3 install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt -q 2>/dev/null

# 启动
echo ""
echo "启动后请浏览器打开: http://localhost:5000"
echo "按 Ctrl+C 停止"
echo "=========================================="
echo ""

PYTHON_BIN="python3"
command -v python3 &> /dev/null || PYTHON_BIN="python"
exec $PYTHON_BIN app.py
