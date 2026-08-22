# -*- coding: utf-8 -*-
"""阿里云 FC 3.0 HTTP 触发器事件函数入口（生产干净版）。

FC 3.0 中，HTTP 触发器调用事件函数时，会把 HTTP 请求转换成一个 JSON event：
{
  "version": "v1",
  "rawPath": "/api/healthz",
  "httpMethod": "GET",
  "headers": {...},
  "queryParameters": {...},
  "body": "...",
  "isBase64Encoded": false,
  "requestContext": {...}
}

本 handler 用 Flask 的 test_client 把 event 转成 WSGI 请求交给 app 处理，
再把 Flask 响应转成 FC 要求的 {statusCode, headers, body} 返回。

生产版：路由内部异常一律上抛、由 FC 返回 500；堆栈只写入 stderr（FC 函数日志）
便于排查，绝不向客户端泄露堆栈或内部信息。
"""
import base64
import json
import sys
import traceback
from urllib.parse import urlencode

from app import app


def _event_to_flask_kwargs(event):
    """把 FC HTTP event 转成 Flask test_client.open 参数。"""
    path = event.get("rawPath") or event.get("path", "/")
    # FC 3.0 HTTP 触发器 event 的 method 字段位置在不同版本有差异，
    # 兼容 httpMethod / method / requestContext.http.method 三种写法
    _rc = event.get("requestContext") or {}
    _rc_http = _rc.get("http") or {} if isinstance(_rc, dict) else {}
    method = (
        event.get("httpMethod")
        or event.get("method")
        or _rc_http.get("method")
        or "GET"
    )
    method = method.upper() if isinstance(method, str) else "GET"
    headers = event.get("headers") or {}
    query = event.get("queryParameters") or {}

    body = event.get("body") or ""
    if event.get("isBase64Encoded") and body:
        body = base64.b64decode(body)
    elif body:
        body = body.encode("utf-8")
    else:
        body = b""

    # queryParameters 形如 {"k":"v"} 或 {"k":"v1,v2"}
    query_string = urlencode(query, doseq=False) if query else ""

    return {
        "path": path,
        "method": method,
        "headers": headers,
        "query_string": query_string,
        "data": body,
    }


def _flask_response_to_fc(resp):
    """把 Flask Response 转成 FC HTTP 触发器返回格式。"""
    data = resp.get_data()
    is_b64 = False
    try:
        body = data.decode("utf-8")
    except UnicodeDecodeError:
        body = base64.b64encode(data).decode("ascii")
        is_b64 = True

    # headers 可能是 Headers 对象，转成普通 dict
    headers = {}
    for k, v in resp.headers.items():
        headers[k] = v

    return {
        "statusCode": resp.status_code,
        "headers": headers,
        "body": body,
        "isBase64Encoded": is_b64,
    }


def handler(event, context):
    if isinstance(event, (bytes, bytearray)):
        event = json.loads(event.decode("utf-8"))
    elif isinstance(event, str):
        event = json.loads(event)

    # 适配 FC 2.0/3.0 字段差异
    if "rawPath" not in event and "path" not in event:
        # 不是 HTTP 触发器事件，直接返回一个简单健康响应
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"code": 0, "data": {"status": "ok"}}),
        }

    kwargs = _event_to_flask_kwargs(event)

    # 用 test_client 在 WSGI 层调用 Flask app，不监听端口
    with app.test_client() as client:
        try:
            resp = client.open(**kwargs)
        except Exception:  # noqa: BLE001
            # 生产环境：异常上抛由 FC 返回 500；堆栈写入 stderr 供函数日志排查，
            # 不向客户端泄露任何内部错误信息
            traceback.print_exc(file=sys.stderr)
            raise
        result = _flask_response_to_fc(resp)
        return result
