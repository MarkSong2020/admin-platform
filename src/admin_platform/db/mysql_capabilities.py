"""MySQL 迁移前能力校验。

PostgreSQL → MySQL 迁移依赖三条实例/库级前提：
1. MySQL >= 8.0.16，否则 CHECK 约束会被静默忽略；
2. schema 默认 collation 为 ``utf8mb4_0900_bin``，否则 unique/check 比较会变成大小写不敏感。
3. 开启 binary logging 时需 ``log_bin_trust_function_creators=1``，否则迁移用户无法创建 trigger。
"""

from __future__ import annotations

from sqlalchemy.engine import Connection

MIN_MYSQL_CHECK_VERSION = (8, 0, 16)
REQUIRED_MYSQL_COLLATION = "utf8mb4_0900_bin"
_MYSQL_VERSION_COMPONENTS = 3
# app_locks.name 列最小宽度（须与 db.locks._LOCK_NAME_MAX_LENGTH 一致；utf8mb4 下单列索引
# ≤767B/4≈191）。健康校验据此拒绝列宽不足的既存表，防长锁名插入失败。
_APP_LOCK_NAME_LENGTH = 191


def parse_mysql_version(version: str) -> tuple[int, int, int]:
    """解析 MySQL 版本号；无法确认版本时拒绝继续迁移。"""
    prefix = version.split("-", maxsplit=1)[0]
    parts = prefix.split(".")
    if len(parts) < _MYSQL_VERSION_COMPONENTS:
        raise RuntimeError(f"无法解析 MySQL 版本号: {version}")
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError as exc:
        raise RuntimeError(f"无法解析 MySQL 版本号: {version}") from exc


def validate_mysql_capability_values(
    version: str,
    collation: str | None,
    *,
    log_bin_enabled: bool = False,
    trust_function_creators: bool = True,
) -> None:
    """校验 MySQL 版本、schema 默认 collation 与 trigger 创建前提。"""
    parsed_version = parse_mysql_version(version)
    if parsed_version < MIN_MYSQL_CHECK_VERSION:
        minimum = ".".join(str(part) for part in MIN_MYSQL_CHECK_VERSION)
        raise RuntimeError(
            f"MySQL 版本需 >= {minimum}，当前 {version}。低版本会静默忽略 CHECK 约束，"
            "定时调度去重和布尔约束不可靠。"
        )
    if collation != REQUIRED_MYSQL_COLLATION:
        raise RuntimeError(
            "MySQL database 默认 collation 必须是 "
            f"{REQUIRED_MYSQL_COLLATION}，当前 {collation!r}。否则 unique/check 会退化为"
            "大小写不敏感语义，无法等价 PostgreSQL。"
        )
    if log_bin_enabled and not trust_function_creators:
        raise RuntimeError(
            "MySQL 开启 binary logging 时必须设置 log_bin_trust_function_creators=1，"
            "否则 app 迁移用户无法创建用于 depts/menus self-parent 防护的 trigger。"
        )


