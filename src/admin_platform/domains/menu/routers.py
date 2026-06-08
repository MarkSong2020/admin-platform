"""``getRouters`` 动态路由 payload 纯函数（spec §6.1 前端契约必冻字段）。

把 ``authz.providers.MenuNode`` 菜单树转成前端动态路由树 payload，字段名按若依 ``RouterVO``
冻结（前端选 RuoYi-Vue3 零适配 / vben 薄适配，spec §6.4）。**必冻字段**（§6.1）：
``name / path / component / redirect / hidden / alwaysShow / meta``，``meta`` 含
``title / icon / noCache / link``。

映射规则（参考若依 ``MenuServiceImpl.buildMenus``，P1 简化）：
  * **按钮类（menu_type=F）不进路由树** —— 只承载 ``perms``，由 getInfo permissions 下发。
  * ``hidden = not visible`` —— 不可见菜单仍注册路由但侧边栏隐藏。
  * ``component`` —— 目录（M）顶层 → ``Layout``、嵌套 → ``ParentView``；菜单（C）→ 自身
    ``component``（缺省回退 ``Layout``）。
  * ``redirect`` / ``alwaysShow`` —— 仅「有子节点的目录」置 ``noRedirect`` / ``True``，其余
    ``None`` / ``False``。
  * ``path`` —— 顶层补前导 ``/``；嵌套保持相对；外链（http/https）原样。
  * ``meta.title`` = 菜单 ``name``；``meta.icon`` = ``icon``；``meta.link`` = 外链 path（否则 None）；
    ``meta.noCache`` 固定 False（P1 menus 表无 is_cache 字段，字段先固化、值取默认）。

纯函数 + 无 IO + 无副作用 —— 可在单测里直接断言（``tests/unit/test_build_routers.py``）。
"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from admin_platform.authz.providers import MenuNode

_EXTERNAL_PREFIXES = ("http://", "https://")


class RouterMeta(TypedDict):
    """路由 meta（若依 ``MetaVo`` 子集，spec §6.1 冻结）。"""

    title: str
    icon: str
    noCache: bool
    link: str | None


class RouterVO(TypedDict):
    """动态路由节点（若依 ``RouterVo`` 子集，spec §6.1 冻结）。``children`` 仅有子节点时出现。"""

    name: str
    path: str
    hidden: bool
    component: str
    redirect: str | None
    alwaysShow: bool
    meta: RouterMeta
    children: NotRequired[list[RouterVO]]


def build_routers(tree: list[MenuNode]) -> list[RouterVO]:
    """把菜单树（含目录/菜单/按钮）转成前端动态路由 payload，过滤按钮类。"""
    return [_to_router(node, top_level=True) for node in tree if node.menu_type != "F"]


def _to_router(node: MenuNode, *, top_level: bool) -> RouterVO:
    child_routers = [
        _to_router(child, top_level=False) for child in node.children if child.menu_type != "F"
    ]
    is_dir = node.menu_type == "M"
    dir_with_children = is_dir and bool(child_routers)
    router: RouterVO = {
        "name": _route_name(node.path),
        "path": _route_path(node.path, top_level=top_level),
        "hidden": not node.visible,
        "component": _component(node, top_level=top_level, is_dir=is_dir),
        "redirect": "noRedirect" if dir_with_children else None,
        "alwaysShow": dir_with_children,
        "meta": _meta(node),
    }
    if child_routers:
        router["children"] = child_routers
    return router


def _route_name(path: str) -> str:
    """路由 name = 去前导 ``/`` 后首字母大写（若依 ``getRouteName``，供 keep-alive 缓存）。"""
    segment = path.lstrip("/")
    return segment[:1].upper() + segment[1:] if segment else ""


def _route_path(path: str, *, top_level: bool) -> str:
    """顶层补前导 ``/``；嵌套保持相对；外链原样。"""
    if path.startswith(_EXTERNAL_PREFIXES):
        return path
    if top_level:
        return path if path.startswith("/") else "/" + path
    return path


def _component(node: MenuNode, *, top_level: bool, is_dir: bool) -> str:
    """目录无 component → ``Layout``（顶层）/ ``ParentView``（嵌套）；菜单用自身 component。"""
    if is_dir:
        return "Layout" if top_level else "ParentView"
    return node.component or "Layout"


def _meta(node: MenuNode) -> RouterMeta:
    link = node.path if node.path.startswith(_EXTERNAL_PREFIXES) else None
    return {"title": node.name, "icon": node.icon, "noCache": False, "link": link}
