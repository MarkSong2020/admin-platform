"""权限点 registry —— 代码侧集中真相源（spec §13.2 / Q12）。

**默认 deny 的本质是端点声明保护**：``require_permission`` 引用本模块常量（禁裸字符串），
**不让 DB ``menus.perms`` 反推后端权限真相**（菜单漏挂 perms ≠ 后端失保护）。三组集合双向机检
保持一致：① 本 registry 声明的权限点（``ALL_PERMISSIONS``）；② 路由 ``@require_permission``
实际使用集（``core.permissions.USED_PERMISSIONS``）；③ seed 菜单 ``menus.perms``（§13.1）。

命名规范：``system:{resource}:{action}``。新增端点权限点必须先在此声明常量，否则
``require_permission`` 运行期 fail-fast（防悬空 / 拼错权限点）。纯前端按钮（有展示无后端端点）
列入 ``FRONTEND_ONLY`` 显式豁免「registry 必被某路由使用」的机检。
"""

from __future__ import annotations

from typing import Final


class Permissions:
    """全部后端权限点常量（``require_permission(Permissions.X)`` 引用，禁裸字符串）。"""

    # ---- system:user ----
    SYSTEM_USER_LIST: Final = "system:user:list"
    SYSTEM_USER_QUERY: Final = "system:user:query"
    SYSTEM_USER_ADD: Final = "system:user:add"
    SYSTEM_USER_EDIT: Final = "system:user:edit"
    SYSTEM_USER_REMOVE: Final = "system:user:remove"

    # ---- system:role ----
    SYSTEM_ROLE_LIST: Final = "system:role:list"
    SYSTEM_ROLE_QUERY: Final = "system:role:query"
    SYSTEM_ROLE_ADD: Final = "system:role:add"
    SYSTEM_ROLE_EDIT: Final = "system:role:edit"
    SYSTEM_ROLE_REMOVE: Final = "system:role:remove"

    # ---- system:menu ----
    SYSTEM_MENU_LIST: Final = "system:menu:list"
    SYSTEM_MENU_QUERY: Final = "system:menu:query"
    SYSTEM_MENU_ADD: Final = "system:menu:add"
    SYSTEM_MENU_EDIT: Final = "system:menu:edit"
    SYSTEM_MENU_REMOVE: Final = "system:menu:remove"

    # ---- system:dept ----
    SYSTEM_DEPT_LIST: Final = "system:dept:list"
    SYSTEM_DEPT_QUERY: Final = "system:dept:query"
    SYSTEM_DEPT_ADD: Final = "system:dept:add"
    SYSTEM_DEPT_EDIT: Final = "system:dept:edit"
    SYSTEM_DEPT_REMOVE: Final = "system:dept:remove"

    # ---- system:post ----
    SYSTEM_POST_LIST: Final = "system:post:list"
    SYSTEM_POST_QUERY: Final = "system:post:query"
    SYSTEM_POST_ADD: Final = "system:post:add"
    SYSTEM_POST_EDIT: Final = "system:post:edit"
    SYSTEM_POST_REMOVE: Final = "system:post:remove"

    # ---- system:operlog（操作/审计日志，对标 RuoYi sys_oper_log，只读）----
    SYSTEM_OPERLOG_LIST: Final = "system:operlog:list"
    SYSTEM_OPERLOG_QUERY: Final = "system:operlog:query"

    # ---- system:logininfor（登录日志，对标 RuoYi sys_logininfor，只读）----
    SYSTEM_LOGININFOR_LIST: Final = "system:logininfor:list"
    SYSTEM_LOGININFOR_QUERY: Final = "system:logininfor:query"


# registry 全集（自动从 Permissions 常量收集，frozenset 天然去重）。
ALL_PERMISSIONS: Final[frozenset[str]] = frozenset(
    value
    for key, value in vars(Permissions).items()
    if not key.startswith("_") and isinstance(value, str)
)

# 纯前端按钮权限点（有展示无后端端点）：豁免「registry 必被某路由使用」机检。P1 暂无。
FRONTEND_ONLY: Final[frozenset[str]] = frozenset()

# 超管展示用权限通配（getInfo 返回，§6.1；非安全判定——安全判定只认 is_super_admin 布尔）。
SUPER_ADMIN_WILDCARD: Final = "*:*:*"
