"""core.pagination 单测 —— compute_total_pages 边界 + resolve_sort 防注入 allowlist。"""

from typing import cast

import pytest
from sqlalchemy import Column, Integer, String

from admin_platform.core.errors import AppError
from admin_platform.core.pagination import (
    SORT_FIELD_INVALID_CODE,
    SortColumn,
    compute_total_pages,
    ilike_contains,
    like_contains,
    resolve_sort,
)

# 测试用裸 Column（不挂表，仅验 resolve_sort 的 allowlist 查表 + 方向逻辑）。生产传 ORM
# ``InstrumentedAttribute``；裸 ``Column`` 在 Mapping/Sequence（协变）参数里结构兼容，但作为
# 单值 ``tie_break``（``SortColumn``=``InstrumentedAttribute``）需 cast 才过 pyright——运行期
# 二者都有 ``.asc()`` / ``.desc()``，行为一致。
_ID = Column("id", Integer)
_NAME = Column("name", String)
_ALLOWED = {"id": _ID, "name": _NAME}
_DEFAULT = [_ID]
_ID_TIE_BREAK = cast(SortColumn, _ID)


@pytest.mark.parametrize(
    ("total", "size", "expected"),
    [
        (0, 20, 0),  # 无记录
        (1, 20, 1),  # 不足一页向上取整为 1
        (20, 20, 1),  # 整除
        (21, 20, 2),  # 非整除向上取整
        (100, 10, 10),  # 整除
        (101, 10, 11),  # 非整除
        (5, 0, 0),  # 防御除零（正常路径 SizeQ ge=1 不会传 0）
    ],
)
def test_compute_total_pages(total: int, size: int, expected: int) -> None:
    assert compute_total_pages(total, size) == expected


# ---- resolve_sort 防注入 allowlist（安全回归守门）----------------------------


def test_resolve_sort_none_returns_default() -> None:
    # order_by=None → 用默认序（不查 allowlist）。
    assert resolve_sort(None, "desc", allowed=_ALLOWED, default=_DEFAULT) == _DEFAULT


def test_resolve_sort_allowed_field_asc() -> None:
    out = resolve_sort("name", "asc", allowed=_ALLOWED, default=_DEFAULT)
    # 命中 allowlist → 返回该列 .asc()（渲染出的 SQL 含列名 + ASC，且不含注入串）。
    sql = str(out[0])
    assert "name" in sql and "ASC" in sql.upper()


def test_resolve_sort_allowed_field_desc() -> None:
    out = resolve_sort("id", "desc", allowed=_ALLOWED, default=_DEFAULT)
    sql = str(out[0])
    assert "DESC" in sql.upper()


@pytest.mark.parametrize(
    "injection",
    [
        "id; DROP TABLE users",  # 经典 SQL 注入串
        "password_hash",  # 未授权列（不在 allowlist）
        "name); DELETE FROM posts;--",  # 闭合括号注入
        "",  # 空串（max_length 允许但不在 allowlist）
        "ID",  # 大小写不匹配（allowlist 区分大小写）
    ],
)
def test_resolve_sort_non_allowlist_field_raises_422(injection: str) -> None:
    """红线：order_by 非 allowlist 字段（含注入串 / 未授权列）→ 422，绝不进 SQL。"""
    with pytest.raises(AppError) as exc:
        resolve_sort(injection, "asc", allowed=_ALLOWED, default=_DEFAULT)
    assert exc.value.status_code == 422
    assert exc.value.code == SORT_FIELD_INVALID_CODE


# ---- 稳定排序 tie-break（OFFSET 深分页跨页不跳行）---------------------------


def test_resolve_sort_appends_tie_break_on_non_unique_column() -> None:
    # 显式按非唯一列（name）排序 → 追加唯一 tie-breaker（id）作第二排序键，保 offset 分页稳定。
    out = resolve_sort("name", "asc", allowed=_ALLOWED, default=_DEFAULT, tie_break=_ID_TIE_BREAK)
    assert len(out) == 2
    assert "name" in str(out[0])
    # tie-breaker 恒升序追加（方向不影响唯一性，只需稳定）。
    assert "id" in str(out[1]) and "ASC" in str(out[1]).upper()


def test_resolve_sort_no_duplicate_when_sort_column_is_tie_break() -> None:
    # 显式排序列本身就是 tie_break（id）→ 它已唯一，不重复追加（仍是单列）。
    out = resolve_sort("id", "desc", allowed=_ALLOWED, default=_DEFAULT, tie_break=_ID_TIE_BREAK)
    assert len(out) == 1
    assert "DESC" in str(out[0]).upper()


def test_resolve_sort_tie_break_not_applied_to_default() -> None:
    # order_by=None → 用 default（自带 tiebreaker），不叠加 tie_break。
    out = resolve_sort(None, "desc", allowed=_ALLOWED, default=_DEFAULT, tie_break=_ID_TIE_BREAK)
    assert out == _DEFAULT


@pytest.mark.parametrize(
    ("keyword", "expected"),
    [
        ("plain", "%plain%"),  # 无元字符：原样包 %...%
        ("a_b", "%a\\_b%"),  # _ 通配符 → 转义为字面下划线
        ("50%", "%50\\%%"),  # % 通配符 → 转义为字面百分号
        ("a\\b", "%a\\\\b%"),  # 反斜杠 → 转义（且先于 % / _ 处理，不二次转义）
        ("%_\\", "%\\%\\_\\\\%"),  # 三种元字符混合
    ],
)
def test_like_contains_escapes_wildcards(keyword: str, expected: str) -> None:
    """``like_contains`` 必须转义 LIKE 元字符 ``\\`` / ``%`` / ``_``（防搜字面元字符时通配符语义污染）。"""
    assert like_contains(keyword) == expected


def test_ilike_contains_emits_escape_clause() -> None:
    """``ilike_contains`` 落地到 SQL 必须带 ``ESCAPE`` 子句（否则转义反斜杠本身被当字面匹配）。"""
    expr = ilike_contains(cast(SortColumn, _NAME), "a_b")
    compiled = str(expr.compile(compile_kwargs={"literal_binds": True}))
    assert "ESCAPE" in compiled.upper(), f"ilike 落地缺 ESCAPE 子句: {compiled}"
