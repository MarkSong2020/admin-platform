"""assemble_menu_forest 菜单建树单测（纯函数，DB-free）。

覆盖：空集 / 扁平排序 / 嵌套 / 孤儿提升为根 / 同级 (sort_order,id) 排序。
"""

from __future__ import annotations

from dataclasses import dataclass

from admin_platform.domains.menu.provider import DbMenuProvider, assemble_menu_forest


@dataclass
class _FakeMenu:
    """假菜单行（只含 assemble_menu_forest 用到的字段，镜像 Menu ORM 子集）。"""

    id: int
    parent_id: int | None
    name: str
    sort_order: int = 0
    menu_type: str = "C"
    path: str = ""
    component: str | None = None
    perms: str | None = None
    icon: str = ""
    visible: bool = True


def _m(id_: int, parent_id: int | None, name: str, sort_order: int = 0) -> _FakeMenu:
    return _FakeMenu(id=id_, parent_id=parent_id, name=name, sort_order=sort_order)


def test_empty_returns_empty() -> None:
    assert assemble_menu_forest([]) == []  # type: ignore[arg-type]


def test_flat_roots_sorted_by_sort_order_then_id() -> None:
    menus = [_m(1, None, "B", 2), _m(2, None, "A", 1), _m(3, None, "C", 1)]
    forest = assemble_menu_forest(menus)  # type: ignore[arg-type]
    # sort_order 升序，相同 sort_order 按 id 升序 → A(2,so1), C(3,so1), B(1,so2)。
    assert [n.name for n in forest] == ["A", "C", "B"]
    assert all(n.children == () for n in forest)


def test_nested_tree() -> None:
    menus = [_m(1, None, "root"), _m(2, 1, "child"), _m(3, 2, "grandchild")]
    forest = assemble_menu_forest(menus)  # type: ignore[arg-type]
    assert len(forest) == 1
    assert forest[0].name == "root"
    assert forest[0].children[0].name == "child"
    assert forest[0].children[0].children[0].name == "grandchild"


def test_orphan_promoted_to_root() -> None:
    # 父 id=99 不在集合内（被可见性 / status 过滤掉）→ 子节点提升为根，不丢失。
    menus = [_m(1, None, "root"), _m(2, 99, "orphan")]
    forest = assemble_menu_forest(menus)  # type: ignore[arg-type]
    assert {n.name for n in forest} == {"root", "orphan"}


def test_invalidate_methods_are_noops() -> None:
    # P1 不缓存：invalidate_* 为 no-op，调用应无副作用、返回 None。
    provider = DbMenuProvider()
    assert provider.invalidate_user(1) is None
    assert provider.invalidate_role(1) is None
    assert provider.invalidate_all() is None


def test_node_metadata_carried() -> None:
    menu = _FakeMenu(
        id=1,
        parent_id=None,
        name="用户",
        sort_order=0,
        menu_type="C",
        path="user",
        component="views/User",
        perms="system:user:list",
        icon="user",
        visible=False,
    )
    node = assemble_menu_forest([menu])[0]  # type: ignore[arg-type]
    assert node.menu_type == "C"
    assert node.component == "views/User"
    assert node.perms == "system:user:list"
    assert node.icon == "user"
    assert node.visible is False
