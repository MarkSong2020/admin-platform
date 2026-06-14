"""列表端点 canonical smoke 覆盖契约 —— 结构性强制每个业务 list 端点都被 canonical 请求覆盖。

**背景（P0 回归）**：列表端点把 query-model 与独立标量 ``page``/``size`` Query 混进同一签名时，
标量令整个 model 形参无法从 query 填充，任何带 ``?page=&size=`` 的真实请求报 422「该模型参数
missing」（与 query-model 的 ``extra`` 策略无关，实测并不 forbid 额外参数）。该 bug 绕过了
``make check``——既有 api 测试裸调端点不带 query，没有人真的发一个 canonical 分页请求。
``test_route_query_binding_contract`` 在**签名层**静态堵这一种反模式；本契约在**运行时**补刀：对每个
list 端点真发 ``GET ?page=1&size=10`` 经 TestClient，断言 ≠ 422——抓的是「任何让 canonical 请求
挂掉」的绑定问题（不限这一种成因）。

**结构性强制（核心价值）+ 零登记（auto-smoke）**：list 端点经生产 ``create_app()`` 路由表**自动
发现**——判据**命名无关**：GET + ``response_model`` 是 ``*Page`` 子类即纳入（不依赖 operation_id
命名后缀）。凡返回 ``*Page`` 的分页端点（含 ``scheduled_task_logs`` 这类子资源 logs，及未来
``*_search`` / ``*_history`` 等任意命名的分页端点）皆自动纳入——因为「带 ``page``/``size`` 的分页请求踩
model+scalar 混用 422」与命名无关，靠后缀排除等于给非 ``_list`` 命名的分页端点开假绿后门。service 依赖
也**自动从路由 dependant 解析**（约定 service 依赖参数名为 ``svc``）——无需手工维护登记表。**新增
（含 ``make new-module`` 生成）第 N 个分页端点零改动自动纳入覆盖**；若新端点不符约定（无 ``svc``
依赖 / response_model 非 ``*Page``），结构性自检直接 FAIL 报出，逼其对齐或显式处理。若确有 ``*Page``
端点需排除，走 ``_DISCOVERY_ALLOWLIST`` 显式登记（operation_id → 原因），**不**靠命名隐式跳过。

不连 DB / 不用 Mock：service 经 ``dependency_overrides`` 注入手写的「返回空 Page」哑 service，
``require_current_user`` / ``get_permission_provider`` 注入超管 stub 越过权限守卫，``get_session``
注入不连库占位。
"""

from __future__ import annotations

from typing import Any, get_type_hints

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel

from admin_platform.authz.providers import PermissionProvider
from admin_platform.authz.scope import DataScope, ScopeType
from admin_platform.core.auth import CurrentUser, require_current_user
from admin_platform.core.errors import register_exception_handlers
from admin_platform.core.middleware import RequestIDMiddleware
from admin_platform.core.permissions import get_permission_provider
from admin_platform.main import create_app
from tests.api._support import override_get_session

# 约定：各域 list 端点的 service 依赖参数名统一为 ``svc``（``ServiceDep = Annotated[XxxService,
# Depends(get_xxx_service)]``）。本契约据此从路由 dependant 自动解析 service 依赖的 ``Depends``
# 目标，免去手工登记表（也免去与 make new-module 生成模块的登记冲突）。
_SERVICE_DEP_PARAM = "svc"

# 显式排除清单（operation_id → 原因）。发现判据命名无关、纳入所有 ``*Page`` 分页端点；若确有某
# ``*Page`` 端点不能进 canonical smoke（极少见），在此登记并注明原因——**不靠命名后缀隐式跳过**。
# 当前为空：所有 ``*Page`` 端点都应能正确响应 canonical ``?page=1&size=10`` 请求。
_DISCOVERY_ALLOWLIST: dict[str, str] = {}


class _SuperAdminProvider(PermissionProvider):
    """超管 stub：让 ``require_permission`` 守卫短路放行（不连 DB / 不用 Mock）。"""

    def get_is_super_admin(self, user_id: int) -> bool:
        return True

    def get_user_permissions(self, user_id: int) -> frozenset[str]:
        return frozenset()

    def get_effective_data_scope(self, user_id: int) -> DataScope:
        return DataScope(ScopeType.ALL, user_id=user_id)

    def invalidate_user(self, user_id: int) -> None: ...
    def invalidate_role(self, role_id: int) -> None: ...
    def invalidate_all(self) -> None: ...


