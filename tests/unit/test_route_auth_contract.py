"""路由鉴权契约（P1.5，Codex/Testing review）—— 所有非公开路由必须挂鉴权守卫。

``test_permission_registry`` 只证「已声明权限点 ↔ seed 一致」；本测试补另一面：**非公开路由
都有 ``require_current_user`` / ``require_permission`` 守卫**，防新增路由忘挂守卫静默裸奔
（require_permission 的内部依赖也依赖 require_current_user，故递归依赖树含它即视为已鉴权）。

DB-free：只检查 ``create_app().routes`` 的依赖树结构，不发请求。
"""

from __future__ import annotations

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from admin_platform.core.auth import require_current_user
from admin_platform.main import create_app

# 公开路由（无需鉴权，合理裸奔）：健康/就绪探针 + 认证端点本身（登录前无 token）。
# docs/openapi 是 Starlette Route（非 APIRoute），下方 isinstance 过滤天然排除，无需列。
_PUBLIC_PATHS = frozenset(
    {
        "/healthz",
        "/readyz",
        "/startupz",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
        "/api/v1/auth/captcha",
    }
)


def _collect_calls(dependant: Dependant) -> set[object]:
    """递归收集依赖树里所有依赖函数（require_permission 的 _dep → require_current_user）。"""
    calls: set[object] = set()
    for sub in dependant.dependencies:
        if sub.call is not None:
            calls.add(sub.call)
        calls |= _collect_calls(sub)
    return calls


def _route_has_auth(route: APIRoute) -> bool:
    return require_current_user in _collect_calls(route.dependant)


def test_all_non_public_routes_require_auth() -> None:
    app = create_app()
    unguarded = [
        f"{sorted(route.methods or [])} {route.path}"
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path not in _PUBLIC_PATHS
        and not _route_has_auth(route)
    ]
    assert not unguarded, (
        f"非公开路由缺鉴权守卫（应挂 require_permission/require_current_user）: {unguarded}"
    )


def test_probe_unguarded_route_is_detected() -> None:
    """违规探针（对称 test_openapi_contract 的 probe）：构造一条故意无守卫的 synthetic 路由，
    断言 _route_has_auth 判其为 unguarded —— 证明规则真会抓漏挂守卫的路由，而非恒返回 True
    的空绿（FastAPI 升级 / 重构令 _route_has_auth 失效时本探针会先红）。
    """

    async def _naked() -> dict[str, str]:
        return {}

    route = APIRoute("/__synthetic_naked", _naked, methods=["GET"])
    assert not _route_has_auth(route), "规则没抓到无守卫的 synthetic 路由 —— 契约测可能空绿"
