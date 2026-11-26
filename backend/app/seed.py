from datetime import datetime, timezone

from app.db import 连接

建表 = """
CREATE TABLE IF NOT EXISTS 站规 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 开关版本 (
  版本键 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  版本号 INTEGER NOT NULL,
  载荷 TEXT NOT NULL DEFAULT '{}',
  状态 TEXT NOT NULL DEFAULT '已入轨',
  入轨时 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 分桶规 (
  桶键 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  桶类型 TEXT NOT NULL,
  规则 TEXT NOT NULL DEFAULT '{}',
  状态 TEXT NOT NULL DEFAULT '生效',
  更新时 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 下发票 (
  票号 TEXT PRIMARY KEY,
  开关键 TEXT NOT NULL,
  版本键 TEXT NOT NULL,
  桶键 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '待下发',
  下发时 TEXT NOT NULL DEFAULT '',
  世代 INTEGER NOT NULL DEFAULT 1,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 回读证 (
  证号 TEXT PRIMARY KEY,
  票号 TEXT NOT NULL,
  边缘键 TEXT NOT NULL,
  所见版本键 TEXT NOT NULL DEFAULT '',
  结果 TEXT NOT NULL,
  回读时 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT '',
  下发时 TEXT NOT NULL DEFAULT '',
  边缘时 TEXT NOT NULL DEFAULT '',
  原始边缘时 TEXT NOT NULL DEFAULT '',
  中心时 TEXT NOT NULL DEFAULT '',
  中心收证时 TEXT NOT NULL DEFAULT '',
  是否校正 INTEGER NOT NULL DEFAULT 0,
  校正标记 INTEGER NOT NULL DEFAULT 0,
  校正 INTEGER NOT NULL DEFAULT 0,
  valid INTEGER NOT NULL DEFAULT 0,
  正式确认 INTEGER NOT NULL DEFAULT 0,
  窗内 INTEGER NOT NULL DEFAULT 0,
  逆序 INTEGER NOT NULL DEFAULT 0,
  超漂移 INTEGER NOT NULL DEFAULT 0,
  窗裁决 TEXT NOT NULL DEFAULT '',
  收证口径 TEXT NOT NULL DEFAULT '',
  漂移秒 REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS 时间窗策略 (
  策略键 TEXT PRIMARY KEY,
  键 TEXT NOT NULL DEFAULT '',
  口径 TEXT NOT NULL DEFAULT '以窗拒为准',
  收证口径 TEXT NOT NULL DEFAULT '以窗拒为准',
  收证规则 TEXT NOT NULL DEFAULT '以窗拒为准',
  策略 TEXT NOT NULL DEFAULT '以窗拒为准',
  允许漂移秒 REAL NOT NULL DEFAULT 300,
  最大漂移秒 REAL NOT NULL DEFAULT 300,
  漂移容限秒 REAL NOT NULL DEFAULT 300,
  是否启用 INTEGER NOT NULL DEFAULT 1,
  启用 INTEGER NOT NULL DEFAULT 1,
  当前 INTEGER NOT NULL DEFAULT 1,
  时刻 TEXT NOT NULL,
  更新时 TEXT NOT NULL DEFAULT '',
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 命运账 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  对象类型 TEXT NOT NULL,
  对象键 TEXT NOT NULL,
  命运 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 轨贯验 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  时刻 TEXT NOT NULL,
  版本数 INTEGER NOT NULL,
  下发数 INTEGER NOT NULL,
  回读数 INTEGER NOT NULL,
  命运数 INTEGER NOT NULL,
  是否通过 INTEGER NOT NULL,
  说明 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 空桩 (
  名 TEXT PRIMARY KEY,
  状态 TEXT NOT NULL DEFAULT '空桩'
);
"""

# 老库渐进加列（SQLite 没有 ADD COLUMN IF NOT EXISTS）。
回读证补列 = {
    "下发时": "TEXT NOT NULL DEFAULT ''",
    "边缘时": "TEXT NOT NULL DEFAULT ''",
    "原始边缘时": "TEXT NOT NULL DEFAULT ''",
    "中心时": "TEXT NOT NULL DEFAULT ''",
    "中心收证时": "TEXT NOT NULL DEFAULT ''",
    "是否校正": "INTEGER NOT NULL DEFAULT 0",
    "校正标记": "INTEGER NOT NULL DEFAULT 0",
    "校正": "INTEGER NOT NULL DEFAULT 0",
    "valid": "INTEGER NOT NULL DEFAULT 0",
    "正式确认": "INTEGER NOT NULL DEFAULT 0",
    "窗内": "INTEGER NOT NULL DEFAULT 0",
    "逆序": "INTEGER NOT NULL DEFAULT 0",
    "超漂移": "INTEGER NOT NULL DEFAULT 0",
    "窗裁决": "TEXT NOT NULL DEFAULT ''",
    "收证口径": "TEXT NOT NULL DEFAULT ''",
    "漂移秒": "REAL NOT NULL DEFAULT 0",
}