def _superadmin_user() -> CurrentUser:
    """``require_current_user`` 替身：固定返回 user_id=1（权限由 ``_superadmin_provider`` 决定）。"""
    return CurrentUser(user_id="1", sub="1")


def _superadmin_provider() -> PermissionProvider:
    """``get_permission_provider`` 替身：超管 stub，让权限守卫短路放行。"""
    return _SuperAdminProvider()


def _resolve_service_class(service_dep: Any) -> type | None:
    """从 service 依赖（``get_xxx_service`` 工厂）解析出它返回的 service 类。

    取 ``get_type_hints(...)["return"]``（解开 ``from __future__ import annotations`` 的字符串化注解）。
    解析失败 / 无返回注解 → 返回 ``None``，由哑 service 回退到「放行任意方法名」的宽松模式（不 FAIL，
    但 ``test_every_list_endpoint_service_class_resolves`` 会盯住所有端点都能解析，杜绝静默回退）。
    """
    try:
        return get_type_hints(service_dep).get("return")
    except Exception:
        return None


def _empty_page_service(page_model: type[BaseModel], service_class: type | None) -> Any:
    """构造一个「调真实存在的 ``list*`` 方法 → 返回空 ``page_model``」的哑 service 类。

    所有 ``*Page`` envelope 同形（items/page/size/total/total_pages），故同一构造适配全部域。
    用 ``__getattr__`` 兜住各域不同的 list 方法名（``list_`` / ``list_types`` / ``list_audit_events``
    …），把回显的 page/size 透传进空 Page —— 既不连 DB，又验证 canonical 请求真的解析到了处理函数。

    **收紧（2026-06-14，Codex high 双源印证）**：``__getattr__`` 不再对任意方法名都返回桩——只放行
    **真实存在于 ``service_class`` 上的方法**；handler 若调了不存在的方法名（typo / 签名漂移，如
    ``svc.list_taks()``）则抛 ``AttributeError`` → 请求 500 → 本 smoke 抓住（旧实现宽 ``__getattr__``
    会让 typo 仍返 200 假绿）。``service_class is None``（依赖无法解析返回类型）时回退宽松模式。

    **仍存的诚实边界**：本 smoke 只验证「请求绑定（canonical ``?page=1&size=10`` ≠ 422）」+「handler
    调的 list 方法名真实存在」；**不**验证参数签名 / 返回 schema 是否真匹配（那是各域单测 / 集成职责）。
    本 smoke 绿 ≠「端点完全 OK」。
    """

    class _StubService:
        def __getattr__(self, name: str) -> Any:
            if service_class is not None and not hasattr(service_class, name):
                raise AttributeError(
                    f"{service_class.__name__} 无方法 {name!r}——handler 调了不存在的 service 方法"
                    f"（typo / 签名漂移）；smoke 哑 service 仅放行真实存在的方法"
                )

            async def _call(
                *_args: Any, page: int = 1, size: int = 10, **_kwargs: Any
            ) -> BaseModel:
                return page_model(items=[], page=page, size=size, total=0, total_pages=0)

            return _call

    return _StubService


def _list_routes(app: FastAPI) -> list[tuple[str, APIRoute]]:
    """发现业务 GET 分页端点，返回 ``(operation_id, route)`` 对（operation_id 已收窄为非空 ``str``）。

    判据**命名无关**：GET + response_model 是 ``*Page`` 子类即纳入。**不**要求 operation_id 以
    ``_list`` 结尾——任何带 ``page``/``size`` 的分页端点都可能踩 model+scalar 混用 422，靠命名后缀
    排除等于给非 ``_list`` 命名的分页端点（如 ``scheduled_task_logs`` / 未来 ``*_search`` /
    ``*_history``）开假绿后门。若确需排除某 ``*Page`` 端点，走 ``_DISCOVERY_ALLOWLIST`` 显式登记。
    """
    routes: list[tuple[str, APIRoute]] = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        operation_id = route.operation_id or ""
        if operation_id in _DISCOVERY_ALLOWLIST:
            continue
        response_model = route.response_model
        is_page = (
            isinstance(response_model, type)
            and issubclass(response_model, BaseModel)
            and response_model.__name__.endswith("Page")
        )
        if "GET" in (route.methods or set()) and is_page:
            routes.append((operation_id, route))
    return routes


