"""
地理编码与地图服务
- 地址 -> 经纬度（腾讯地图 WebService 地理编码，需 Key；中文地址解析准）
- 腾讯返回 GCJ02 坐标 -> 转 WGS84，适配现有 Leaflet/OSM 地图
- 通过 curl 子进程联网（主机网络，绕过受限 Python 运行环境）
- 附近客户查询（Haversine 公式计算距离）
"""
import os
import json
import math
import subprocess
import urllib.parse


BASE = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE, ".env")
TENCENT_GEOCODE_URL = "https://apis.map.qq.com/ws/geocoder/v1/"

# 地理编码结果缓存：相同地址只联网解析一次（有上限的 LRU 风格，仅缓存成功结果、不缓存 None/失败）
_GEOCODE_CACHE = {}
_GEOCODE_CACHE_ORDER = []  # FIFO 顺序，用于超上限时淘汰最旧
GEOCODE_CACHE_MAX = 4096


# ---------- Key 解析 ----------
def load_tencent_key():
    key = os.environ.get("TENCENT_MAP_KEY")
    if key:
        return key
    # FC 环境：密钥已在函数环境变量中，不读本地 .env 文件
    if os.environ.get("MYSQL_HOST"):
        return None
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and line.startswith("TENCENT_MAP_KEY="):
                return line.split("=", 1)[1].strip()
    return None


# ---------- GCJ02 -> WGS84 ----------
A = 6378245.0
EE = 0.00669342162296594323


def _transformlat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + \
        0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) +
            20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) +
            40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) +
            320.0 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transformlng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + \
        0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) +
            20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) +
            40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) +
            300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lng, lat):
    """GCJ02 -> WGS84（一次近似，误差 ~1-2 米，地图显示足够）"""
    dlat = _transformlat(lng - 105.0, lat - 35.0)
    dlng = _transformlng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * math.pi)
    mglat = lat + dlat
    mglng = lng + dlng
    return lng * 2 - mglng, lat * 2 - mglat


# ---------- 腾讯地理编码（curl 子进程） ----------
def geocode(address):
    """
    将地址文本转换为经纬度（WGS84）
    使用腾讯地图 WebService 地理编码（中文地址解析准，门牌级可命中）。
    返回: (latitude, longitude) 或 None
    """
    if not address:
        return None
    if address in _GEOCODE_CACHE:
        # 命中缓存：移到队尾标记为最近使用
        try:
            _GEOCODE_CACHE_ORDER.remove(address)
        except ValueError:
            pass
        _GEOCODE_CACHE_ORDER.append(address)
        return _GEOCODE_CACHE[address]
    key = load_tencent_key()
    if not key:
        print("[地理编码] 未配置 TENCENT_MAP_KEY，跳过")
        return None
    params = urllib.parse.urlencode({
        'address': address,
        'policy': '1',
        'key': key
    })
    url = TENCENT_GEOCODE_URL + '?' + params
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "15", url],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode != 0 or not r.stdout.strip():
            print("[地理编码] curl 联网失败: %s" % address)
            return None
        d = json.loads(r.stdout)
        status = d.get("status")
        if status == 0:
            loc = d["result"]["location"]
            wgs_lng, wgs_lat = gcj02_to_wgs84(float(loc["lng"]), float(loc["lat"]))
            _GEOCODE_CACHE[address] = (wgs_lat, wgs_lng)
            _GEOCODE_CACHE_ORDER.append(address)
            if len(_GEOCODE_CACHE_ORDER) > GEOCODE_CACHE_MAX:
                old = _GEOCODE_CACHE_ORDER.pop(0)
                _GEOCODE_CACHE.pop(old, None)
            return wgs_lat, wgs_lng
        if status == 121:
            print("[地理编码] 配额耗尽 (status 121): %s" % address)
            return None
        print("[地理编码] 地址 '%s' 解析失败 status=%s %s"
              % (address, status, d.get("message", "")))
        return None
    except Exception as e:
        print("[地理编码错误] 地址 '%s': %s" % (address, e))
        return None


def reverse_geocode(lat, lon):
    """
    将经纬度（WGS84）反解为中文地址名称
    使用腾讯地图 WebService 逆地理编码。
    返回: 地址字符串（如"武汉市江夏区"）或 None
    """
    key = load_tencent_key()
    if not key:
        print("[逆地理编码] 未配置 TENCENT_MAP_KEY，跳过")
        return None
    # coord_type=1 告诉腾讯传入的是 WGS84（GPS）坐标，腾讯内部会转 GCJ02 处理
    params = urllib.parse.urlencode({
        'location': '%s,%s' % (lat, lon),
        'key': key,
        'get_poi': '0',
        'coord_type': '1'
    })
    url = TENCENT_GEOCODE_URL + '?' + params
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "15", url],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode != 0 or not r.stdout.strip():
            print("[逆地理编码] curl 联网失败")
            return None
        d = json.loads(r.stdout)
        status = d.get("status")
        if status == 0:
            result = d["result"]
            # 优先用推荐地址，回退到完整地址
            addr = result.get("formatted_addresses", {}).get("recommend", "") or result.get("address", "")
            if addr:
                return addr
            # 地址组件拼接
            comp = result.get("address_component", {})
            parts = [comp.get(k, "") for k in ("nation", "province", "city", "district")]
            return " ".join(p for p in parts if p) or None
        if status == 121:
            print("[逆地理编码] 配额耗尽 (status 121)")
            return None
        print("[逆地理编码] status=%s %s" % (status, d.get("message", "")))
        return None
    except Exception as e:
        print("[逆地理编码错误]: %s" % e)
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


def find_nearby_customers(my_lat, my_lon, customers, radius_km=None):
    """
    查找附近客户（按距离排序，附带 distance 字段）
    参数:
        my_lat, my_lon: 我的位置
        customers: 客户列表（dict 列表，需含 latitude, longitude）
        radius_km: 搜索半径（公里）；为 None 时返回全部含坐标客户
    返回:
        按距离排序的附近客户列表（附带 distance 字段）
    """
    nearby = []
    # 范围窗口剪枝：先用经纬度包围盒过滤，避免对全部客户点都做昂贵的 haversine（原暴力枚举 O(n) 距离计算）。
    # 包围盒是圆（radius_km）的超集，剪枝不会漏掉任何圆内点（无假阴性）。
    box = None
    if radius_km is not None:
        lat_delta = radius_km / 111.0
        coslat = math.cos(math.radians(my_lat)) or 1e-9
        lon_delta = radius_km / (111.0 * coslat)
        box = (my_lat - lat_delta, my_lat + lat_delta,
               my_lon - lon_delta, my_lon + lon_delta)
    for c in customers:
        if c["latitude"] and c["longitude"]:
            if box and not (box[0] <= c["latitude"] <= box[1] and box[2] <= c["longitude"] <= box[3]):
                continue
            dist = haversine(my_lat, my_lon, c["latitude"], c["longitude"])
            if radius_km is None or dist <= radius_km:
                c_with_dist = dict(c)
                c_with_dist["distance_km"] = round(dist, 2)
                nearby.append(c_with_dist)

    nearby.sort(key=lambda x: x["distance_km"])
    return nearby
