#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时材料价格同步器 —— 造价工程师工作台配套脚本
================================================
数据来源（严格按用户指定，不做任何估算或编造）：
  1) SMM1#电解铜价 : 上海有色网      https://www.smm.com.cn/price
  2) 热镀锌板价    : 我的钢铁网      https://duxin.mysteel.com

用法
----
  python price_sync.py                # 抓取一次，写入同目录 prices.json
  python price_sync.py --json         # 抓取一次，直接打印 JSON（不写文件）
  python price_sync.py --serve        # 启动本地服务(默认 8000)，页面点「同步最新价」即可取数
  python price_sync.py --serve 8080   # 指定端口

为什么需要它
------------
浏览器同源策略决定了「双击打开 HTML（file://）」时，页面无法直接跨域抓取这两个网站。
本脚本在本地抓取后写入 prices.json，或直接提供 /api/prices 接口，页面即可读取。

关于 SMM 电解铜
--------------
数据取自 https://www.smm.com.cn/price 现货价格表的首行「SMM 1#电解铜」（上海基准）：
  价格范围 / 均价 / 涨跌 / 单位 / 日期 均为公开可见，无需登录、无需 Cookie。
（同一页面还有「SMM 广东1#电解铜」「SMM 鹰潭1#电解铜」等，本脚本只取上海基准价。）

我的钢铁网镀锌板同为公开页面，无需登录，可直接抓取。
"""

import argparse
import gzip
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request
import zlib
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SMM_URL = "https://www.smm.com.cn/price"
GALV_URL = "https://duxin.mysteel.com"
CACHE_SECONDS = 180

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


# ---------------------------------------------------------------- 基础工具
def _headers():
    return {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        # 只声明标准库能解压的编码。注意 www.smm.com.cn 会无条件回 gzip，
        # 因此下面必须真正解压，否则拿到的是乱码二进制。
        "Accept-Encoding": "gzip, deflate",
    }


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as resp:
        raw = resp.read()
        enc = (resp.headers.get("Content-Encoding") or "").lower()
    if enc in ("gzip", "x-gzip"):
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def strip_tags(s):
    s = re.sub(r"<script.*?</script>", " ", s, flags=re.S)
    s = re.sub(r"<style.*?</style>", " ", s, flags=re.S)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- 镀锌板（我的钢铁网）
def fetch_galv():
    """抓取 duxin.mysteel.com「热门城市今日报价」——镀锌板卷城市价（元/吨）。"""
    out = {"date": datetime.now().strftime("%Y-%m-%d"), "unit": "元/吨",
           "source": "我的钢铁网", "cities": {}, "changes": {}, "message": ""}
    try:
        html = http_get(GALV_URL)
    except Exception as exc:                                  # noqa: BLE001
        out["message"] = "我的钢铁网访问失败：%s" % exc
        return out

    m = re.search(r'name="publish"[^>]*content="published at ([\d\-]{8,10})', html)
    if m:
        out["date"] = m.group(1)

    dl = re.search(r'<dl[^>]*class="today-price"[^>]*>(.*?)</dl>', html, re.S)
    seg = dl.group(1) if dl else html
    items = re.findall(r"<li>\s*<a\b[^>]*>\s*<span>([^<]{1,12})</span>\s*"
                       r"(\d+(?:\.\d+)?)\s*<em[^>]*>([^<]*)</em>", seg)
    for city, price, chg in items:
        city = city.strip()
        out["cities"][city] = float(price) if "." in price else int(price)
        out["changes"][city] = chg.strip()

    if not out["cities"]:
        out["message"] = "未解析到城市报价，页面结构可能已调整。"
    return out


# ---------------------------------------------------------------- 电解铜（上海有色网）
# https://www.smm.com.cn/price 由 Next.js 渲染，价格表列序为：
#   名称 / 价格范围 / 均价 / 涨跌 / 单位 / 日期   —— 公开可见，无需登录。
# class 名带构建哈希（如 page-module__E0kJGG__nameCell），故只锚定稳定后缀。
_SMM_ROW = re.compile(
    r'<td class="[^"]*__nameCell"><a href="(/price/\d+)"[^>]*>(.*?)</a></td>'
    r'<td class="[^"]*">(.*?)</td>'                    # 价格范围
    r'<td class="[^"]*__avgPrice[^"]*">(.*?)</td>'     # 均价
    r'<td class="[^"]*">(.*?)</td>'                    # 涨跌
    r'<td[^>]*>(.*?)</td>'                             # 单位
    r'<td[^>]*>(.*?)</td>',                            # 日期
    re.S,
)

# 排除项：同页还有广东/鹰潭报价、洋山铜溢价、升贴水等，均非「SMM 1#电解铜」基准价
_SMM_EXCLUDE = ("广东", "鹰潭", "溢价", "升贴水")


def _to_num(s):
    s = (s or "").strip().replace(",", "")
    return float(s) if re.match(r"^-?\d+(\.\d+)?$", s) else None


def _smm_rows(html):
    rows = []
    for href, name, rng, avg, chg, unit, date in _SMM_ROW.findall(html):
        rows.append({"href": href, "name": strip_tags(name), "range": strip_tags(rng),
                     "avg": strip_tags(avg), "change": strip_tags(chg),
                     "unit": strip_tags(unit), "date": strip_tags(date)})
    return rows


def fetch_copper():
    """抓取 www.smm.com.cn/price 现货价格表首行「SMM 1#电解铜」（上海基准）。"""
    out = {"status": "error", "date": datetime.now().strftime("%Y-%m-%d"),
           "price": None, "change": None, "unit": "元/吨", "source": "上海有色网 SMM",
           "name": "SMM 1#电解铜", "low": None, "high": None, "range": "",
           "url": SMM_URL, "message": ""}
    try:
        html = http_get(SMM_URL)
    except Exception as exc:                                  # noqa: BLE001
        out["message"] = "上海有色网访问失败：%s" % exc
        return out

    rows = _smm_rows(html)
    if not rows:
        out["message"] = "未解析到现货价格表，页面结构可能已调整。"
        return out

    row = None
    for r in rows:                                            # 首选：名称即「SMM 1#电解铜」
        if r["name"].replace(" ", "").upper() == "SMM1#电解铜":
            row = r
            break
    if row is None:                                           # 兜底：含 1#电解铜 的 SMM 上海基准报价
        for r in rows:
            n = r["name"]
            if "1#电解铜" in n and "SMM" in n.upper() and not any(k in n for k in _SMM_EXCLUDE):
                row = r
                break
    if row is None:
        out["message"] = "未找到「SMM 1#电解铜」价格行，页面结构可能已调整。"
        return out

    avg = _to_num(row["avg"])
    if avg is None:
        out["message"] = "「%s」均价字段为空或非数值：%s" % (row["name"], row["avg"] or "（空）")
        return out

    out["status"] = "ok"
    out["price"] = int(avg) if avg == int(avg) else avg
    out["change"] = row["change"] or ""
    out["unit"] = row["unit"] or "元/吨"
    out["name"] = row["name"]
    out["range"] = row["range"]
    out["url"] = "https://www.smm.com.cn" + row["href"]
    if re.match(r"^\d{4}-\d{2}-\d{2}$", row["date"] or ""):
        out["date"] = row["date"]
    m = re.match(r"^\s*([\d.]+)\s*[~～\-]{1,2}\s*([\d.]+)\s*$", row["range"] or "")
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        out["low"] = int(lo) if lo == int(lo) else lo
        out["high"] = int(hi) if hi == int(hi) else hi
    return out


