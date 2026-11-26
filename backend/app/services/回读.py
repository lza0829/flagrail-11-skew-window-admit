import json
import sqlite3
from datetime import datetime, timezone, timedelta

from app.db import 连接
from fastapi import HTTPException

from app.modules.回读时间窗 import 裁决时间窗, 解析时刻, 此刻精串
from app.services import 时间窗


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# 边缘时可能的入参名（规格名 + 常见别名，最后才是旧字段「回读时」）。
_边缘键名 = (
    "边缘时", "边缘时间", "边缘时间戳", "原始边缘时", "回读时间戳",
    "时间戳", "edge_at", "edge_time", "edge_ts", "timestamp", "ts",
    "回读时",
)
_中心键名 = (
    "中心时", "中心收证时", "中心校正时", "校正时", "center_at", "center_time",
)


def _取边缘入参(体: dict):
    for k in _边缘键名:
        v = 体.get(k)
        if v not in (None, ""):
            return v
    return None


def _取中心入参(体: dict):
    for k in _中心键名:
        v = 体.get(k)
        if v not in (None, ""):
            return v
    return None


def _解析三联(体: dict, ticket) -> tuple[str, str, str]:
    """返回 (下发时ISO, 边缘时原始/规范, 中心时ISO)。支持偏移描述符。"""
    D原始 = ticket["下发时"] or 此刻精串()
    Ddt = 解析时刻(D原始)

    C原始 = _取中心入参(体)
    Cdt = 解析时刻(C原始) if C原始 not in (None, "") else None
    if Cdt is None:
        Cdt = 解析时刻(此刻精串())

    E原始 = _取边缘入参(体)
    Edt = 解析时刻(E原始) if E原始 not in (None, "") else None

    # 偏移描述符（夹具用，加载时动态求值，保证任意日期都成立）
    if Edt is None:
        if 体.get("边缘距下发秒") not in (None, "") and Ddt is not None:
            Edt = Ddt + timedelta(seconds=float(体["边缘距下发秒"]))
        elif 体.get("边缘偏移中心秒") not in (None, ""):
            Edt = Cdt + timedelta(seconds=float(体["边缘偏移中心秒"]))
        elif 体.get("边缘偏移秒") not in (None, ""):
            Edt = Cdt + timedelta(seconds=float(体["边缘偏移秒"]))

    if Edt is None:
        # 老客户端/老夹具不带边缘时：边缘与中心同刻，严格合窗。
        Edt = Cdt
        E存 = ""
    else:
        # 保留调用方给出的原始字面值，核证可查「原始边缘时」。
        E存 = str(E原始) if E原始 not in (None, "") else ""

    Diso = Ddt.strftime("%Y-%m-%dT%H:%M:%SZ") if Ddt else str(D原始)
    Ciso = Cdt.strftime("%Y-%m-%dT%H:%M:%SZ")
    Eiso = Edt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # 原始列优先存字面输入；没有字面输入（偏移/同刻）时存规范 ISO。
    if not E存:
        E存 = Eiso
    return Diso, Eiso, Ciso, E存


