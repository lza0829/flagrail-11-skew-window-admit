# -*- coding: utf-8 -*-
"""回读时间窗（skew-window-admit）核证套件。

覆盖规格点名的夹具：逆序、正常时序、超大漂移两端不可当确认、并发双回读不双计，
以及两种收证口径的正确性分叉与核证四字段。
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from app.services import 回读


# ---------- 表结构交付物 ----------

def test_时间窗策略表_与_校正标记列_落库(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert "时间窗策略" in tables
    assert "时间窗策略表" in tables  # 口述名兼容视图
    cols = {r[1] for r in conn.execute("PRAGMA table_info(回读证)")}
    for c in ("边缘时", "中心时", "是否校正", "校正标记", "valid", "正式确认"):
        assert c in cols, f"回读证缺列 {c}"
    pcols = {r[1] for r in conn.execute("PRAGMA table_info(时间窗策略)")}
    assert "收证口径" in pcols and "允许漂移秒" in pcols
    # 默认口径必须是窗拒，保证「逆序默认不计入正式确认集」。
    val = conn.execute("SELECT 收证口径 FROM 时间窗策略 WHERE 策略键='默认'").fetchone()[0]
    assert val == "以窗拒为准"
    conn.close()


def test_核证四字段_纯引擎():
    from app.modules.回读时间窗 import 裁决时间窗
    r = 裁决时间窗(
        下发时="2026-01-01T00:10:00Z", 边缘时="2026-01-01T00:09:30Z",
        中心时="2026-01-01T00:20:00Z", 口径="以窗拒为准")
    for k in ("边缘时", "中心时", "是否校正", "valid"):
        assert k in r
    assert r["逆序"] is True and r["正式确认"] is False and r["valid"] is False


# ---------- 正常时序 ----------

def test_正常时序_正式确认(chain):
    c, iso, D, C = chain["client"], chain["iso"], chain["D"], chain["C"]
    for i, delta in enumerate((60, 120), 1):
        r = c.post("/api/回读", json={
            "证号": f"pt-ok-{i}", "票号": chain["票号"], "边缘键": f"e-ok-{i}",
            "所见版本键": chain["vk"],
            "边缘时": iso(D + __import__("datetime").timedelta(seconds=delta)),
            "中心时": iso(C)}).json()
        assert r["正式确认"] is True and r["valid"] is True
        assert r["是否校正"] is False
    fs = c.get("/api/正式确认集", params={"票号": chain["票号"]}).json()
    assert fs["数量"] == 2


# ---------- 逆序 + 口径分叉 ----------

def test_逆序_窗拒口径_无正式证且可区分(chain):
    from datetime import timedelta
    c, iso, D, C = chain["client"], chain["iso"], chain["D"], chain["C"]
    E = iso(D - timedelta(seconds=30))
    r = c.post("/api/回读", json={
        "证号": "pt-rev-a", "票号": chain["票号"], "边缘键": "e-rev",
        "所见版本键": chain["vk"], "边缘时": E, "中心时": iso(C)}).json()
    assert r["结果"] == "时间窗拒绝"
    assert r["正式确认"] is False and r["valid"] is False and r["逆序"] is True

    h = c.get("/api/核证/pt-rev-a").json()
    assert h["valid"] is False and h["是否校正"] is False
    assert h["边缘时"] == E and h["原始边缘时"] == E and h["中心时"]

    fs = c.get("/api/正式确认集", params={"票号": chain["票号"]}).json()
    assert "pt-rev-a" not in fs["证号集"] and fs["数量"] == 0
    gate = c.post("/api/放量门", json={"票号": chain["票号"]}).json()
    assert gate["可放量"] is False
    assert any(x["证号"] == "pt-rev-a" for x in gate["超窗排除"])


def test_逆序_校正口径_有校正正式证_原始边缘时可核(chain):
    from datetime import timedelta
    c, iso, D, C = chain["client"], chain["iso"], chain["D"], chain["C"]
    c.post("/api/时间窗策略", json={"收证口径": "以中心校正收证为准", "允许漂移秒": 300})
    E = iso(D - timedelta(seconds=30))
    r = c.post("/api/回读", json={
        "证号": "pt-rev-b", "票号": chain["票号"], "边缘键": "e-rev2",
        "所见版本键": chain["vk"], "边缘时": E, "中心时": iso(C)}).json()
    # 必须可区分：这次正式确认存在，但是校正证。
    assert r["正式确认"] is True and r["valid"] is True and r["是否校正"] is True
    h = c.get("/api/核证/pt-rev-b").json()
    assert h["是否校正"] is True and h["valid"] is True
    assert h["原始边缘时"] == E
    assert h["中心收证时"] and h["原始边缘时"] < h["中心收证时"]
    fs = c.get("/api/正式确认集", params={"票号": chain["票号"]}).json()
    assert "pt-rev-b" in fs["证号集"]


# ---------- 超大漂移两端，任何口径都不可确认 ----------

def test_超大漂移两端_两口径均硬拒(chain):
    from datetime import timedelta
    c, iso, D, C = chain["client"], chain["iso"], chain["D"], chain["C"]
    for policy in ("以窗拒为准", "以中心校正收证为准"):
        c.post("/api/时间窗策略", json={"收证口径": policy, "允许漂移秒": 300})
        for end, E in (("early", D - timedelta(hours=2)), ("late", C + timedelta(hours=2))):
            cid = f"pt-over-{policy[3]}-{end}"
            r = c.post("/api/回读", json={
                "证号": cid, "票号": chain["票号"], "边缘键": f"e-{cid}",
                "所见版本键": chain["vk"],
                "边缘时": iso(E), "中心时": iso(C)}).json()
            assert r["超漂移"] is True, (policy, end)
            assert r["正式确认"] is False and r["valid"] is False
            assert r["是否校正"] is False
            h = c.get(f"/api/核证/{cid}").json()
            assert h["valid"] is False
    fs = c.get("/api/正式确认集", params={"票号": chain["票号"]}).json()
    assert fs["数量"] == 0


# ---------- 并发双回读不得双计 ----------

def test_并发双回读_不同证号同边缘_只一张正式证(db_path, chain):
    from datetime import timedelta
    c, iso, D, C = chain["client"], chain["iso"], chain["D"], chain["C"]
    c.post("/api/时间窗策略", json={"收证口径": "以窗拒为准"})
    barrier = threading.Barrier(2)

    def put(i):
        barrier.wait()
        return 回读.记回读({
            "证号": f"pt-cc-{i}", "票号": chain["票号"], "边缘键": "same-edge",
            "所见版本键": chain["vk"],
            "边缘时": iso(D + timedelta(seconds=30 + i)), "中心时": iso(C)})

    with ThreadPoolExecutor(max_workers=2) as ex:
        outs = list(ex.map(put, (1, 2)))

    assert sum(1 for o in outs if o["正式确认"]) == 1
    fs = c.get("/api/正式确认集", params={"票号": chain["票号"]}).json()
    assert fs["数量"] == 1 and len(fs["证号集"]) == 1


def test_同体双击_同证号upsert_不双计(chain):
    from datetime import timedelta
    c, iso, D, C = chain["client"], chain["iso"], chain["D"], chain["C"]
    body = {"证号": "pt-http-cc", "票号": chain["票号"], "边缘键": "http-same",
            "所见版本键": chain["vk"],
            "边缘时": iso(D + timedelta(seconds=20)), "中心时": iso(C)}
    o1 = c.post("/api/回读", json=body).json()
    o2 = c.post("/api/回读", json=body).json()
    # 同证号 upsert，必然只有一行/一张正式证
    assert o1["证号"] == o2["证号"] == "pt-http-cc"
    assert o1["正式确认"] is True and o2["正式确认"] is True
    fs = c.get("/api/正式确认集", params={"票号": chain["票号"]}).json()
    assert fs["数量"] == 1


# ---------- 贯验协同 + 主链冒烟 ----------

def test_贯验不把超窗证计入_且主链通过(client):
    client.post("/api/装载/夹具?名=入轨样例")
    client.post("/api/装载/夹具?名=分桶样例")
    client.post("/api/装载/夹具?名=下发样例")
    client.post("/api/装载/夹具?名=回读样例")
    g = client.post("/api/贯验").json()
    assert g["是否通过"] is True, g["说明"]
    assert g["正式确认数"] == 2
    ov = client.get("/api/总览").json()
    assert ov["确认回读"] == 2 and ov["正式确认"] == 2


def test_站规切换口径_生效(chain):
    c = chain["client"]
    c.post("/api/站规", json={"回读时间窗收证口径": "以中心校正收证为准"})
    pol = c.get("/api/时间窗策略").json()
    assert pol["口径"] == "以中心校正收证为准"
