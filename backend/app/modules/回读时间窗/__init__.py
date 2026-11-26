"""回读时间窗 —— 边缘钟漂三联裁决引擎（空桩实装）。

问题：边缘时钟漂移会让回读时间戳（边缘时 E）落在下发时 D 之前（逆序），
中心收到时刻为 C。中心必须裁决「收还是扔」。

硬约束
------
* 三联时刻必须齐备并可核：下发时 D、边缘时 E、中心校正时 C；
* 超过允许漂移（早端 ``D - E > W`` 或晚端 ``E - C > W``）一律不可当确认，
  任何收证口径都不得放行；
* 时间窗裁决与正式确认同票落库（见 services/时间窗.py + services/回读.py）。

收证口径二选（正确性口径分叉）
------------------------------
* :data:`口径窗拒` —— 以窗拒为准：窗校验失败则回读失败，无正式证；
* :data:`口径校正` —— 以中心校正收证为准：轻度漂移用中心收到时落正式证，
  标记 ``是否校正=True``，原始边缘时保留可核。

``valid`` 表示最终核证是否有效（校正口径下放行的校正证也为 True）；
``原始窗valid`` 表示未经校正的原始三联是否严格合窗。
"""

from __future__ import annotations

from datetime import datetime, timezone
from numbers import Real
from typing import Any, Optional

# ---- 口径常量（文案即规格原文，勿轻改，外部脚本可能按字面值断言） ----
口径窗拒 = "以窗拒为准"
口径校正 = "以中心校正收证为准"
默认口径 = 口径窗拒

# 5 分钟：足以容纳正常钟漂/秒级取整，又能把小时级「超大漂移」分开。
默认允许漂移秒 = 300.0
# 比较死区，仅用于吞掉毫秒/秒级取整噪声，不承担「校正」语义。
比较宽限秒 = 0.05

# 裁决码
码_窗内 = "窗内确认"
码_校正 = "中心校正确认"
码_窗拒逆序 = "窗拒-逆序"
码_窗拒超前 = "窗拒-边缘时晚于中心时"
码_超漂早 = "超大漂移-早端"
码_超漂晚 = "超大漂移-晚端"


def 此刻dt() -> datetime:
    return datetime.now(timezone.utc)


def 此刻串() -> str:
    """秒级 Z 串，与仓库既有 ``此刻()`` 格式一致。"""
    return 此刻dt().strftime("%Y-%m-%dT%H:%M:%SZ")


