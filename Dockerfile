# 客户管理工作空间 - Docker 镜像
# 基础镜像：官方 Python 3.13 精简版
FROM python:3.13-slim

# 环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    DATA_DIR=/data

WORKDIR /app

# 先装依赖（利用 Docker 层缓存，requirements.txt 不变时无需重装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码（.dockerignore 已排除 *.db / .workbuddy 等本地文件）
COPY . .

# 创建数据目录与报告目录
RUN mkdir -p /data /app/reports

# Koyeb 会注入 PORT 环境变量；gunicorn 绑定 0.0.0.0:${PORT}
EXPOSE 8000

# 健康检查（Koyeb 也可在控制台另行配置）
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/dashboard')" || exit 1

# 启动命令：shell 形式以便展开 ${PORT}
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120 --access-logfile - --error-logfile - app:app"]