def _service_dependency(route: APIRoute) -> Any:
    """从路由 dependant 解析出 service 依赖的 ``Depends`` 目标（``dependency_overrides`` 的 key）。

    约定 service 依赖参数名为 ``svc``（见 ``_SERVICE_DEP_PARAM``）。找不到 → 返回 ``None``，由
    调用方报结构性失败（端点未按约定声明 service 依赖，覆盖无从注入）。
    """
    for dependency in route.dependant.dependencies:
        if dependency.name == _SERVICE_DEP_PARAM:
            return dependency.call
    return None


def test_list_endpoint_discovery_is_nonempty() -> None:
    """自检：发现逻辑确实抓到了分页端点（防判据失效 → 下面两个契约空转恒过）。"""
    assert _list_routes(create_app()), "未发现任何业务 GET 分页端点——发现判据可能失效"


def test_discovery_includes_non_list_suffixed_page_endpoint() -> None:
    """负向探针：返回 ``*Page`` 但 operation_id 不以 ``_list`` 结尾的端点也必须被发现。

    ``scheduled_task_logs``（``GET /logs`` → ``ScheduledTaskLogPage``）是真实的「非 ``_list`` 命名的
    分页端点」——旧判据靠 ``_list`` 后缀把它排除在 canonical smoke 外（假绿后门）。本探针锚定它必在
    发现集里；若有人退回「后缀过滤」判据，这里立刻 FAIL。再补一个 synthetic 路由（operation_id 完全
    不含 ``list``、response_model 是 ``*Page``）双重证明判据确实命名无关。
    """
    discovered = {operation_id for operation_id, _ in _list_routes(create_app())}
    assert "scheduled_task_logs" in discovered, (
        "scheduled_task_logs（GET /logs → ScheduledTaskLogPage）未被发现——"
        "判据可能退回了 `_list` 后缀过滤（假绿后门）"
    )

    class _WidgetPage(BaseModel):
        items: list[Any] = []
        page: int = 1
        size: int = 10
        total: int = 0
        total_pages: int = 0

    synthetic = APIRouter()

    @synthetic.get("/widgets", operation_id="widgets_overview", response_model=_WidgetPage)
    async def _widgets() -> _WidgetPage:  # pragma: no cover - 仅供 AST/路由发现，不实际调用
        return _WidgetPage()

    probe_app = FastAPI()
    probe_app.include_router(synthetic)
    probe_discovered = {operation_id for operation_id, _ in _list_routes(probe_app)}
    assert "widgets_overview" in probe_discovered, (
        "operation_id 不含 `list` 的 *Page 端点未被发现——发现判据不应依赖命名后缀"
    )


def test_every_list_endpoint_exposes_a_service_dependency() -> None:
    """结构性强制：每个发现到的 list 端点都必须暴露可解析的 ``svc`` service 依赖。

    auto-smoke 靠把该依赖 override 成空 Page service 才能 DB-free 跑 canonical 请求。新增 list 端点
    若不按约定声明 ``svc`` 依赖 → 这里 FAIL 报出，逼其对齐（或显式扩展本契约）。这条让覆盖**零遗漏**
    且**零登记**——新端点（含 make new-module 生成）自动纳入。
    """
    unresolved: list[str] = []
    for operation_id, route in _list_routes(create_app()):
        if _service_dependency(route) is None:
            unresolved.append(f"{operation_id} ({route.path})")
    assert not unresolved, (
        f"下列 list 端点未暴露可解析的 {_SERVICE_DEP_PARAM!r} service 依赖（auto-smoke 无从注入覆盖）:\n"
        + "\n".join(unresolved)
    )


