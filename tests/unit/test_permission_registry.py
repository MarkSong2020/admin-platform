"""权限点 registry 契约机检（spec §13.2 / §9 DoD 补）。

三组集合之 ①registry ②路由实际用集 的双向一致（③seed 菜单 perms 一致在
``test_permission_menu_contract`` 覆盖）：
  * 命名规范 ``system:{resource}:{action}`` + 无重复。
  * 路由只用已注册权限点（``require_permission`` 运行期已 fail-fast，此处再断言）。
  * registry 无悬空权限点（每个都被某路由使用，或显式 ``FRONTEND_ONLY`` 豁免）。
"""

from __future__ import annotations

import importlib
import pkgutil
import re

import admin_platform.domains as _domains_pkg
from admin_platform.authz.permissions import ALL_PERMISSIONS, FRONTEND_ONLY, Permissions
from admin_platform.core.permissions import USED_PERMISSIONS

_PERM_RE = re.compile(r"^system:[a-z]+:[a-z]+$")


def _import_all_domain_apis() -> None:
    """import 每个 ``domains/<domain>/api.py``，触发 require_permission 登记 USED_PERMISSIONS。

    自动发现：新增域无需改本测试即被契约覆盖（与 test_column_comments 同款）。
    """
    for mod in pkgutil.iter_modules(_domains_pkg.__path__):
        if not mod.ispkg:
            continue
        try:
            importlib.import_module(f"admin_platform.domains.{mod.name}.api")
        except ModuleNotFoundError:
            continue  # 该域还没长出 api.py


def test_registry_naming_and_no_duplicates() -> None:
    raw = [
        value
        for key, value in vars(Permissions).items()
        if not key.startswith("_") and isinstance(value, str)
    ]
    assert len(raw) == len(set(raw)), "registry 存在重复权限点常量"
    bad = [p for p in ALL_PERMISSIONS if not _PERM_RE.match(p)]
    assert not bad, f"权限点命名不符 system:{{resource}}:{{action}}：{bad}"


def test_routes_use_only_registered_perms() -> None:
    _import_all_domain_apis()
    unregistered = USED_PERMISSIONS - ALL_PERMISSIONS
    assert not unregistered, (
        f"路由使用了未注册的权限点（require_permission 应已 fail-fast）：{unregistered}"
    )


def test_registry_has_no_dangling_perm() -> None:
    _import_all_domain_apis()
    dangling = ALL_PERMISSIONS - USED_PERMISSIONS - FRONTEND_ONLY
    assert not dangling, (
        f"registry 有悬空权限点（无任何路由使用且未列入 FRONTEND_ONLY）：{dangling}"
    )