def assert_app_locks_table_healthy(connection: Connection) -> None:
    """迁移后独立校验 app_locks 实际引擎/collation（纵深防御，codex 对抗审查 BLOCKING）。

    ``CREATE TABLE IF NOT EXISTS`` 不会修正既存错误表；0021 的幂等 ALTER 是主修正手段，本校验
    是独立确认层——非 InnoDB 会让 ``SELECT ... FOR UPDATE`` 行锁静默失效（应用级互斥不可靠），
    非 bin collation 会让锁名 PK 比较大小写不敏感（不同锁名误判为同一行）。非 MySQL 方言跳过；
    表尚未建（首次迁移前）跳过。
    """
    if connection.dialect.name != "mysql":
        return
    row = connection.exec_driver_sql(
        """
        SELECT ENGINE, TABLE_COLLATION
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'app_locks'
        """
    ).first()
    if row is None:
        return
    engine = str(row[0]) if row[0] is not None else ""
    collation = str(row[1]) if row[1] is not None else ""
    if engine.upper() != "INNODB":
        raise RuntimeError(
            f"app_locks 表引擎必须是 InnoDB，当前 {engine!r}。非事务引擎下 SELECT ... FOR UPDATE "
            "行锁静默失效，应用级事务锁不可靠。"
        )
    if collation != REQUIRED_MYSQL_COLLATION:
        raise RuntimeError(
            f"app_locks 表 collation 必须是 {REQUIRED_MYSQL_COLLATION}，当前 {collation!r}。"
            "否则锁名比较退化为大小写不敏感，可能把不同锁名误判为同一行。"
        )
    # 校验主键 = 单列 (name)（codex 第二轮：既存 InnoDB+bin 但缺 PK 的畸形表会被 CREATE IF NOT
    # EXISTS 跳过、ENGINE/collation 校验放行，但缺 PK 会让哨兵行可重复插入、FOR UPDATE 锁多行 →
    # 互斥语义失效）。PRIMARY KEY 在 STATISTICS 中 INDEX_NAME='PRIMARY'。
    pk_columns = [
        str(r[0])
        for r in connection.exec_driver_sql(
            """
            SELECT COLUMN_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'app_locks'
              AND INDEX_NAME = 'PRIMARY'
            ORDER BY SEQ_IN_INDEX
            """
        ).fetchall()
    ]
    if pk_columns != ["name"]:
        raise RuntimeError(
            f"app_locks 主键必须是单列 (name)，当前 {pk_columns!r}。缺主键会让锁哨兵行可重复插入，"
            "INSERT IGNORE / SELECT ... FOR UPDATE 的事务级互斥语义失效。"
        )
    # 校验 name 列结构（codex 第三轮）：既存 name VARCHAR(64) 会被 ENGINE/collation/PK 校验全放行，
    # 但 CREATE IF NOT EXISTS + ALTER ENGINE/CONVERT 都不扩列宽 → 长锁名(65-191)插入失败、业务偶发
    # 500。须独立查 COLUMNS 兜底列类型/宽度/可空/列 collation。
    column = connection.exec_driver_sql(
        """
        SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE, COLLATION_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'app_locks' AND COLUMN_NAME = 'name'
        """
    ).first()
    if column is None:
        raise RuntimeError("app_locks 缺少 name 列，锁哨兵表结构不完整。")
    data_type = str(column[0]).lower() if column[0] is not None else ""
    max_length = int(column[1]) if column[1] is not None else 0
    is_nullable = str(column[2]).upper() if column[2] is not None else ""
    name_collation = str(column[3]) if column[3] is not None else ""
    if data_type != "varchar" or max_length < _APP_LOCK_NAME_LENGTH:
        raise RuntimeError(
            f"app_locks.name 必须是 VARCHAR(>={_APP_LOCK_NAME_LENGTH})，"
            f"当前 {data_type}({max_length})。列宽不足会让长锁名插入失败。"
        )
    if is_nullable != "NO":
        raise RuntimeError("app_locks.name 必须 NOT NULL（NULL 锁名会绕过哨兵行唯一性）。")
    if name_collation != REQUIRED_MYSQL_COLLATION:
        raise RuntimeError(
            f"app_locks.name 列 collation 必须是 {REQUIRED_MYSQL_COLLATION}，当前 {name_collation!r}。"
        )


def assert_mysql_database_capabilities(connection: Connection) -> None:
    """迁移前校验 MySQL 版本与 schema collation；非 MySQL 方言跳过。"""
    if connection.dialect.name != "mysql":
        return
    version = str(connection.exec_driver_sql("SELECT VERSION()").scalar_one())
    collation = connection.exec_driver_sql(
        """
        SELECT DEFAULT_COLLATION_NAME
        FROM information_schema.SCHEMATA
        WHERE SCHEMA_NAME = DATABASE()
        """
    ).scalar_one_or_none()
    log_bin_enabled = bool(int(connection.exec_driver_sql("SELECT @@log_bin").scalar_one()))
    trust_function_creators = bool(
        int(connection.exec_driver_sql("SELECT @@log_bin_trust_function_creators").scalar_one())
    )
    validate_mysql_capability_values(
        version,
        str(collation) if collation is not None else None,
        log_bin_enabled=log_bin_enabled,
        trust_function_creators=trust_function_creators,
    )
