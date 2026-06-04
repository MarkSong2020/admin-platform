"""机检门禁：每个 ORM 列必须有中文 comment（数据建模标准，与模板同款）。

comment 双门禁的 **ORM 元数据层**：扫 ``Base.metadata`` 全部列，缺 comment 即红。
另一道 **schema-drift 层** —— ``make check-db``（alembic check 默认比对
``COMMENT ON COLUMN``）保证 model 的 comment 真落到迁移/DB。

mixin 继承列（``id`` / ``created_at`` / ``updated_at``）的 comment 由 ``IdMixin`` /
``TimestampMixin`` 统一提供，业务列由各表自己写 —— 本门禁不区分来源，只要求"每列都有"。
"""

from __future__ import annotations

import importlib
import pkgutil

import admin_platform.domains as _domains_pkg
from admin_platform.db.base import Base


def _load_all_domain_models() -> None:
    """import 每个 ``domains/<domain>/models.py``，把表注册进 ``Base.metadata``。

    自动发现：新增 domain 无需改本测试即被门禁覆盖。
    """
    for mod in pkgutil.iter_modules(_domains_pkg.__path__):
        if not mod.ispkg:
            continue
        try:
            importlib.import_module(f"admin_platform.domains.{mod.name}.models")
        except ModuleNotFoundError:
            # 该 domain 还没长出 models.py（仅 api/service 等）—— 跳过。
            continue


def test_every_orm_column_has_comment() -> None:
    _load_all_domain_models()
    missing = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if not column.comment
    ]
    assert not missing, (
        f"以下列缺中文 comment（数据建模标准要求每个业务列必带 comment，"
        f"mixin 列由 mixin 提供）：{missing}"
    )
