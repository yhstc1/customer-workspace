# -*- coding: utf-8 -*-
"""把 H5 静态包上传到阿里云 OSS（前后端分离方案）。

前置：pip install oss2
用法：
    set ALIYUN_AK_ID=xxx
    set ALIYUN_AK_SECRET=xxx
    python upload_h5_oss.py

或直接在脚本里填 AK（不推荐，易泄露）。
"""
import os
import sys
import zipfile

_CT_MAP = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".apk": "application/vnd.android.package-archive",
}

def _guess_ct(name):
    _, ext = os.path.splitext(name.lower())
    return _CT_MAP.get(ext, "application/octet-stream")

try:
    import oss2
except ImportError:
    print("缺少 oss2，先装: pip install oss2")
    sys.exit(1)

# ============ 配置（按需修改） ============
BUCKET_NAME = "crm-h5-static"          # OSS bucket 名（全局唯一，自己换）
REGION = "cn-hangzhou"                 # 与 FC 同地域（杭州）
ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"  # 公网端点（本机上传用；若在阿里云 ECS 内可换 internal 内网）
PUBLIC_ENDPOINT = "oss-cn-hangzhou.aliyuncs.com"     # 对外访问域名
LOCAL_ZIP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h5-dist.zip")
PREFIX = ""                            # 上传到 bucket 根；如需子目录改这里

AK_ID = os.environ.get("ALIYUN_AK_ID") or ""
AK_SECRET = os.environ.get("ALIYUN_AK_SECRET") or ""

if not AK_ID or not AK_SECRET:
    print("请先设置环境变量 ALIYUN_AK_ID / ALIYUN_AK_SECRET")
    sys.exit(1)

auth = oss2.Auth(AK_ID, AK_SECRET)
bucket = oss2.Bucket(auth, ENDPOINT, BUCKET_NAME)

# 若 bucket 不存在则创建（标准存储，公共读）
try:
    bucket.get_bucket_info()
    print("bucket 已存在:", BUCKET_NAME)
except oss2.exceptions.NoSuchBucket:
    bucket.create_bucket(oss2.BUCKET_ACL_PUBLIC_READ)
    print("已创建 bucket:", BUCKET_NAME, "(公共读)")

# 解压 zip 并逐文件上传，保持目录结构（去掉 h5-dist/ 前缀）
count = 0
with zipfile.ZipFile(LOCAL_ZIP) as z:
    for name in z.namelist():
        if name.endswith("/"):
            continue
        # h5-dist/m.html -> m.html ; h5-dist/static/... -> static/...
        arc = name
        if arc.startswith("h5-dist/"):
            arc = arc[len("h5-dist/"):]
        if PREFIX:
            arc = PREFIX.rstrip("/") + "/" + arc
        data = z.read(name)
        bucket.put_object(arc, data, headers={"Content-Type": _guess_ct(arc)})
        count += 1
        print("uploaded", arc)

print(f"完成，共上传 {count} 个文件")
print("OSS 域名: https://{}.{}/m.html".format(BUCKET_NAME, PUBLIC_ENDPOINT))