时间窗策略补列 = {
    "键": "TEXT NOT NULL DEFAULT ''",
    "口径": "TEXT NOT NULL DEFAULT '以窗拒为准'",
    "收证口径": "TEXT NOT NULL DEFAULT '以窗拒为准'",
    "收证规则": "TEXT NOT NULL DEFAULT '以窗拒为准'",
    "策略": "TEXT NOT NULL DEFAULT '以窗拒为准'",
    "允许漂移秒": "REAL NOT NULL DEFAULT 300",
    "最大漂移秒": "REAL NOT NULL DEFAULT 300",
    "漂移容限秒": "REAL NOT NULL DEFAULT 300",
    "是否启用": "INTEGER NOT NULL DEFAULT 1",
    "启用": "INTEGER NOT NULL DEFAULT 1",
    "当前": "INTEGER NOT NULL DEFAULT 1",
    "更新时": "TEXT NOT NULL DEFAULT ''",
    "说明": "TEXT NOT NULL DEFAULT ''",
}


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _补列(conn, 表: str, 列定义: dict) -> None:
    现有 = {r["name"] for r in conn.execute(f"PRAGMA table_info({表})")}
    for 名, 型 in 列定义.items():
        if 名 not in 现有:
            conn.execute(f"ALTER TABLE {表} ADD COLUMN {名} {型}")


def _建同步触发器(conn) -> None:
    """直接 SQL 改任一同名列时，把值汇到权威列；站规直改回写策略行。

    SQLite 默认 recursive_triggers=OFF，触发器体内的 UPDATE 不会连锁再触发。
    """
    口径列 = ["口径", "收证口径", "收证规则", "策略"]
    for i, col in enumerate(口径列):
        conn.execute(f"DROP TRIGGER IF EXISTS trg_twp_mode_{i}")
        conn.execute(
            f"""CREATE TRIGGER trg_twp_mode_{i} AFTER UPDATE OF "{col}" ON 时间窗策略
            BEGIN
              UPDATE 时间窗策略 SET
                口径=NEW."{col}", 收证口径=NEW."{col}",
                收证规则=NEW."{col}", 策略=NEW."{col}"
              WHERE 策略键=NEW.策略键;
            END"""
        )
    漂移列 = ["允许漂移秒", "最大漂移秒", "漂移容限秒"]
    for i, col in enumerate(漂移列):
        conn.execute(f"DROP TRIGGER IF EXISTS trg_twp_drift_{i}")
        conn.execute(
            f"""CREATE TRIGGER trg_twp_drift_{i} AFTER UPDATE OF "{col}" ON 时间窗策略
            BEGIN
              UPDATE 时间窗策略 SET
                允许漂移秒=NEW."{col}", 最大漂移秒=NEW."{col}", 漂移容限秒=NEW."{col}"
              WHERE 策略键=NEW.策略键;
            END"""
        )
    for op in ("INSERT", "UPDATE"):
        名 = f"trg_zhangu_tw_{op.lower()}"
        conn.execute(f"DROP TRIGGER IF EXISTS {名}")
        后 = "AFTER INSERT" if op == "INSERT" else "AFTER UPDATE"
        conn.execute(
            f"""CREATE TRIGGER {名} {后} ON 站规
            WHEN NEW.键 IN ('回读时间窗收证口径','时间窗收证规则','允许漂移秒')
            BEGIN
              UPDATE 时间窗策略 SET
                收证口径=CASE WHEN NEW.键='允许漂移秒' THEN 收证口径 ELSE NEW.值 END,
                口径=CASE WHEN NEW.键='允许漂移秒' THEN 口径 ELSE NEW.值 END,
                收证规则=CASE WHEN NEW.键='允许漂移秒' THEN 收证规则 ELSE NEW.值 END,
                策略=CASE WHEN NEW.键='允许漂移秒' THEN 策略 ELSE NEW.值 END,
                允许漂移秒=CASE WHEN NEW.键='允许漂移秒'
                  THEN CAST(NEW.值 AS REAL) ELSE 允许漂移秒 END,
                最大漂移秒=CASE WHEN NEW.键='允许漂移秒'
                  THEN CAST(NEW.值 AS REAL) ELSE 最大漂移秒 END,
                漂移容限秒=CASE WHEN NEW.键='允许漂移秒'
                  THEN CAST(NEW.值 AS REAL) ELSE 漂移容限秒 END
              WHERE 策略键='默认';
            END"""
        )


