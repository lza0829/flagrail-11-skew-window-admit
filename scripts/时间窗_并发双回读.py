#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间窗自动化 · 并发双回读不得双计。

两个线程同时 POST 同一(票号, 边缘键)、不同证号的回读；
无论存储层谁先谁后，/api/正式确认集 中该边缘只能有一张正式证。

用法：python3 scripts/时间窗_并发双回读.py [BASE_URL]
"""
import json
import os
import sys
import threading
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
vk, bk, tk = f"tw.cc-{RUN}@1", f"tw-cc-{RUN}", f"票-tw-cc-{RUN}"
ek = f"edge-cc-{RUN}"
call("POST", "/入轨", {"版本": [{"开关键": f"tw.cc-{RUN}", "版本号": 1, "版本键": vk}]})
call("POST", "/分桶", {"桶键": bk, "开关键": f"tw.cc-{RUN}"})
call("POST", "/时间窗策略", {"收证口径": "以窗拒为准", "允许漂移秒": 300})
call("POST", "/下发", {"票号": tk, "版本键": vk, "桶键": bk, "下发时": iso(D)})

barrier = threading.Barrier(2)
outs = [None, None]


def hit(i):
    barrier.wait()  # 尽量同时发出，制造真并发
    outs[i] = call("POST", "/回读", {
        "证号": f"证-cc-{RUN}-{i}", "票号": tk, "边缘键": ek,
        "所见版本键": vk, "边缘时": iso(D + timedelta(seconds=30 + i)), "中心时": iso(C)})


ts = [threading.Thread(target=hit, args=(i,)) for i in range(2)]
[t.start() for t in ts]; [t.join() for t in ts]

formal_flags = [bool(o.get("正式确认")) for o in outs]
print("两个并发响应正式标记:", formal_flags, "去重标记:",
      [o.get("并发去重") for o in outs])
check("恰好一个响应是正式确认", sum(formal_flags) == 1, str(formal_flags))
check("另一个被并发去重/幂等",
      any(o.get("并发去重") or o.get("幂等") for o in outs))

fs = call("GET", f"/正式确认集?票号={urllib.parse.quote(tk)}")
check("正式确认集数量恰为 1", fs.get("数量") == 1, str(fs.get("证号集")))

# 再来一次完全同体的双击（同默认证号），仍不得双计
body = {"票号": tk, "边缘键": f"edge-samebody-{RUN}", "所见版本键": vk,
        "边缘时": iso(D + timedelta(seconds=40)), "中心时": iso(C)}
b1 = call("POST", "/回读", body)
b2 = call("POST", "/回读", body)
fs2 = call("GET", f"/正式确认集?票号={urllib.parse.quote(tk)}")
edge_formal = [x for x in fs2.get("正式确认集", []) if True]
check("同体双击后该票正式集=2（每边缘一张）", fs2.get("数量") == 2, str(fs2.get("证号集")))
check("同体双击返回同证号", b1.get("证号") == b2.get("证号"))

g = call("POST", "/贯验")
check("贯验通过且无双计问题", g.get("是否通过") is True, g.get("说明", ""))

print(f"\n[并发双回读脚本] 票={tk}")
if fails:
    print(f"RESULT FAIL ({len(fails)}): {fails}"); sys.exit(1)
print("RESULT PASS · 并发双回读未双计")
