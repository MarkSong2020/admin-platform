"""分页 / 排序基础设施 —— 共享的 Query 别名 + total_pages 计算 + 防注入排序 helper。

各业务域的列表端点曾各自重复定义 ``PageQ`` / ``SizeQ``（约束一致但 description 文案漂移
出 3 个版本），各 service 的 ``list_`` 也重复同一段 ``total_pages`` 计算。此模块作为单一真相
源收口这两处重复。约束沿用现状（``PageQ`` ge=1/le=10000，``SizeQ`` ge=1/le=100），仅统一
description 文案；分页行为零变更。

排序（对标 RuoYi 列表端点 orderByColumn / isAsc）—— ``OrderByQ`` / ``OrderQ`` 是排序的
Query 别名，``apply_sort`` 是统一的**防注入**落地点：repository 维护**每个域自己的
allowlist**（``{字段名: ORM Column}``），``order_by`` 字符串只用于查 allowlist，命中才把对应
ORM Column 喂给 ``stmt.order_by``——绝不把客户端字符串拼进 SQL / ``text()``。不在 allowlist
→ 抛 422（``framework.SORT_FIELD_INVALID``，明确反馈而非静默回退）。

分层说明：``core`` 是被 ``api`` / ``service`` 依赖的基础设施层（同 ``core.auth`` /
``core.errors``），import-linter 契约允许；``core`` 可 import fastapi / sqlalchemy / 抛
``AppError``（``core.errors`` 已是）。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Literal

from fastapi import Query
from sqlalchemy import ColumnElement, ColumnExpressionArgument
from sqlalchemy.orm.attributes import InstrumentedAttribute

from admin_platform.core.errors import AppError

# 排序列类型别名（两类，语义不同）：
#   * ``SortColumn`` —— allowlist 的值：ORM ``Mapped`` 列（``InstrumentedAttribute``），它有
#     ``.asc()`` / ``.desc()``，``resolve_sort`` 据 order 方向产出排序表达式。
#   * ``SortExpr`` —— ``order_by()`` 接受的官方入参联合（``ColumnExpressionArgument``）：既容纳
#     bare 列（default 用），又容纳 ``.asc()`` / ``.desc()`` 产出的 ``UnaryExpression``。
# 用 Mapping/Sequence（协变）标注容器，避免 list/dict 不变性把具体列类型误报为不兼容。
SortColumn = InstrumentedAttribute[Any]
SortExpr = ColumnExpressionArgument[Any]

# 列表端点的页码 / 每页条数 Query 别名（单一真相源）。
# le=10000 防深分页 DoS（OFFSET 过大拖垮 DB）；le=100 限制单页负载。
PageQ = Annotated[
    int, Query(ge=1, le=10000, description="页码（从 1 开始，上限 10000 防深分页 DoS）")
]
SizeQ = Annotated[int, Query(ge=1, le=100, description="每页条数（上限 100）")]
# 日志类端点（operlog/logininfor 等 append-only 高增长表）专用更低页码上限：OFFSET 深翻页在百万级
# 日志表上「扫描+丢弃前 N 行」代价远高于体量小的业务表，le=500 收窄 blast radius（PK 项3；
# 任意页跳转 + 精确 total 仍保留，cursor/seek 分页排期 P6 与前端日志页契约一起定）。
LogPageQ = Annotated[int, Query(ge=1, le=500, description="日志页码（从 1 开始，上限 500）")]

# 排序方向取值（对标 RuoYi isAsc）。用 Literal 进 OpenAPI → 客户端只能传 asc / desc，
# 非法值在 FastAPI 入口 422，不会进到 repository。
OrderValue = Literal["asc", "desc"]
# 排序 Query 别名。``order_by`` 是逻辑字段名（非 ORM 列名，由 allowlist 映射）；None=用各域默认。
# ``order`` 默认 desc——列表多按 created_at 排，最新在前（对标 RuoYi 时间列倒序习惯）。
OrderByQ = Annotated[
    str | None, Query(max_length=64, description="排序字段（须在该端点允许的字段集合内）")
]
OrderQ = Annotated[OrderValue, Query(description="排序方向（asc / desc，默认 desc）")]

SORT_FIELD_INVALID_CODE = "framework.SORT_FIELD_INVALID"


def like_contains(keyword: str) -> str:
    """把搜索关键字转义成「包含」LIKE 模式 ``%kw%``，转义 LIKE 元字符 ``\\`` / ``%`` / ``_``。

    ``Column.ilike`` 走 bind param（无 SQL 注入），但 ``%`` / ``_`` 作 LIKE 通配符**仍生效**——用户搜
    字面 ``a_b`` / ``50%`` 会被当通配匹配，结果失真（``%``-only 还强制 leading-wildcard 全表扫）。本
    helper 先把 ``\\`` / ``%`` / ``_`` 按 ``\\`` 转义再包 ``%...%``，配合 ``ilike(pattern, escape='\\')``
    令元字符按字面匹配。转义顺序：**先 ``\\`` 再 ``%`` / ``_``**（避免把后插入的反斜杠二次转义）。
    """
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def ilike_contains(column: InstrumentedAttribute[Any], keyword: str) -> ColumnElement[bool]:
    """构造转义元字符的「包含」匹配条件 ``column ILIKE %kw% ESCAPE '\\'``（防 LIKE 通配符语义污染）。

    各 repo search 收口到此单一 helper：调它即转义 + 传 ``escape``，**无法忘记**（防御一致，杜绝
    某个 repo 漏转义）。``keyword`` 走 bind param，叠加 ``like_contains`` 的元字符转义，字面安全。
    """
    return column.ilike(like_contains(keyword), escape="\\")


def compute_total_pages(total: int, size: int) -> int:
    """根据总条数与每页条数计算总页数。

    向上取整：``ceil(total / size)``。``size`` 为 0 时返回 0（防御除零；实际
    ``SizeQ`` 约束 ge=1，正常路径不会传 0）。

    :param total: 记录总数（非负）。
    :param size: 每页条数。
    :return: 总页数；``total`` 为 0 时返回 0。
    """
    return (total + size - 1) // size if size > 0 else 0


def resolve_sort(
    order_by: str | None,
    order: OrderValue,
    *,
    allowed: Mapping[str, SortColumn],
    default: Sequence[SortExpr],
    tie_break: SortColumn | None = None,
) -> list[SortExpr]:
    """按 allowlist 把 ``order_by`` 解析成 ORDER BY 列表（**防注入**，在 service 层调用）。

    **防注入红线**：``order_by`` 是不可信客户端字符串，只用作 ``allowed`` 字典的 key 查 ORM
    Column——命中才排序，**绝不**把字符串本身拼进 SQL / 传给 ``text()``。不在 allowlist（含
    构造的注入串如 ``"id; DROP TABLE"`` / 未授权列如 ``"password_hash"``）→ 抛 422，明确拒绝。

    放在 service 层调用（service 可抛 ``AppError``，repository 不抛——分层契约 C3）：service 解析
    出经校验的 ORDER BY 列表，再传给 repository 拼进 ``stmt.order_by``。

    **稳定排序（tie-break）**：显式 ``order_by`` 命中非唯一列（如 ``sort_order`` / ``created_at``
    可重复）时只产单列 ORDER BY，OFFSET 深分页会跨页跳行 / 重复。传 ``tie_break``（各域唯一列，
    一般是 pk ``id``）→ 在显式排序列之后追加该列作稳定 tie-breaker（已是同列时不重复追加）。
    ``order_by=None`` 走 ``default``（默认序已自带 tiebreaker），不叠加。

    :param order_by: 客户端传入的逻辑字段名；``None`` → 返回 ``default``（各域稳定默认序）。
    :param order: 排序方向（``OrderValue``，Literal 已在入口约束 asc / desc）。
    :param allowed: 该端点允许的排序字段 → ORM Column 映射（防注入 allowlist）。
    :param default: ``order_by`` 为 None 时的默认排序列（含 tiebreaker，保 offset 分页稳定）。
    :param tie_break: 显式排序时追加的唯一 tie-breaker 列（各域 pk）；``None`` → 不追加（向后兼容）。
    :return: 经校验的 ORDER BY 列表（含方向），可直接 ``*`` 展开进 ``stmt.order_by``。
    :raises AppError: ``order_by`` 非空且不在 ``allowed`` 内 → 422 ``framework.SORT_FIELD_INVALID``。
    """
    if order_by is None:
        return list(default)
    column = allowed.get(order_by)
    if column is None:
        raise AppError(
            code=SORT_FIELD_INVALID_CODE,
            title="Invalid sort field",
            detail=f"order_by={order_by!r} 不在允许的排序字段内: {sorted(allowed)}",
            status_code=422,
        )
    primary = column.asc() if order == "asc" else column.desc()
    # 显式排序列已是 tie_break 本身（如 order_by=id）则无需再追加——它本就唯一，单列稳定。
    if tie_break is None or tie_break is column:
        return [primary]
    return [primary, tie_break.asc()]