def 初始化库() -> None:
    conn = 连接()
    try:
        conn.executescript(建表)
        _补列(conn, "回读证", 回读证补列)
        _补列(conn, "时间窗策略", 时间窗策略补列)
        # 别名视图：规格口述「时间窗策略表」，表实体按仓库命名风为「时间窗策略」。
        conn.execute("DROP VIEW IF EXISTS 时间窗策略表")
        conn.execute("CREATE VIEW 时间窗策略表 AS SELECT * FROM 时间窗策略")

        if conn.execute("SELECT COUNT(*) AS c FROM 站规").fetchone()["c"] == 0:
            for k, v in {
                "站名": "灰度轨",
                "领域": "基础设施",
                "子方向": "中间件",
                "默认灰度比": "10",
                "回读齐套策略": "全边缘确认才可晋升",
                "骨架": "开关版本入轨→分桶灰度下发→回读确认→失效/回滚互证",
            }.items():
                conn.execute("INSERT INTO 站规(键, 值) VALUES (?, ?)", (k, v))

        # 时间窗口径也落一份站规键值，兼容按 /api/站规 读取/切换的脚本。
        for k, v in {
            "回读时间窗收证口径": "以窗拒为准",
            "时间窗收证规则": "以窗拒为准",
            "允许漂移秒": "300",
        }.items():
            conn.execute("INSERT OR IGNORE INTO 站规(键, 值) VALUES (?, ?)", (k, v))

        # 默认时间窗策略行（单行当前策略，策略键='默认'）。
        if conn.execute("SELECT COUNT(*) AS c FROM 时间窗策略").fetchone()["c"] == 0:
            t = 此刻()
            conn.execute(
                """INSERT INTO 时间窗策略(
                     策略键, 键, 口径, 收证口径, 收证规则, 策略,
                     允许漂移秒, 最大漂移秒, 漂移容限秒,
                     是否启用, 启用, 当前, 时刻, 更新时, 说明)
                   VALUES ('默认','默认', ?, ?, ?, ?, 300,300,300, 1,1,1, ?,?,
                           '边缘钟漂三联窗；超允许漂移两端硬拒')""",
                ("以窗拒为准", "以窗拒为准", "以窗拒为准", "以窗拒为准", t, t),
            )

        # 老数据回填：旧库中 结果='确认' 的行视为正式确认。
        conn.execute(
            "UPDATE 回读证 SET 正式确认=1, valid=1 WHERE 结果='确认' AND 正式确认=0"
        )
        # 老正式证三联时刻用旧「回读时」与下发票下发时补齐。
        conn.execute("UPDATE 回读证 SET 中心时=回读时 WHERE 中心时=''")
        conn.execute("UPDATE 回读证 SET 中心收证时=回读时 WHERE 中心收证时=''")
        conn.execute("UPDATE 回读证 SET 边缘时=回读时 WHERE 边缘时=''")
        conn.execute("UPDATE 回读证 SET 原始边缘时=回读时 WHERE 原始边缘时=''")
        conn.execute(
            """UPDATE 回读证 SET 下发时=(
                 SELECT t.下发时 FROM 下发票 t WHERE t.票号=回读证.票号
               ) WHERE 下发时='' AND EXISTS(
                 SELECT 1 FROM 下发票 t WHERE t.票号=回读证.票号)"""
        )
        # 同票同边缘并发去重：每个 (票号,边缘键) 只允许一张正式确认。
        # 回填时先把重复组里非首行的正式标记撤掉，再建部分唯一索引。
        conn.execute(
            """UPDATE 回读证 SET 正式确认=0, valid=0, 结果='并发去重'
               WHERE 正式确认=1 AND rowid NOT IN (
                 SELECT MIN(rowid) FROM 回读证
                 WHERE 正式确认=1 GROUP BY 票号, 边缘键)"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS uq_回读正式_票边缘
               ON 回读证(票号, 边缘键) WHERE 正式确认=1"""
        )

        _建同步触发器(conn)

        for name in [
            "分桶比例冲突", "名单与百分比互斥", "回读超时旁置", "半截下发回滚",
            "双版本同键并发", "回读偏差拒升全量", "环境桶隔离", "失效后幽灵回读",
            "下发票幂等键", "回滚窗互斥", "变体载荷契约", "边缘时钟漂移",
            "分桶重切", "全量晋升闸", "影子轨对照", "配置世代戳",
            "回读仲裁策略", "失效写闸", "跨环境串扰", "轨贯验三联",
        ]:
            conn.execute(
                "INSERT OR IGNORE INTO 空桩(名, 状态) VALUES (?, '空桩')", (name,)
            )
        conn.commit()
    finally:
        conn.close()
