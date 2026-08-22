# -*- coding: utf-8 -*-
"""OSS 上传（导出文件 / 备份）。

导出文件不直接公网暴露，用「临时签名 URL」下发（默认 1 小时有效）。
依赖 aliyun-oss-sdk-python（FC 中需加入 requirements.txt）。
"""
import time
import config

_OSS_AVAILABLE = True
try:
    import oss2
except Exception:
    _OSS_AVAILABLE = False

_bucket = None


def _get_bucket():
    global _bucket
    if _bucket is not None:
        return _bucket
    endpoint = config.OSS_ENDPOINT
    bucket_name = config.OSS_BUCKET
    ak = config.OSS_AK
    sk = config.OSS_SK
    if not (endpoint and bucket_name and ak and sk):
        return None
    auth = oss2.Auth(ak, sk)
    _bucket = oss2.Bucket(auth, endpoint, bucket_name)
    return _bucket


def upload_text(object_key, text, content_type="text/plain"):
    """上传文本到 OSS，返回 {url, object_key} 或 {"error": ...}。"""
    if not _OSS_AVAILABLE:
        return {"error": "oss2 未安装"}
    bucket = _get_bucket()
    if bucket is None:
        return {"error": "OSS 未配置（缺 endpoint/bucket/ak/sk 环境变量）"}
    bucket.put_object(object_key, text, headers={"Content-Type": content_type})
    # 生成 1 小时有效签名 URL
    url = bucket.sign_url("GET", object_key, 3600)
    return {"url": url, "object_key": object_key}


def upload_bytes(object_key, data, content_type="application/octet-stream"):
    if not _OSS_AVAILABLE:
        return {"error": "oss2 未安装"}
    bucket = _get_bucket()
    if bucket is None:
        return {"error": "OSS 未配置"}
    bucket.put_object(object_key, data, headers={"Content-Type": content_type})
    url = bucket.sign_url("GET", object_key, 3600)
    return {"url": url, "object_key": object_key}
