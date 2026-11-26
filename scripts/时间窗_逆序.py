#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间窗自动化 · 逆序脚本（与「超大漂移」脚本分开跑）。

口径：以窗拒为准（默认）。
断言：边缘时落在下发前（轻度逆序，未超允许漂移）时——
  1) 回读响应 valid=False / 正式确认=False；
  2) /api/核证 中该证 valid=false，三联时刻齐备且 逆序=true；
  3) /api/正式确认集 与 /api/放量门 的正式确认集合都不含它；
  4) 贯验通过且正式确认数不增加该证。

用法：python3 scripts/时间窗_逆序.py [BASE_URL]
环境：FLAGRAIL_BASE（默认 http://127.0.0.1:11800）
退出码：0 全过；1 有断言/连接失败。
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FLAGRAIL_BASE", "http://127.0.0.1:11800")).rstrip("/")
RUN = datetime.now(timezone.utc).strftime("%H%M%S") + f"-{os.getpid()}"
VK, BK, TK = f"tw.rev-{RUN}@1", f"tw-rev-{RUN}", f"票-tw-rev-{RUN}"
EK, CID = f"edge-rev-{RUN}", f"证-tw-rev-{RUN}"
W = 300


def call(method, path, body=None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + "/api" + urllib.parse.quote(path, safe="/?=&%+:"), data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def wait_health(seconds=30):
    for _ in range(seconds * 2):
        try:
            call("GET", "/健康")
            return
        except Exception:
            time.sleep(0.5)
    print(f"FAIL 连不上后端 {BASE}", file=sys.stderr)
    sys.exit(2)


fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    wait_health()
    now = datetime.now(timezone.utc)
    D, C = now - timedelta(seconds=600), now
    E = D - timedelta(seconds=30)  # 逆序 30s，在 W=300 带内

    call("POST", "/入轨", {"版本": [{"开关键": f"tw.rev-{RUN}", "版本号": 1, "版本键": VK}]})
    call("POST", "/分桶", {"桶键": BK, "开关键": f"tw.rev-{RUN}", "规则": {"percent": 100}})
    call("POST", "/时间窗策略", {"收证口径": "以窗拒为准", "允许漂移秒": W})
    call("POST", "/下发", {"票号": TK, "版本键": VK, "桶键": BK, "下发时": iso(D)})

    before = call("GET", "/总览")["正式确认"]
    resp = call("POST", "/回读", {
        "证号": CID, "票号": TK, "边缘键": EK, "所见版本键": VK,
        "边缘时": iso(E), "中心时": iso(C),
    })
    after = call("GET", "/总览")["正式确认"]

    check("逆序响应结果非确认", resp.get("结果") != "确认", str(resp.get("结果")))
    check("逆序响应 valid=False", resp.get("valid") is False, str(resp.get("valid")))
    check("逆序响应 正式确认=False", resp.get("正式确认") is False)
    check("标记 逆序=True", resp.get("逆序") is True)
    check("未误判超大漂移", resp.get("超漂移") is False)
    check("总览正式确认数不增加", after == before, f"{before}->{after}")

    h = call("GET", f"/核证?证号={urllib.parse.quote(CID)}")[0]
    for k in ("边缘时", "中心时", "是否校正", "valid"):
        check(f"核证含字段 {k}", k in h)
    check("核证 valid=false", h.get("valid") is False)
    check("核证 是否校正=false", h.get("是否校正") is False)
    check("核证保留原始边缘时", bool(h.get("边缘时")) and h.get("边缘时") == iso(E))
    check("核证含中心时", bool(h.get("中心时")))

    fs = call("GET", f"/正式确认集?票号={urllib.parse.quote(TK)}")
    check("正式确认集不含逆序证", CID not in fs.get("证号集", []), str(fs.get("证号集")))
    check("该票正式确认数=0", fs.get("数量") == 0, str(fs.get("数量")))

    gate = call("GET", f"/放量门?票号={urllib.parse.quote(TK)}")
    check("放量门正式确认集为空", gate.get("正式确认集") == [], str(gate.get("正式确认集")))
    check("放量门不可放量", gate.get("可放量") is False)
    check("放量门超窗排除含该证", any(x.get("证号") == CID for x in gate.get("超窗排除", [])))

    g = call("POST", "/贯验")
    check("贯验仍通过（被拒证不是不一致）", g.get("是否通过") is True, g.get("说明", ""))
    check("贯验正式确认集不含逆序证", CID not in g.get("正式确认集", []))

    print(f"\n[逆序脚本] 票={TK} 证={CID}")
    if fails:
        print(f"RESULT FAIL ({len(fails)}): {fails}")
        sys.exit(1)
    print("RESULT PASS · 逆序回读后无正式确认，且全程未计入正式确认集合")


if __name__ == "__main__":
    main()
