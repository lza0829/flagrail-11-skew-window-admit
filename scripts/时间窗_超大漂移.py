#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间窗自动化 · 超大漂移脚本（与「逆序」脚本分开跑）。

硬约束：超过允许漂移 W=300s 时，早端（E 远早于 D）与晚端（E 远晚于 C）
都绝不可当确认 —— 即使切到「以中心校正收证为准」口径也必须硬拒。

断言（两种口径 × 两端）：
  * 回读 valid=False / 正式确认=False / 超漂移=True；
  * 正式确认集、放量门、贯验正式确认集均不含这些证；
  * 总览正式确认数不增加。

用法：python3 scripts/时间窗_超大漂移.py [BASE_URL]
退出码：0 全过；1 有失败。
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
W = 300
BIG = 3600  # 1h，远超 W


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


fails = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def wait_health(seconds=30):
    for _ in range(seconds * 2):
        try:
            call("GET", "/健康")
            return
        except Exception:
            time.sleep(0.5)
    print(f"FAIL 连不上后端 {BASE}", file=sys.stderr)
    sys.exit(2)


def main():
    wait_health()
    now = datetime.now(timezone.utc)
    D, C = now - timedelta(seconds=600), now

    # 先建链
    vk, bk = f"tw.over-{RUN}@1", f"tw-over-{RUN}"
    call("POST", "/入轨", {"版本": [{"开关键": f"tw.over-{RUN}", "版本号": 1, "版本键": vk}]})
    call("POST", "/分桶", {"桶键": bk, "开关键": f"tw.over-{RUN}", "规则": {"percent": 100}})

    all_cids = []
    for policy in ("以中心校正收证为准", "以窗拒为准"):
        call("POST", "/时间窗策略", {"收证口径": policy, "允许漂移秒": W})
        tk = f"票-tw-over-{RUN}-{policy[:2]}"
        call("POST", "/下发", {"票号": tk, "版本键": vk, "桶键": bk, "下发时": iso(D)})

        for end, E in (
            ("早端", D - timedelta(seconds=BIG)),
            ("晚端", C + timedelta(seconds=BIG)),
        ):
            cid = f"证-over-{RUN}-{policy[:2]}-{end}"
            ek = f"edge-over-{RUN}-{policy[:2]}-{end}"
            all_cids.append((tk, cid))
            before = call("GET", "/总览")["正式确认"]
            r = call("POST", "/回读", {
                "证号": cid, "票号": tk, "边缘键": ek, "所见版本键": vk,
                "边缘时": iso(E), "中心时": iso(C),
            })
            after = call("GET", "/总览")["正式确认"]
            tag = f"[{policy}/{end}]"
            check(f"{tag} 超漂移=True", r.get("超漂移") is True, str(r.get("超漂移")))
            check(f"{tag} valid=False", r.get("valid") is False, str(r.get("valid")))
            check(f"{tag} 正式确认=False", r.get("正式确认") is False)
            check(f"{tag} 结果非确认", r.get("结果") != "确认", str(r.get("结果")))
            check(f"{tag} 校正标记=False（超漂不可校正）", r.get("是否校正") is False)
            check(f"{tag} 总览正式数不增", after == before, f"{before}->{after}")

            h = call("GET", f"/核证/{urllib.parse.quote(cid)}")
            check(f"{tag} 核证 valid=false", h.get("valid") is False)
            check(f"{tag} 核证含边缘时/中心时", bool(h.get("边缘时")) and bool(h.get("中心时")))

            fs = call("GET", f"/正式确认集?票号={urllib.parse.quote(tk)}")
            check(f"{tag} 正式确认集为空", fs.get("数量") == 0, str(fs.get("证号集")))
            gate = call("GET", f"/放量门?票号={urllib.parse.quote(tk)}")
            check(f"{tag} 放量门排除该证",
                  any(x.get("证号") == cid for x in gate.get("超窗排除", [])))
            check(f"{tag} 放量门不可放量", gate.get("可放量") is False)

    g = call("POST", "/贯验")
    gset = set(g.get("正式确认集", []))
    check("贯验通过", g.get("是否通过") is True, g.get("说明", ""))
    check("贯验正式确认集不含任何超漂证", all(cid not in gset for _, cid in all_cids))

    print(f"\n[超大漂移脚本] 共 {len(all_cids)} 张两端 × 两口径超漂证")
    if fails:
        print(f"RESULT FAIL ({len(fails)}): {fails}")
        sys.exit(1)
    print("RESULT PASS · 超大漂移两端在两种口径下均未计入正式确认集合")


if __name__ == "__main__":
    main()
