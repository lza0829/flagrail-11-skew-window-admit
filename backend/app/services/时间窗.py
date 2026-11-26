"""回读时间窗应用服务：策略、核证序列化、正式确认集与放量门。

裁决纯逻辑在 ``app.modules.回读时间窗``，本模块负责库与编排。
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from fastapi import HTTPException

from app.db import 连接
from app.modules.回读时间窗 import (
    默认允许漂移秒,
    默认口径,
    归一化口径,
    裁决时间窗,
    此刻串,
    此刻精串,
)

# 正式确认集的唯一口径：结果确认 + 正式标记 + valid。
正式集条件 = "结果='确认' AND 正式确认=1 AND valid=1"

_BOOL_COLS = (
    "是否校正", "校正标记", "校正", "valid", "正式确认",
    "窗内", "逆序", "超漂移",
)


def 读策略(conn=None, 体: Optional[dict] = None) -> dict:
    """解析当前时间窗策略。

    优先级：单次请求覆盖（体）> 时间窗策略当前行 > 站规键值 > 内置默认。
    """
    自有连接 = conn is None
    if 自有连接:
        conn = 连接()
    try:
        口径 = 默认口径
        漂移 = 默认允许漂移秒

        # 策略行为权威源；seed 的同步触发器保证直接 SQL 改任一同名列/站规键都汇到这里。
        row = conn.execute(
            "SELECT * FROM 时间窗策略 ORDER BY "
            "CASE 策略键 WHEN '默认' THEN 0 ELSE 1 END, "
            "当前 DESC, 更新时 DESC LIMIT 1"
        ).fetchone()
        if row:
            d = dict(row)
            口径 = (d.get("收证口径") or d.get("口径") or d.get("收证规则")
                    or d.get("策略") or 默认口径)
            漂移 = (d.get("允许漂移秒") or d.get("最大漂移秒")
                    or d.get("漂移容限秒") or 默认允许漂移秒)

        # 站规仅在策略行缺值时兜底（触发器会把站规直改回写策略行）。
        规 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 站规")}
        if not row:
            口径 = 规.get("回读时间窗收证口径") or 规.get("时间窗收证规则") or 口径
        try:
            漂移 = float(规.get("允许漂移秒", 漂移)) if not row else 漂移
        except (TypeError, ValueError):
            pass

        if 体:
            for k in ("收证口径", "口径", "口径策略", "收证规则", "策略口径", "policy"):
                if 体.get(k):
                    口径 = 体[k]
                    break
            for k in ("允许漂移秒", "漂移秒", "最大漂移秒", "漂移容限秒", "w"):
                if 体.get(k) not in (None, ""):
                    try:
                        漂移 = float(体[k])
                    except (TypeError, ValueError):
                        pass
                    break
        return {"口径": 归一化口径(口径), "允许漂移秒": float(漂移)}
    finally:
        if 自有连接:
            conn.close()


def 写策略(体: dict) -> dict:
    口径原始 = (
        体.get("收证口径") or 体.get("口径") or 体.get("收证规则")
        or 体.get("策略") or 默认口径
    )
    口径 = 归一化口径(口径原始)
    漂移 = 体.get("允许漂移秒", 体.get("最大漂移秒", 默认允许漂移秒))
    try:
        漂移 = float(漂移)
    except (TypeError, ValueError):
        漂移 = 默认允许漂移秒
    键 = 体.get("策略键") or 体.get("键") or "默认"
    t = 此刻串()

    conn = 连接()
    try:
        conn.execute(
            """INSERT INTO 时间窗策略(
                 策略键, 键, 口径, 收证口径, 收证规则, 策略,
                 允许漂移秒, 最大漂移秒, 漂移容限秒,
                 是否启用, 启用, 当前, 时刻, 更新时, 说明)
               VALUES (?,?,?,?,?,?,?,?,?,1,1,1,?,?,?)
               ON CONFLICT(策略键) DO UPDATE SET
                 键=excluded.键, 口径=excluded.口径, 收证口径=excluded.收证口径,
                 收证规则=excluded.收证规则, 策略=excluded.策略,
                 允许漂移秒=excluded.允许漂移秒, 最大漂移秒=excluded.最大漂移秒,
                 漂移容限秒=excluded.漂移容限秒, 更新时=excluded.更新时""",
            (键, 键, 口径, 口径, 口径, 口径, 漂移, 漂移, 漂移,
             t, t, 体.get("说明", "")),
        )
        # 站规镜像，给只读 /api/站规 与 KV 切换路径留一致口径。
        for k, v in {
            "回读时间窗收证口径": 口径,
            "时间窗收证规则": 口径,
            "允许漂移秒": str(int(漂移) if float(漂移).is_integer() else 漂移),
        }.items():
            conn.execute(
                "INSERT INTO 站规(键, 值) VALUES (?,?) "
                "ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (k, v),
            )
        conn.commit()
        return {"策略键": 键, "口径": 口径, "收证口径": 口径, "允许漂移秒": 漂移,
                "是否启用": True, "valid": True}
    finally:
        conn.close()


def 序列化回读(row: Any) -> dict:
    d = dict(row)
    for k in _BOOL_COLS:
        if k in d and d[k] is not None:
            d[k] = bool(d[k])
    边缘 = d.get("边缘时") or d.get("原始边缘时") or ""
    中心 = d.get("中心时") or d.get("中心收证时") or d.get("回读时") or ""
    d["边缘时"] = 边缘
    d["原始边缘时"] = d.get("原始边缘时") or 边缘
    d["中心时"] = 中心
    d["中心收证时"] = d.get("中心收证时") or 中心
    d["下发时"] = d.get("下发时") or ""
    校正 = bool(d.get("是否校正") or d.get("校正标记") or d.get("校正"))
    d["是否校正"] = 校正
    d["校正标记"] = 校正
    d["校正"] = 校正
    d["corrected"] = 校正
    formal = bool(d.get("正式确认")) and d.get("结果") == "确认" and bool(d.get("valid"))
    # 对外统一以「正式确认集」谓词为准，修正历史/并发去重留下的半态。
    d["正式确认"] = formal
    d["formal"] = formal
    d["confirmed"] = formal
    d["valid"] = bool(d.get("valid"))
    # 核证四字段之外的英文别名
    d["is_valid"] = d["valid"]
    d["edge_at"] = 边缘
    d["center_at"] = 中心
    d["dispatch_at"] = d["下发时"]
    return d


def 取核证(证号: str) -> dict:
    conn = 连接()
    try:
        r = conn.execute("SELECT * FROM 回读证 WHERE 证号=?", (证号,)).fetchone()
        if not r:
            raise HTTPException(404, f"核证不存在:{证号}")
        return 序列化回读(r)
    finally:
        conn.close()


def 列核证(证号: str = "", 票号: str = "", 边缘键: str = "",
           仅正式: bool = False, 限制: int = 200) -> list[dict]:
    sql = "SELECT * FROM 回读证 WHERE 1=1"
    args: list[Any] = []
    if 证号:
        sql += " AND 证号=?"; args.append(证号)
    if 票号:
        sql += " AND 票号=?"; args.append(票号)
    if 边缘键:
        sql += " AND 边缘键=?"; args.append(边缘键)
    if 仅正式:
        sql += f" AND {正式集条件}"
    sql += " ORDER BY 回读时 DESC, rowid DESC LIMIT ?"
    args.append(限制)
    conn = 连接()
    try:
        return [序列化回读(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def 正式确认集(conn=None, 票号: str = "") -> list[dict]:
    自有连接 = conn is None
    if 自有连接:
        conn = 连接()
    try:
        sql = f"SELECT * FROM 回读证 WHERE {正式集条件}"
        args: list[Any] = []
        if 票号:
            sql += " AND 票号=?"; args.append(票号)
        sql += " ORDER BY 证号"
        return [序列化回读(r) for r in conn.execute(sql, args)]
    finally:
        if 自有连接:
            conn.close()


def 评放量门(票号: str, 要求边缘: Optional[list[str]] = None) -> dict:
    """放量门：超窗/被拒证一律不进正式确认集；齐套才可放量。"""
    conn = 连接()
    try:
        t = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
        if not t:
            raise HTTPException(404, f"下发票不存在:{票号}")
        formal = 正式确认集(conn, 票号)
        rows = conn.execute(
            "SELECT * FROM 回读证 WHERE 票号=? ORDER BY rowid", (票号,)
        ).fetchall()
        all_proofs = [序列化回读(r) for r in rows]
        formal_ids = {p["证号"] for p in formal}
        excluded = [p for p in all_proofs if p["证号"] not in formal_ids]
        formal_edges = sorted({p["边缘键"] for p in formal})

        if 要求边缘:
            required = list(dict.fromkeys(要求边缘))
        else:
            # 无名册时，把任何上报过的边缘视为应确认边缘；被窗拒的边缘即缺口。
            required = sorted({p["边缘键"] for p in all_proofs})
        missing = [e for e in required if e not in set(formal_edges)]

        return {
            "票号": 票号,
            "可放量": not missing and len(formal) > 0,
            "通过": not missing and len(formal) > 0,
            "要求边缘": required,
            "缺失边缘": missing,
            "正式确认集": [p["证号"] for p in formal],
            "正式确认边缘": formal_edges,
            "正式确认证": formal,
            "正式确认数": len(formal),
            "校正确认集": [p["证号"] for p in formal if p["是否校正"]],
            "超窗排除": [
                {"证号": p["证号"], "边缘键": p["边缘键"], "裁决": p["窗裁决"],
                 "valid": p["valid"], "是否校正": p["是否校正"]}
                for p in excluded
            ],
            "排除数": len(excluded),
            "formal": [p["证号"] for p in formal],
        }
    finally:
        conn.close()


def 试裁决(体: dict) -> dict:
    """无状态核证：直接吃三联时刻给结论（也可给票号，从票补下发时）。"""
    d = 体.get("下发时") or 体.get("dispatch_at")
    if not d and 体.get("票号"):
        conn = 连接()
        try:
            t = conn.execute(
                "SELECT 下发时 FROM 下发票 WHERE 票号=?", (体["票号"],)
            ).fetchone()
            if t:
                d = t["下发时"]
        finally:
            conn.close()
    pol = 读策略(体=体)
    return 裁决时间窗(
        下发时=d,
        边缘时=体.get("边缘时", 体.get("edge_at")),
        中心时=体.get("中心时") or 体.get("中心收证时") or 体.get("center_at"),
        允许漂移秒=pol["允许漂移秒"],
        口径=体.get("收证口径") or 体.get("口径") or pol["口径"],
    )


# ---------------- 时间窗剧本夹具（UI/自动化共用） ----------------

def 装剧本夹具(体: dict) -> dict:
    """执行自描述时间窗剧本。

    剧本可含：口径/允许漂移秒、版本、分桶、下发（支持 ``下发于秒前``）、
    回读列表（支持 ``边缘距下发秒`` / ``边缘偏移中心秒``）。
    并发双回读剧本可用 ``并发双发: true`` + 两条同边缘不同证号的回读。
    """
    from app.services import 入轨, 分桶, 下发, 回读

    报告: dict[str, Any] = {"类型": "时间窗剧本", "步骤": []}
    if 体.get("口径") or 体.get("收证口径"):
        p = 写策略({
            "收证口径": 体.get("口径") or 体.get("收证口径"),
            "允许漂移秒": 体.get("允许漂移秒", 默认允许漂移秒),
        })
        报告["策略"] = p

    if 体.get("版本"):
        v = 入轨.入一批({"版本": 体["版本"]})
        报告["步骤"].append({"入轨": v.get("报告", v)})
    for b in 体.get("分桶") or []:
        报告["步骤"].append({"分桶": 分桶.写桶(b)})
    for d in 体.get("下发") or []:
        报告["步骤"].append({"下发": 下发.下一票(d)})

    reads = 体.get("回读") or []
    if 体.get("并发双发") and len(reads) >= 2:
        # 真并发：两条各自走 记回读（独立连接 + BEGIN IMMEDIATE 去重）。
        with ThreadPoolExecutor(max_workers=2) as ex:
            futs = [ex.submit(回读.记回读, item) for item in reads[:2]]
            outs = [f.result() for f in futs]
        outs += [回读.记回读(item) for item in reads[2:]]
    else:
        outs = [回读.记回读(item) for item in reads]
    报告["回读"] = outs

    票号 = 体.get("票号") or (体.get("下发") or [{}])[0].get("票号")
    if 票号:
        报告["放量门"] = 评放量门(票号)
        报告["核证"] = 列核证(票号=票号)
    批次 = 体.get("批次编号") or f"时间窗剧本-{此刻串()}"
    conn = 连接()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次, 此刻串(), json.dumps(报告, ensure_ascii=False, default=str)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"批次编号": 批次, "报告": 报告}
