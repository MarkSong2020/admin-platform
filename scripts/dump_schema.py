"""从 ORM models 自省生成「数据模型速览」（docs/architecture/DATA_MODEL.md）。

真相源是 ``src/admin_platform/domains/*/models.py`` + ``db/base.py``（公共列/mixin）；
本脚本只把 ``Base.metadata`` 渲染成人读 markdown，**不是**另一个要手维护的副本。
表结构改动走 models + 迁移，然后 ``make schema-doc`` 重生本文件即可。

用法::

    uv run python scripts/dump_schema.py            # 写 docs/architecture/DATA_MODEL.md
    uv run python scripts/dump_schema.py --stdout    # 只打印，不落盘
    uv run python scripts/dump_schema.py --check      # 校验committed 文件是否最新（CI 友好，差异 → exit 1）

漂移守门分两层：本脚本的 ``--check`` 守「models → 本文档」；``make check-db``
（``alembic check``）守「models ↔ 迁移 ↔ 活库」。前者无需 DB，后者需 compose-up。
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from pathlib import Path

from sqlalchemy import (
    ForeignKeyConstraint,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql

import admin_platform.domains as _domains_pkg
from admin_platform.db.base import Base

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC_PATH = _REPO_ROOT / "docs" / "architecture" / "DATA_MODEL.md"
_PG = postgresql.dialect()


def _discover_models() -> None:
    """import 每个 ``domains/<domain>/models.py``，把表注册进 ``Base.metadata``。

    自动发现，新增 domain 无需改本脚本（与 ``migrations/env.py`` 的手工 import
    块互补：env.py 那份是迁移用的稳定契约，这份是文档用的零维护发现）。
    """
    for mod in pkgutil.iter_modules(_domains_pkg.__path__):
        if not mod.ispkg:
            continue
        try:
            importlib.import_module(f"admin_platform.domains.{mod.name}.models")
        except ModuleNotFoundError:
            # 该 domain 还没长出 models.py（仅 api/service 等）—— 跳过。
            continue
    # audit_events 在顶层 ``admin_platform.audit``（非 domains/），上面的 domains 自动发现扫不到 →
    # 显式补 import，否则审计表及其索引永远不进 DATA_MODEL.md（PK 审查发现的 dump_schema 范围缺陷，
    # 2026-06-15：审计是 append-only 取证轨，schema 文档须覆盖，与其余 domain 表一视同仁）。
    importlib.import_module("admin_platform.audit.models")


def _table_to_class() -> dict[str, type]:
    """表名 → ORM 类，用于标注来源 model。"""
    return {mapper.local_table.name: mapper.class_ for mapper in Base.registry.mappers}


def _col_type(column) -> str:
    """列类型按 PostgreSQL 方言渲染（部署目标），如 ``VARCHAR(64)`` / ``TIMESTAMP WITH TIME ZONE``。"""
    return column.type.compile(dialect=_PG)


def _col_default(column) -> str:
    """渲染列默认值：DB 侧 ``server_default`` 优先，其次 Python 侧 ``default``。"""
    if column.server_default is not None:
        return f"`{column.server_default.arg!s}` (DB)"
    if column.default is not None and not getattr(column.default, "is_callable", False):
        return f"`{column.default.arg!r}`"
    return "—"


def _render_table(table: Table, cls: type | None) -> str:
    lines: list[str] = []
    lines.append(f"### `{table.name}`")
    lines.append("")

    # 来源 model。
    if cls is not None:
        lines.append(f"> 来源 model：`{cls.__module__}.{cls.__qualname__}`")
        lines.append("")

    # 列表格。
    lines.append("| 列 | 类型 | 空 | 默认 | 描述 | 备注 |")
    lines.append("|---|---|---|---|---|---|")
    for column in table.columns:
        nullable = "NULL" if column.nullable else "NOT NULL"
        note = "PK" if column.primary_key else ""
        desc = column.comment or "—"
        lines.append(
            f"| `{column.name}` | {_col_type(column)} | {nullable} | {_col_default(column)} | {desc} | {note} |"
        )
    lines.append("")

    # 约束 / 索引（PK 已在备注，这里列复合约束与索引）。
    extras: list[str] = []
    # H7：约束/索引名可能为空（列级 unique=True / 未命名 FK），仅按 name 排序时 tie-break 落到
    # set 迭代顺序（受 PYTHONHASHSEED 影响 → --check 随机 pass/fail）。补列名做确定性 tie-break。
    uniques = sorted(
        (c for c in table.constraints if isinstance(c, UniqueConstraint)),
        key=lambda c: (c.name or "", tuple(col.name for col in c.columns)),
    )
    for uq in uniques:
        cols = ", ".join(col.name for col in uq.columns)
        label = f"`{uq.name}`" if uq.name else "（列级 `unique=True`，DDL 由 PG 自动命名）"
        extras.append(f"- UNIQUE {label}：({cols})")
    fks = sorted(
        (c for c in table.constraints if isinstance(c, ForeignKeyConstraint)),
        key=lambda c: (
            c.name or "",
            tuple(c.column_keys),
            tuple(el.target_fullname for el in c.elements),
        ),
    )
    for fk in fks:
        local = ", ".join(fk.column_keys)
        target = ", ".join(el.target_fullname for el in fk.elements)
        extras.append(f"- FK `{fk.name}`：({local}) → {target}")
    for idx in sorted(
        table.indexes, key=lambda i: (i.name or "", tuple(col.name for col in i.columns))
    ):
        cols = ", ".join(col.name for col in idx.columns)
        uniq = " UNIQUE" if idx.unique else ""
        extras.append(f"- INDEX{uniq} `{idx.name}`：({cols})")

    if extras:
        lines.append("约束 / 索引：")
        lines.append("")
        lines.extend(extras)
        lines.append("")

    return "\n".join(lines)


def _render() -> str:
    _discover_models()
    cls_map = _table_to_class()
    tables = Base.metadata.sorted_tables  # 依赖顺序：被引用表在前

    header = (
        "# 数据模型速览（DATA_MODEL）\n"
        "\n"
        "> ⚠️ **生成物，请勿手改。** 本文件由 `scripts/dump_schema.py` 从 ORM models 自省生成。\n"
        "> **真相源 = `src/admin_platform/domains/*/models.py` + `db/base.py`（公共列/mixin）**；\n"
        "> 物化 DDL 见 `migrations/versions/`。改表结构 → 改 models + 迁移 → `make schema-doc` 重生本文件。\n"
        ">\n"
        "> - 再生：`make schema-doc`（= `uv run python scripts/dump_schema.py`）\n"
        "> - 校验是否最新：`uv run python scripts/dump_schema.py --check`（差异即非零退出）\n"
        "> - 类型以 PostgreSQL 方言渲染；models↔迁移↔活库的漂移由 `make check-db` 守门。\n"
        "\n"
    )

    # 表清单速览。
    toc_lines = ["## 表清单", ""]
    for table in tables:
        toc_lines.append(f"- [`{table.name}`](#{table.name})（{len(table.columns)} 列）")
    toc_lines.append("")

    body = ["## 表结构", ""]
    for table in tables:
        body.append(_render_table(table, cls_map.get(table.name)))

    return header + "\n".join(toc_lines) + "\n" + "\n".join(body).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="从 ORM models 生成数据模型速览")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--stdout", action="store_true", help="只打印到 stdout，不落盘")
    group.add_argument(
        "--check",
        action="store_true",
        help="校验 committed 文件是否与 models 一致（差异 → exit 1，不写文件）",
    )
    args = parser.parse_args()

    content = _render()

    if args.stdout:
        sys.stdout.write(content)
        return 0

    if args.check:
        if not _DOC_PATH.exists():
            print(f"✘ {_DOC_PATH.relative_to(_REPO_ROOT)} 不存在，请先跑 `make schema-doc`")
            return 1
        current = _DOC_PATH.read_text(encoding="utf-8")
        if current != content:
            print(
                f"✘ {_DOC_PATH.relative_to(_REPO_ROOT)} 与 models 不一致 —— "
                "请跑 `make schema-doc` 重生后提交"
            )
            return 1
        print(f"✓ {_DOC_PATH.relative_to(_REPO_ROOT)} 与 models 一致")
        return 0

    _DOC_PATH.write_text(content, encoding="utf-8")
    print(f"✓ 已写 {_DOC_PATH.relative_to(_REPO_ROOT)}（{len(Base.metadata.tables)} 张表）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
