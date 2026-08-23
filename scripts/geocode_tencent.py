"""
生产级：用腾讯地图 WebService 地理编码回填客户经纬度
- 走 curl 子进程（主机网络，绕过 venv python 无外网的限制）
- 腾讯返回 GCJ02 -> 转为 WGS84，适配现有 Leaflet/OSM 地图
- 按地址去重，减少 API 调用（额度敏感）
- 额度耗尽（status 121）时优雅停止并报告进度
- Key 来源：命令行 --key > 环境变量 TENCENT_MAP_KEY > 项目 .env 的 TENCENT_MAP_KEY

用法（Windows 主机，项目 venv）：
    venv\Scripts\python.exe geocode_tencent.py
    venv\Scripts\python.exe geocode_tencent.py --key 你的KEY
"""
import sys, os, json, math, subprocess, time, argparse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "customers.db")
ENV_FILE = os.path.join(BASE, ".env")


# ---------- Key 解析 ----------
def load_key(cli_key):
    if cli_key:
        return cli_key
    if os.environ.get("TENCENT_MAP_KEY"):
        return os.environ["TENCENT_MAP_KEY"]
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE, encoding="utf-8"):
            line = line.strip()
            if line.startswith("TENCENT_MAP_KEY="):
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
def geocode_tencent(address, key):
    import urllib.parse
    q = urllib.parse.quote(address)
    url = ("https://apis.map.qq.com/ws/geocoder/v1/"
           "?address=%s&policy=1&key=%s" % (q, key))
    try:
        r = subprocess.run(
            ["curl", "-s", "-m", "15", url],
            capture_output=True, text=True, timeout=20
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None, "curl_failed"
        d = json.loads(r.stdout)
        status = d.get("status")
        if status == 0:
            loc = d["result"]["location"]
            return gcj02_to_wgs84(float(loc["lng"]), float(loc["lat"])), None
        if status == 121:
            return None, "QUOTA_EXHAUSTED"
        return None, "status_%s:%s" % (status, d.get("message", ""))
    except Exception as e:
        return None, "err:%s" % e


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=None, help="腾讯地图 Key")
    args = ap.parse_args()

    key = load_key(args.key)
    if not key:
        print("[错误] 未找到腾讯地图 Key。请用 --key 传入，或设置 TMAP_KEY 环境变量。")
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, company, address FROM customers "
        "WHERE (latitude IS NULL OR longitude IS NULL) "
        "AND address IS NOT NULL AND address != ''"
    ).fetchall()
    print("[待处理] 缺坐标且含地址的客户：%d 条" % len(rows))

    # 按地址去重：相同地址只打一次 API
    uniq = {}
    for r in rows:
        uniq.setdefault(r["address"], []).append(r)

    total = len(rows)
    done = 0
    failed = 0
    quota_hit = False
    cache = {}

    for addr, grp in uniq.items():
        if quota_hit:
            print("  [额度耗尽] 剩余地址跳过。")
            failed += len(grp)
            continue
        if addr in cache:
            coords, err = cache[addr]
        else:
            coords, err = geocode_tencent(addr, key)
            cache[addr] = (coords, err)
            time.sleep(0.25)  # 礼貌节流

        if coords:
            for r in grp:
                conn.execute(
                    "UPDATE customers SET latitude=?, longitude=?, "
                    "updated_at=datetime('now','localtime') WHERE id=?",
                    (coords[1], coords[0], r["id"])
                )
            conn.commit()
            done += len(grp)
            print("  OK   x%d %s -> (%.5f, %.5f)" % (
                len(grp), addr[:24], coords[1], coords[0]))
        elif err == "QUOTA_EXHAUSTED":
            quota_hit = True
            failed += len(grp)
            print("  [额度耗尽] %s" % addr[:24])
        else:
            failed += len(grp)
            print("  FAIL %s : %s" % (addr[:24], err))

    conn.close()
    print("[完成] 成功 %d 条，失败 %d 条（共 %d）" % (done, failed, total))


if __name__ == "__main__":
    main()
