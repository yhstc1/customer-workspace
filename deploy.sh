#!/bin/bash
# ==========================================
# 部署脚本 - 将应用暴露到公网
# 提供两种方式：内网穿透（临时）或 Docker（正式）
# ==========================================

set -e

echo "=========================================="
echo "  客户工作空间 - 部署助手"
echo "=========================================="
echo ""
echo "请选择部署方式："
echo "  1) 内网穿透（cpolar）— 快速试用，电脑不关机即可访问"
echo "  2) 生成云服务器部署包 — 部署到阿里云/腾讯云"
echo "  3) 仅查看钉钉配置指南"
echo ""
read -p "请输入选项 (1/2/3): " choice

case $choice in
    1)
        echo ""
        echo "=== 方式1：内网穿透（cpolar）==="
        echo ""
        # 检查 cpolar 是否安装
        if ! command -v cpolar &> /dev/null; then
            echo "cpolar 未安装，正在安装..."
            curl -L https://www.cpolar.com/static/downloads/install-release-cpolar.sh | sudo bash 2>/dev/null || {
                echo "自动安装失败，请手动安装："
                echo "  curl -L https://www.cpolar.com/static/downloads/install-release-cpolar.sh | sudo bash"
                echo "  注册账号: https://www.cpolar.com"
                echo "  配置token: cpolar authtoken <你的token>"
                exit 1
            }
        fi

        echo "启动内网穿透..."
        echo "访问地址将在下方显示，手机用该地址即可访问"
        echo ""
        cpolar http 5000
        ;;
    2)
        echo ""
        echo "=== 方式2：生成云服务器部署包 ==="
        OUTPUT_DIR="/workspace/customer-workspace-deploy"
        rm -rf "$OUTPUT_DIR"
        mkdir -p "$OUTPUT_DIR"

        # 打包项目（排除缓存和数据库）
        cd /workspace
        tar czf "$OUTPUT_DIR/customer-workspace.tar.gz" \
            --exclude='__pycache__' \
            --exclude='data/*.db' \
            --exclude='*.png' \
            --exclude='.git' \
            customer-workspace/

        # 生成 Dockerfile
        cat > "$OUTPUT_DIR/Dockerfile" << 'EOF'
FROM python:3.11-slim
WORKDIR /app
COPY customer-workspace/ .
RUN pip install --no-cache-dir flask requests
EXPOSE 5000
ENV PORT=5000
CMD ["python", "app.py"]
EOF

        # 生成 docker-compose.yml
        cat > "$OUTPUT_DIR/docker-compose.yml" << 'EOF'
version: '3'
services:
  app:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./data:/app/data
      - ./reports:/app/reports
    environment:
      - DINGTALK_APP_KEY=${DINGTALK_APP_KEY:-}
      - DINGTALK_APP_SECRET=${DINGTALK_APP_SECRET:-}
      - DINGTALK_CORP_ID=${DINGTALK_CORP_ID:-}
      - DINGTALK_AGENT_ID=${DINGTALK_AGENT_ID:-}
      - APP_BASE_URL=${APP_BASE_URL:-http://localhost:5000}
    restart: unless-stopped
EOF

        # 生成部署说明
        cat > "$OUTPUT_DIR/部署说明.md" << 'EOF'
# 云服务器部署说明

## 1. 准备服务器
- 购买阿里云/腾讯云轻量应用服务器（推荐 2核2G，约 50-100元/月）
- 操作系统选择 Ubuntu 22.04
- 开放端口 5000（在安全组/防火墙中配置）

## 2. 上传部署包
```bash
scp customer-workspace.tar.gz root@你的服务器IP:/opt/
ssh root@你的服务器IP
cd /opt && tar xzf customer-workspace.tar.gz
```

## 3. Docker 部署（推荐）
```bash
# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 启动
cd /opt
docker-compose up -d

# 查看日志
docker-compose logs -f
```

## 4. 配置钉钉（可选）
```bash
# 编辑 docker-compose.yml，填入钉钉凭证
vi docker-compose.yml
# 重启
docker-compose restart
```

## 5. 配置域名 + HTTPS（推荐）
钉钉微应用要求 HTTPS，可用 Nginx + Let's Encrypt：
```bash
apt install nginx certbot python3-certbot-nginx
# 配置 Nginx 反向代理到 5000 端口
# certbot --nginx -d yourdomain.com
```
EOF

        echo "部署包已生成: $OUTPUT_DIR"
        echo ""
        echo "包含文件："
        ls -la "$OUTPUT_DIR"
        echo ""
        echo "上传到服务器后，按 '部署说明.md' 操作即可。"
        ;;
    3)
        echo ""
        echo "=== 钉钉配置指南 ==="
        echo ""
        echo "1. 打开 https://open-dev.dingtalk.com"
        echo "2. 注册/登录钉钉开发者后台"
        echo "3. 创建 H5 微应用，获取 AppKey / AppSecret / AgentId"
        echo "4. 在应用首页地址填入你的公网 URL + /dingtalk"
        echo "5. 在本项目的 dingtalk_config.py 中填入凭证"
        echo ""
        echo "详细说明见项目目录下: 钉钉集成指南.md"
        cat /workspace/customer-workspace/钉钉集成指南.md 2>/dev/null || echo "(指南文件待生成)"
        ;;
    *)
        echo "无效选项"
        ;;
esac
