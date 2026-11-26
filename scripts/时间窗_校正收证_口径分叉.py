#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间窗自动化 · 口径分叉可区分性脚本。

同一笔轻度逆序回读：
 * 「以窗拒为准」   -> 无正式确认（正式确认集不含）；
 * 「以中心校正收证为准」-> 正式确认存在，是否校正=true，
                          核证保留原始边缘时与中心收证时。
另证：切到校正口径后，超大漂移仍不可当确认（硬约束不被口径覆盖）。

用法：python3 scripts/时间窗_校正收证_口径分叉.py [BASE_URL]
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
E_rev = D - timedelta(seconds=30)
vk, bk = f"tw.fork-{RUN}@1", f"tw-fork-{RUN}"
call("POST", "/入轨", {"版本": [{"开关键": f"tw.fork-{RUN}", "版本号": 1, "版本键": vk}]})
call("POST", "/分桶", {"桶键": bk, "开关键": f"tw.fork-{RUN}"})

# —— 口径 A：窗拒 ——
call("POST", "/时间窗策略", {"收证口径": "以窗拒为准", "允许漂移秒": 300})
tkA, cidA = f"票-forkA-{RUN}", f"证-forkA-{RUN}"
call("POST", "/下发", {"票号": tkA, "版本键": vk, "桶键": bk, "下发时": iso(D)})
rA = call("POST", "/回读", {"证号": cidA, "票号": tkA, "边缘键": f"eA-{RUN}",
                            "所见版本键": vk, "边缘时": iso(E_rev), "中心时": iso(C)})
check("A 口径逆序无正式确认", rA.get("正式确认") is False and rA.get("valid") is False)
setA = call("GET", f"/正式确认集?票号={urllib.parse.quote(tkA)}").get("证号集", [])
check("A 口径正式确认集不存在该证", cidA not in setA, str(setA))

# —— 口径 B：中心校正收证 ——
p = call("POST", "/时间窗策略", {"收证口径": "以中心校正收证为准", "允许漂移秒": 300})
check("策略可切到校正口径", p.get("口径") == "以中心校正收证为准", str(p))
tkB, cidB = f"票-forkB-{RUN}", f"证-forkB-{RUN}"
call("POST", "/下发", {"票号": tkB, "版本键": vk, "桶键": bk, "下发时": iso(D)})
rB = call("POST", "/回读", {"证号": cidB, "票号": tkB, "边缘键": f"eB-{RUN}",
                            "所见版本键": vk, "边缘时": iso(E_rev), "中心时": iso(C)})
check("B 口径逆序落正式确认", rB.get("正式确认") is True and rB.get("valid") is True,
      f"{rB.get('结果')} formal={rB.get('正式确认')}")
check("B 口径标记校正", rB.get("是否校正") is True)
hB = call("GET", f"/核证/{urllib.parse.quote(cidB)}")
check("核证 是否校正=true", hB.get("是否校正") is True)
check("核证含原始边缘时且等于输入", hB.get("原始边缘时") == iso(E_rev), hB.get("原始边缘时"))
check("核证含中心收证时", bool(hB.get("中心收证时")))
check("原始边缘时早于中心收证时（可核逆序）", hB.get("原始边缘时") < hB.get("中心收证时"))
setB = call("GET", f"/正式确认集?票号={urllib.parse.quote(tkB)}").get("证号集", [])
check("B 口径正式确认集含校正证", cidB in setB, str(setB))

# —— B 口径下超大漂移仍硬拒 ——
cidO = f"证-forkO-{RUN}"
rO = call("POST", "/回读", {"证号": cidO, "票号": tkB, "边缘键": f"eO-{RUN}",
                            "所见版本键": vk,
                            "边缘时": iso(D - timedelta(hours=2)), "中心时": iso(C)})
check("B 口径超大漂移仍不可确认",
      rO.get("正式确认") is False and rO.get("超漂移") is True and rO.get("是否校正") is False)

print(f"\n[口径分叉脚本] A票={tkA}  B票={tkB}")
if fails:
    print(f"RESULT FAIL ({len(fails)}): {fails}"); sys.exit(1)
print("RESULT PASS · 逆序后正式确认是否存在可按口径区分；超漂硬约束不变")
