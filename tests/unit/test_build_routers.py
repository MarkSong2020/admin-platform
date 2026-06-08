"""build_routers getRouters payload 映射单测（spec §6.1 必冻字段，纯函数 DB-free）。

覆盖映射规则：按钮(F)不进树 / hidden=not visible / 目录 component(Layout|ParentView) /
菜单 component 回退 / redirect+alwaysShow 仅「有子目录」/ path 顶层补前导斜杠 / 外链 / meta 字段。
"""

from __future__ import annotations

from admin_platform.authz.providers import MenuNode
from admin_platform.domains.menu.routers import build_routers


def _menu(**kw: object) -> MenuNode:
    base: dict[str, object] = {"id": 1, "name": "X", "path": "x", "menu_type": "C"}
    base.update(kw)
    return MenuNode(**base)  # type: ignore[arg-type]


def test_button_type_excluded_from_tree() -> None:
    # 按钮(F)只承载 perms，不进路由树（顶层 + 嵌套都过滤）。
    tree = [
        _menu(
            id=1,
            name="系统",
            path="system",
            menu_type="M",
            children=(
                _menu(
                    id=2,
                    name="用户",
                    path="user",
                    menu_type="C",
                    children=(
                        _menu(id=3, name="新增", path="", menu_type="F", perms="system:user:add"),
                    ),
                ),
            ),
        ),
    ]
    routers = build_routers(tree)
    assert len(routers) == 1
    user = routers[0].get("children", [])[0]
    assert user["name"] == "User"
    assert "children" not in user  # 唯一子节点是按钮 → 被过滤，无 children 键


def test_hidden_is_negation_of_visible() -> None:
    routers = build_routers([_menu(id=1, name="隐藏页", path="hidden", visible=False)])
    assert routers[0]["hidden"] is True
    routers2 = build_routers([_menu(id=1, name="显示页", path="shown", visible=True)])
    assert routers2[0]["hidden"] is False


def test_directory_component_layout_vs_parentview() -> None:
    # 顶层目录 → Layout；嵌套目录 → ParentView。
    tree = [
        _menu(
            id=1,
            name="顶级目录",
            path="top",
            menu_type="M",
            children=(
                _menu(
                    id=2,
                    name="子目录",
                    path="sub",
                    menu_type="M",
                    children=(
                        _menu(
                            id=3, name="叶菜单", path="leaf", menu_type="C", component="views/Leaf"
                        ),
                    ),
                ),
            ),
        ),
    ]
    top = build_routers(tree)[0]
    assert top["component"] == "Layout"
    assert top["redirect"] == "noRedirect"
    assert top["alwaysShow"] is True
    sub = top.get("children", [])[0]
    assert sub["component"] == "ParentView"


def test_menu_component_used_with_layout_fallback() -> None:
    # 菜单(C) 用自身 component；缺省回退 Layout。
    with_comp = build_routers([_menu(id=1, name="有组件", path="a", component="views/A")])
    assert with_comp[0]["component"] == "views/A"
    no_comp = build_routers([_menu(id=1, name="无组件", path="b", component=None)])
    assert no_comp[0]["component"] == "Layout"


def test_leaf_directory_no_redirect_no_alwaysshow() -> None:
    # 无子节点的目录不置 redirect/alwaysShow（只有「有子目录」才置）。
    routers = build_routers([_menu(id=1, name="空目录", path="empty", menu_type="M")])
    assert routers[0]["redirect"] is None
    assert routers[0]["alwaysShow"] is False


def test_path_prefix_and_external_link() -> None:
    # 顶层补前导 /；外链原样 + meta.link。
    top = build_routers([_menu(id=1, name="页面", path="page")])[0]
    assert top["path"] == "/page"
    ext = build_routers([_menu(id=1, name="文档", path="https://example.com/doc")])[0]
    assert ext["path"] == "https://example.com/doc"
    assert ext["meta"]["link"] == "https://example.com/doc"


def test_meta_fields() -> None:
    node = _menu(id=1, name="标题", path="t", icon="star")
    meta = build_routers([node])[0]["meta"]
    assert meta["title"] == "标题"
    assert meta["icon"] == "star"
    assert meta["noCache"] is False
    assert meta["link"] is None
