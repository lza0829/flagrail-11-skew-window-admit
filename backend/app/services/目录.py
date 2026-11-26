from app.db import 连接
from app.services import 时间窗


def 总览() -> dict:
    conn = 连接()
    try:
        def c(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]

        正式确认 = c(f"SELECT COUNT(*) FROM 回读证 WHERE {时间窗.正式集条件}")
        校正确认 = c(
            f"SELECT COUNT(*) FROM 回读证 WHERE {时间窗.正式集条件} AND 是否校正=1"
        )
        时间窗拒绝 = c(
            "SELECT COUNT(*) FROM 回读证 WHERE 结果='时间窗拒绝' OR valid=0"
        )
        return {
            "开关版本": c("SELECT COUNT(*) FROM 开关版本"),
            "分桶规": c("SELECT COUNT(*) FROM 分桶规 WHERE 状态='生效'"),
            "下发票": c("SELECT COUNT(*) FROM 下发票"),
            "已下发": c("SELECT COUNT(*) FROM 下发票 WHERE 状态='已下发'"),
            "回读证": c("SELECT COUNT(*) FROM 回读证"),
            # 旧键保持：确认回读 == 正式确认集（超窗/逆序被拒证不计）。
            "确认回读": 正式确认,
            "正式确认": 正式确认,
            "校正确认": 校正确认,
            "时间窗拒绝": 时间窗拒绝,
            "命运条": c("SELECT COUNT(*) FROM 命运账"),
            "最近贯验通过": bool(
                (conn.execute(
                    "SELECT 是否通过 FROM 轨贯验 ORDER BY 编号 DESC LIMIT 1"
                ).fetchone() or [0])[0]
            ),
        }
    finally:
        conn.close()
