"""
地理编码与地图服务
- 地址 -> 经纬度（使用 Nominatim 免费服务）
- 附近客户查询（Haversine 公式计算距离）
"""
import requests
import math
import time
import os
import urllib.parse


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode(address):
    """
    将地址文本转换为经纬度
    使用 OpenStreetMap Nominatim 免费服务（无需 API Key）
    返回: (latitude, longitude) 或 None
    """
    try:
        params = {
            "q": address,
            "format": "json",
            "limit": 1,
            "accept-language": "zh-CN"
        }
        headers = {
            "User-Agent": "CustomerWorkspace/1.0 (local use)"
        }
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data and len(data) > 0:
            return float(data[0]["lat"]), float(data[0]["lon"])
        return None
    except Exception as e:
        print(f"[地理编码错误] 地址 '{address}': {e}")
        return None


def haversine(lat1, lon1, lat2, lon2):
    """
    用 Haversine 公式计算两点间距离（单位：公里）
    """
    R = 6371.0  # 地球半径（km）

    lat1_r = math.radians(lat1)
    lon1_r = math.radians(lon1)
    lat2_r = math.radians(lat2)
    lon2_r = math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def find_nearby_customers(my_lat, my_lon, customers, radius_km=10):
    """
    查找指定半径内的客户
    参数:
        my_lat, my_lon: 我的位置
        customers: 客户列表（dict 列表，需含 latitude, longitude）
        radius_km: 搜索半径（公里）
    返回:
        按距离排序的附近客户列表（附带 distance 字段）
    """
    nearby = []
    for c in customers:
        if c["latitude"] and c["longitude"]:
            dist = haversine(my_lat, my_lon, c["latitude"], c["longitude"])
            if dist <= radius_km:
                c_with_dist = dict(c)
                c_with_dist["distance_km"] = round(dist, 2)
                nearby.append(c_with_dist)

    nearby.sort(key=lambda x: x["distance_km"])
    return nearby