def 记回读(体: dict) -> dict:
    conn = 连接()
    try:
        conn.execute("BEGIN IMMEDIATE")
        票号 = 体["票号"]
        ticket = conn.execute("SELECT * FROM 下发票 WHERE 票号=?", (票号,)).fetchone()
        if not ticket:
            raise HTTPException(400, f"下发票不存在:{票号}")
        if ticket["状态"] not in ("已下发", "回滚中"):
            raise HTTPException(400, f"票状态不可回读:{ticket['状态']}")

        边缘键 = 体["边缘键"]
        证号 = 体.get("证号") or f"证-{票号}-{边缘键}"
        所见 = 体.get("所见版本键") or ticket["版本键"]
        客户端结果 = 体.get("结果", "确认")

        Diso, Eiso, Ciso, E原始 = _解析三联(体, ticket)
        pol = 时间窗.读策略(conn, 体)
        裁 = 裁决时间窗(
            下发时=Diso, 边缘时=Eiso, 中心时=Ciso,
            允许漂移秒=pol["允许漂移秒"], 口径=pol["口径"],
        )

        # 版本拧花优先判偏差：即便时间窗有效，也不是正式确认。
        版本拧花 = 客户端结果 == "确认" and 所见 != ticket["版本键"]

        # 同票同边缘已有正式证（不同证号）=> 并发/重试双回读，不得双计。
        已有正式 = conn.execute(
            f"SELECT * FROM 回读证 WHERE 票号=? AND 边缘键=? "
            f"AND 证号<>? AND {时间窗.正式集条件} LIMIT 1",
            (票号, 边缘键, 证号),
        ).fetchone()

        双发去重 = 已有正式 is not None and 裁["正式确认"] and not 版本拧花

        if 版本拧花:
            结果 = "偏差"
            formal = False
        elif not 裁["正式确认"]:
            # 以窗拒为准 / 超大漂移：回读失败，无正式证。
            结果 = "时间窗拒绝"
            formal = False
        elif 双发去重:
            # 第二张同边缘证留痕但不计数。
            结果 = "并发去重"
            formal = False
        else:
            结果 = "确认"
            formal = True

        记录时 = 体.get("回读时") if 体.get("回读时") not in (None, "") else Ciso
        说明 = 体.get("说明", "")
        if 双发去重:
            说明 = (说明 + "；" if 说明 else "") + f"并发双回读去重，正式证={已有正式['证号']}"

        conn.execute(
            """INSERT INTO 回读证(
                 证号, 票号, 边缘键, 所见版本键, 结果, 回读时, 说明,
                 下发时, 边缘时, 原始边缘时, 中心时, 中心收证时,
                 是否校正, 校正标记, 校正, valid, 正式确认,
                 窗内, 逆序, 超漂移, 窗裁决, 收证口径, 漂移秒)
               VALUES (?,?,?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?,?, ?,?,?)
               ON CONFLICT(证号) DO UPDATE SET
                 所见版本键=excluded.所见版本键, 结果=excluded.结果,
                 回读时=excluded.回读时, 说明=excluded.说明,
                 下发时=excluded.下发时, 边缘时=excluded.边缘时,
                 原始边缘时=excluded.原始边缘时, 中心时=excluded.中心时,
                 中心收证时=excluded.中心收证时, 是否校正=excluded.是否校正,
                 校正标记=excluded.校正标记, 校正=excluded.校正,
                 valid=excluded.valid, 正式确认=excluded.正式确认,
                 窗内=excluded.窗内, 逆序=excluded.逆序, 超漂移=excluded.超漂移,
                 窗裁决=excluded.窗裁决, 收证口径=excluded.收证口径,
                 漂移秒=excluded.漂移秒""",
            (
                证号, 票号, 边缘键, 所见, 结果, 记录时, 说明,
                Diso, Eiso, E原始, Ciso, Ciso,
                1 if 裁["是否校正"] else 0,
                1 if 裁["是否校正"] else 0,
                1 if 裁["是否校正"] else 0,
                1 if formal else 0,
                1 if formal else 0,
                1 if 裁["窗内"] else 0,
                1 if 裁["逆序"] else 0,
                1 if 裁["超漂移"] else 0,
                裁["裁决"], pol["口径"], 裁["漂移秒"],
            ),
        )
        conn.commit()

        if 双发去重:
            返回 = 时间窗.序列化回读(
                conn.execute("SELECT * FROM 回读证 WHERE 证号=?", (证号,)).fetchone()
            )
            已有序 = 时间窗.序列化回读(已有正式)
            返回.update({
                "幂等": True,
                "并发去重": True,
                "双计": False,
                "已有正式证号": 已有正式["证号"],
                "正式确认": False,
                "valid": False,
                "结果": "并发去重",
                "正式证": 已有序,
            })
            return 返回

        row = conn.execute("SELECT * FROM 回读证 WHERE 证号=?", (证号,)).fetchone()
        out = 时间窗.序列化回读(row)
        out.update({
            "幂等": False,
            "并发去重": False,
            "双计": bool(formal),
            "窗裁决": 裁["裁决"],
            "原因": 裁["原因"],
        })
        return out
    except sqlite3.IntegrityError:
        # 部分唯一索引硬兜底：并发下另一张同边缘正式证已落。
        conn.rollback()
        try:
            已有 = conn.execute(
                f"SELECT * FROM 回读证 WHERE 票号=? AND 边缘键=? AND {时间窗.正式集条件} LIMIT 1",
                (体["票号"], 体["边缘键"]),
            ).fetchone()
            if 已有:
                out = 时间窗.序列化回读(已有)
                out.update({"幂等": True, "并发去重": True, "双计": False})
                return out
        except Exception:
            pass
        raise HTTPException(409, "并发回读冲突，正式确认唯一约束兜底")
    finally:
        conn.close()


def 装回读夹具(体: dict) -> dict:
    批次 = 体.get("批次编号") or f"回读-{此刻()}"
    结果 = []
    for item in 体.get("回读") or []:
        结果.append(记回读(item))
    conn = 连接()
    try:
        报告 = {"类型": "回读", "结果": 结果}
        conn.execute(
            "INSERT OR REPLACE INTO 装载批次(编号, 时刻, 报告) VALUES (?,?,?)",
            (批次, 此刻(), json.dumps(报告, ensure_ascii=False, default=str)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"批次编号": 批次, "报告": 报告}