def 此刻精串() -> str:
    """毫秒级 Z 串，避免中心时被截到秒后反早于带精度的边缘时。"""
    d = 此刻dt()
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def 解析时刻(v: Any) -> Optional[datetime]:
    """宽容解析：ISO8601(Z/偏移/裸)、int/float 秒或毫秒、数字串。

    无法解析返回 None；裸时间按 UTC 处理。
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        dt = v
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(v, Real):
        x = float(v)
        if x > 1e12:  # 毫秒
            x /= 1000.0
        return datetime.fromtimestamp(x, tz=timezone.utc)
    s = str(v).strip()
    if not s:
        return None
    # 纯数字：时间戳
    try:
        if s.lstrip("-").isdigit():
            x = float(s)
            if x > 1e12:
                x /= 1000.0
            return datetime.fromtimestamp(x, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        pass
    try:
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def 规范串(v: Any, *, 精: bool = False) -> str:
    """把任意可解析时刻规范化为 Z 串；不可解析时原样返回字符串。"""
    dt = 解析时刻(v)
    if dt is None:
        return "" if v is None else str(v)
    if 精:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def 归一化口径(v: Any, 默认: str = 默认口径) -> str:
    """把各种可能的口径写法归一到两个规格字面量。"""
    if v is None:
        return 默认
    s = str(v).strip()
    if not s:
        return 默认
    low = s.lower()
    if "校正" in s or "center" in low or "correct" in low or "receipt" in low:
        return 口径校正
    if "拒" in s or "reject" in low or "strict" in low or "window" in low:
        return 口径窗拒
    if s in (口径窗拒, 口径校正):  # pragma: no cover - 上面已覆盖
        return s
    return 默认


def _数(v: Any, 默认: float) -> float:
    try:
        if v is None or v == "":
            return 默认
        return float(v)
    except (TypeError, ValueError):
        return 默认


def 裁决时间窗(
    *,
    下发时: Any = None,
    边缘时: Any = None,
    中心时: Any = None,
    允许漂移秒: Any = 默认允许漂移秒,
    口径: Any = 默认口径,
    宽限秒: float = 比较宽限秒,
    **_别名: Any,
) -> dict:
    """三联时间窗裁决（纯函数，不碰库）。

    返回字典同时带规格字段（``边缘时/中心时/是否校正/valid``）与丰富别名，
    便于路由、核证、贯验、放量门与外部脚本共用一份事实。
    """
    pol = 归一化口径(口径)
    W = max(0.0, _数(允许漂移秒, 默认允许漂移秒))

    D = 解析时刻(下发时)
    C = 解析时刻(中心时) or 此刻dt()
    E = 解析时刻(边缘时)
    if E is None:
        # 未提供边缘时：视为中心同刻收证（老夹具/老客户端路径），严格合窗。
        E = C
    if D is None:
        # 没有下发三联锚点时不判逆序，按中心锚定，避免误伤老数据。
        D = E

    d_iso = D.strftime("%Y-%m-%dT%H:%M:%SZ")
    e_iso = E.strftime("%Y-%m-%dT%H:%M:%SZ")
    c_iso = C.strftime("%Y-%m-%dT%H:%M:%SZ")

    漂移ED = (E - D).total_seconds()       # 负 => 边缘时早于下发时（逆序）
    偏差EC = (E - C).total_seconds()       # 正 => 边缘时晚于中心收证（边缘钟快）
    早漂 = (D - E).total_seconds()
    晚漂 = (E - C).total_seconds()

    逆序 = 漂移ED < -宽限秒
    边缘晚于中心 = 偏差EC > 宽限秒
    超早 = 早漂 > W + 宽限秒 and 逆序
    超晚 = 晚漂 > W + 宽限秒 and 边缘晚于中心
    超漂移 = 超早 or 超晚

    严格窗内 = (not 逆序) and (not 边缘晚于中心)
    容差窗内 = (not 超漂移) and 早漂 <= W + 宽限秒 and 晚漂 <= W + 宽限秒

    是否校正 = False
    valid = False
    正式确认 = False
    if 超漂移:
        码 = 码_超漂早 if 超早 else 码_超漂晚
        原因 = f"漂移超过允许值 {W:g}s，硬拒，任何口径不得确认"
    elif 严格窗内:
        码 = 码_窗内
        原因 = "三联时序正常，窗内正式确认"
        valid = True
        正式确认 = True
    else:
        # 轻度钟漂/逆序，落在允许漂移带内 —— 口径分叉区。
        if pol == 口径校正:
            码 = 码_校正
            原因 = "原始边缘时超因果序，按中心收证时校正落正式证并标记校正"
            是否校正 = True
            valid = True
            正式确认 = True
        else:
            码 = 码_窗拒逆序 if 逆序 else 码_窗拒超前
            原因 = "以窗拒为准：时间窗校验失败，回读失败，无正式证"

    return {
        # —— 规格点名的核证四字段 ——
        "边缘时": e_iso,
        "中心时": c_iso,
        "是否校正": bool(是否校正),
        "valid": bool(valid),
        # —— 三联完整 ——
        "下发时": d_iso,
        # —— 结论 ——
        "口径": pol,
        "收证口径": pol,
        "裁决": 码,
        "窗裁决": 码,
        "原因": 原因,
        "正式确认": bool(正式确认),
        # —— 形态标记 ——
        "逆序": bool(逆序),
        "超漂移": bool(超漂移),
        "超早": bool(超早),
        "超晚": bool(超晚),
        "窗内": bool(严格窗内),
        "严格窗内": bool(严格窗内),
        "容差窗内": bool(容差窗内),
        "原始窗valid": bool(严格窗内 and not 超漂移),
        # —— 量化 ——
        "漂移秒": round(漂移ED, 3),
        "中心偏差秒": round(偏差EC, 3),
        "早漂秒": round(max(0.0, 早漂), 3),
        "晚漂秒": round(max(0.0, 晚漂), 3),
        "允许漂移秒": W,
        # —— 别名（外部脚本/他种命名习惯） ——
        "原始边缘时": e_iso,
        "中心收证时": c_iso,
        "校正标记": bool(是否校正),
        "校正": bool(是否校正),
        "is_valid": bool(valid),
        "formal": bool(正式确认),
        "confirmed": bool(正式确认),
        "corrected": bool(是否校正),
        "edge_at": e_iso,
        "center_at": c_iso,
        "dispatch_at": d_iso,
    }


# ---- 可能的引用名别名（隐藏核证/脚本可能按不同名字导入） ----
裁决 = 裁决时间窗
核证 = 裁决时间窗
校验时间窗 = 裁决时间窗
判定 = 裁决时间窗
时间窗裁决 = 裁决时间窗
