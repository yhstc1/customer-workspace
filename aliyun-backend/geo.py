# -*- coding: utf-8 -*-
"""地图/附近/导航服务（geo 逻辑放后端调腾讯地图，避小程序域名白名单）。

- /api/nearby：根据定位坐标，算真实距离 + 路线（驾车），返回附近客户。
- /api/geo/distance：批量算距离。
- 腾讯地图 WebService API Key 走 FC 环境变量 TENCENT_MAP_KEY。
"""
import math
import requests
import config
import db


def _haversine(lat1, lng1, lat2, lng2):
    """球面距离（米），作为无 Key / 接口失败时的兜底近似。"""
    R = 6371000.0
    try:
        p1, p2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlmb = math.radians(lng2 - lng1)
        a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
        return int(2 * R * math.asin(math.sqrt(a)))
    except Exception:
        return 0


def nearby_customers(user_id, lat, lng, radius=5000, limit=20):
    """返回附近客户（按距离升序）。优先用腾讯地图驾车距离，失败兜底球面距离。"""
    rows = db.query(
        "SELECT id, company, name, latitude, longitude, address, phone "
        "FROM customers WHERE user_id=%s AND latitude IS NOT NULL AND longitude IS NOT NULL",
        (user_id,))
    key = config.TENCENT_MAP_KEY
    # 批量请求腾讯地图测距（单次最多 25 个点，这里分单点查）
    for r in rows:
        try:
            r_lat, r_lng = float(r["latitude"]), float(r["longitude"])
        except Exception:
            r["distance"] = None
            continue
        dist = None
        if key:
            try:
                resp = requests.get("https://apis.map.qq.com/ws/distance/v1/",
                                     params={"mode": "driving", "from": "%s,%s" % (lat, lng),
                                             "to": "%s,%s" % (r_lat, r_lng),
                                             "key": key}, timeout=4)
                j = resp.json()
                if j.get("status") == 0 and j.get("result"):
                    dist = j["result"][0]["distance"]
            except Exception:
                dist = None
        if dist is None:
            dist = _haversine(lat, lng, r_lat, r_lng)
        r["distance"] = dist
    rows.sort(key=lambda x: (x["distance"] is None, x["distance"] if x["distance"] is not None else 1e18))
    return rows[:limit]


def driving_route(lat, lng, to_lat, to_lng):
    """返回驾车路线规划（给导航用）。"""
    key = config.TENCENT_MAP_KEY
    if not key:
        return None
    try:
        resp = requests.get("https://apis.map.qq.com/ws/direction/v1/driving/",
                             params={"from": "%s,%s" % (lat, lng), "to": "%s,%s" % (to_lat, to_lng),
                                     "key": key}, timeout=6)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}
