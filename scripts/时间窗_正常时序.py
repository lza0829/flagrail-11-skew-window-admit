#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间窗自动化 · 正常时序脚本。

E 严格落在 [D, C] 内：两张不同边缘的回读都应成为正式确认，
放量门齐套可放量，贯验通过。

用法：python3 scripts/时间窗_正常时序.py [BASE_URL]
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FLAGRAIL_BASE", "http://127.0.0.1:11800")).rstrip("/")
RUN = datetime.now(timezone.utc).strftime("%H%M%S") + f"-{os.getpid()}"
fails = []


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api" + urllib.parse.quote(path, safe="/?=&%+:"), data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


for _ in range(60):
    try:
        call("GET", "/健康"); break
    except Exception:
        time.sleep(0.5)
else:
    sys.exit("连不上后端")

now = datetime.now(timezone.utc)
D, C = now - timedelta(seconds=600), now
vk, bk, tk = f"tw.ok-{RUN}@1", f"tw-ok-{RUN}", f"票-tw-ok-{RUN}"
call("POST", "/入轨", {"版本": [{"开关键": f"tw.ok-{RUN}", "版本号": 1, "版本键": vk}]})
call("POST", "/分桶", {"桶键": bk, "开关键": f"tw.ok-{RUN}"})
call("POST", "/时间窗策略", {"收证口径": "以窗拒为准", "允许漂移秒": 300})
call("POST", "/下发", {"票号": tk, "版本键": vk, "桶键": bk, "下发时": iso(D)})

cids = []
for i, delta in enumerate((60, 120), 1):
    cid = f"证-ok-{RUN}-{i}"
    cids.append(cid)
    r = call("POST", "/回读", {
        "证号": cid, "票号": tk, "边缘键": f"edge-ok-{RUN}-{i}",
        "所见版本键": vk, "边缘时": iso(D + timedelta(seconds=delta)), "中心时": iso(C)})
    check(f"边缘{i} 窗内正式确认", r.get("正式确认") is True and r.get("valid") is True,
          f"{r.get('结果')} {r.get('窗裁决')}")
    check(f"边缘{i} 未校正", r.get("是否校正") is False)

fs = call("GET", f"/正式确认集?票号={urllib.parse.quote(tk)}")
check("正式确认数=2", fs.get("数量") == 2, str(fs.get("证号集")))
gate = call("POST", "/放量门", {"票号": tk, "要求边缘": [f"edge-ok-{RUN}-1", f"edge-ok-{RUN}-2"]})
check("齐套可放量", gate.get("可放量") is True, str(gate.get("缺失边缘")))
g = call("POST", "/贯验")
check("贯验通过", g.get("是否通过") is True, g.get("说明", ""))

print(f"\n[正常时序脚本] 票={tk}")
if fails:
    print(f"RESULT FAIL ({len(fails)}): {fails}"); sys.exit(1)
print("RESULT PASS · 正常时序两张回读均入正式确认集")