def test_every_list_endpoint_service_class_resolves() -> None:
    """结构性强制：每个 list 端点的 ``svc`` 依赖都能解析出 service 类（保证 ``__getattr__`` 收紧生效）。

    收紧后的哑 service 靠 ``service_class`` 判定「handler 调的方法是否真实存在」；若某 ``get_xxx_service``
    工厂掉了返回注解 → ``service_class`` 解析为 ``None`` → 该端点静默回退宽松模式（typo 又能假绿）。
    本测试盯住所有端点都能解析返回类型，杜绝静默回退。新端点工厂若无返回注解，这里 FAIL 报出。
    """
    unresolved: list[str] = []
    for operation_id, route in _list_routes(create_app()):
        service_dep = _service_dependency(route)
        if service_dep is None or _resolve_service_class(service_dep) is None:
            unresolved.append(f"{operation_id} ({route.path})")
    assert not unresolved, (
        "下列 list 端点的 service 依赖无法解析出 service 类（哑 service 收紧会静默回退宽松模式）:\n"
        + "\n".join(unresolved)
    )


def test_stub_service_rejects_unknown_method() -> None:
    """负向探针：收紧后的哑 service 对「service 类上不存在的方法名」必须抛 ``AttributeError``。

    旧宽 ``__getattr__`` 对任意名字都返回桩，handler 调错方法名（typo）仍 200 假绿；本探针证明已收紧。
    """

    class _Page(BaseModel):
        items: list[Any] = []
        page: int = 1
        size: int = 10
        total: int = 0
        total_pages: int = 0

    class _RealService:
        async def list_(self) -> Any: ...  # 真实存在的方法

    stub = _empty_page_service(_Page, _RealService)()
    # 真实方法名放行（返回可调用桩）。
    assert callable(stub.list_)
    # 不存在的方法名（typo）必须抛 AttributeError。
    try:
        stub.list_taks  # noqa: B018 - 故意触发 __getattr__
    except AttributeError:
        pass
    else:
        raise AssertionError(
            "收紧后的哑 service 对不存在的方法名未抛 AttributeError（typo 仍假绿）"
        )
    # service_class is None 时回退宽松（任意名放行），防解析失败误伤。
    loose = _empty_page_service(_Page, None)()
    assert callable(loose.any_name_whatsoever)


def test_every_list_endpoint_canonical_request_not_422() -> None:
    """对每个 list 端点真发 ``GET <path>?page=1&size=10``，断言 200（绝不 422）。

    把该域 service（从 dependant 自动解析）override 成「返回空 Page」哑 service、用超管 stub 越过权限
    守卫，经 TestClient 实发 canonical 分页请求。任一端点返回 422 → 它的请求绑定坏了（model-Query
    与标量混用等），本契约报出 method+path+status+body 定位。现有 + 未来端点零登记自动覆盖。
    """
    app = create_app()
    failures: list[str] = []
    for operation_id, route in _list_routes(app):
        service_dep = _service_dependency(route)
        assert service_dep is not None, (
            f"{operation_id} 无 {_SERVICE_DEP_PARAM!r} 依赖"  # 由上一个契约兜底，这里防御
        )
        response_model = route.response_model
        assert isinstance(response_model, type) and issubclass(response_model, BaseModel)

        # 每个端点用独立 app（隔离 override），镜像生产 middleware/异常处理拓扑。
        local_app = FastAPI()
        local_app.add_middleware(RequestIDMiddleware)
        register_exception_handlers(local_app)
        local_app.include_router(_wrap_route(route))
        override_get_session(local_app.dependency_overrides)
        local_app.dependency_overrides[require_current_user] = _superadmin_user
        local_app.dependency_overrides[get_permission_provider] = _superadmin_provider
        local_app.dependency_overrides[service_dep] = _empty_page_service(
            response_model, _resolve_service_class(service_dep)
        )

        res = TestClient(local_app).get(f"{route.path}?page=1&size=10")
        if res.status_code != 200:
            failures.append(
                f"GET {route.path} ({operation_id}) → {res.status_code} (期望 200): {res.text[:200]}"
            )
    assert not failures, (
        "下列 list 端点的 canonical ?page=1&size=10 请求未返回 200（请求绑定反模式）:\n"
        + "\n".join(failures)
    )


def _wrap_route(route: APIRoute) -> APIRouter:
    """把单条生产 ``route`` 包进一个临时 router（保留其完整路径 + 依赖图）。

    各域 ``api.py`` 的端点已带最终路径（route.path 是含 prefix 的绝对路径），直接塞进空 router
    再 ``include_router``（不加二次 prefix），确保本地 app 路径与生产逐字一致——避免在测试里重复
    硬编码每个域的 router import / prefix。
    """
    wrapper = APIRouter()
    wrapper.routes.append(route)
    return wrapper
