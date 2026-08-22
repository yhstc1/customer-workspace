# -*- coding: utf-8 -*-
"""FC 环境变量配置（全部从函数计算环境变量读取，不硬编码任何密钥）。"""
import os

# RDS MySQL
DB_HOST = os.environ.get("MYSQL_HOST", "")
DB_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
DB_USER = os.environ.get("MYSQL_USER", "")
DB_PASS = os.environ.get("MYSQL_PASSWORD", "")
DB_NAME = os.environ.get("MYSQL_DB", "crm")

# 钉钉企业内部小程序凭证（P0-1 创建的「客户管理平台」）
DING_APP_KEY = os.environ.get("DING_APP_KEY", "")
DING_APP_SECRET = os.environ.get("DING_APP_SECRET", "")

# JWT（FC 无状态，用 token 替代 session 维持登录态）
JWT_SECRET = os.environ.get("JWT_SECRET", "please-change-in-fc-env")
JWT_EXPIRE_HOURS = int(os.environ.get("JWT_EXPIRE_HOURS", "720"))  # 30 天

# 腾讯地图（geo 逻辑放后端调，避小程序域名白名单）
TENCENT_MAP_KEY = os.environ.get("TENCENT_MAP_KEY", "")

# 前端小程序基址（用于 CORS，留空表示不限制）
ALLOW_ORIGIN = os.environ.get("ALLOW_ORIGIN", "*")

# 对象存储 OSS（导出/备份文件，用签名 URL 下发）
OSS_ENDPOINT = os.environ.get("OSS_ENDPOINT", "")
OSS_BUCKET = os.environ.get("OSS_BUCKET", "")
OSS_AK = os.environ.get("OSS_AK", "")
OSS_SK = os.environ.get("OSS_SK", "")