def collect():
    data = {
        "updated": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "copper": fetch_copper(),
        "galv": fetch_galv(),
    }
    return data


# ---------------------------------------------------------------- 本地服务
_CACHE = {"ts": 0.0, "data": None}


def get_prices(force=False):
    now = time.time()
    if not force and _CACHE["data"] is not None and (now - _CACHE["ts"]) < CACHE_SECONDS:
        return _CACHE["data"]
    data = collect()
    _CACHE["ts"] = now
    _CACHE["data"] = data
    return data


def serve(port, out_dir):
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=out_dir, **kw)

        def log_message(self, fmt, *args):
            sys.stderr.write("[price_sync] %s\n" % (fmt % args))

        def do_GET(self):                                     # noqa: N802
            path = self.path.split("?")[0]
            if path in ("/api/prices", "/api/prices/", "/api/refresh"):
                try:
                    data = get_prices(force=path.rstrip("/").endswith("refresh"))
                    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                    self.send_response(200)
                except Exception as exc:                      # noqa: BLE001
                    body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return super().do_GET()

    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://localhost:%d/" % port
    print("=" * 66)
    print(" 造价工作台 · 价格同步服务已启动")
    print("   页面地址 : %szaojia-workbench9.9.html" % url)
    print("   价格接口 : %sapi/prices   (实时抓取，缓存 %d 秒)" % (url, CACHE_SECONDS))
    print("   强制刷新 : %sapi/refresh" % url)
    print("   按 Ctrl+C 停止")
    print("=" * 66)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()


# ---------------------------------------------------------------- 入口
def main():
    ap = argparse.ArgumentParser(description="造价工作台 · 每日材料价格同步器")
    ap.add_argument("--serve", nargs="?", const=8000, type=int, metavar="PORT",
                    help="启动本地服务（默认端口 8000），提供 /api/prices")
    ap.add_argument("--json", action="store_true", help="仅打印 JSON，不写文件")
    ap.add_argument("--out", default=SCRIPT_DIR, metavar="DIR", help="prices.json 输出目录")
    args = ap.parse_args()

    if args.serve:
        serve(args.serve, args.out)
        return 0

    data = collect()
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    if args.json:
        sys.stdout.write(payload + "\n")
        return 0

    path = os.path.join(args.out, "prices.json")
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(payload)

    cu, gv = data["copper"], data["galv"]
    print("已写入：%s" % path)
    if cu.get("status") == "ok":
        rng = ("%s~%s" % (cu["low"], cu["high"])) if cu.get("low") and cu.get("high") else (cu.get("range") or "")
        print("  SMM1#电解铜 : %s 元/吨   涨跌 %s   范围 %s   (%s)"
              % (cu["price"], cu["change"] or "—", rng or "—", cu["date"]))
    else:
        print("  SMM1#电解铜 : 未获取（%s）" % cu.get("message", "未知原因"))
    if gv.get("cities"):
        print("  热镀锌板价   : %s 个城市  %s" % (len(gv["cities"]), gv["date"]))
        for c in ("上海", "广州", "杭州"):
            if c in gv["cities"]:
                print("      %s %s 元/吨  %s" % (c, gv["cities"][c], gv["changes"].get(c, "")))
    else:
        print("  热镀锌板价   : 未获取（%s）" % gv.get("message", "未知原因"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
