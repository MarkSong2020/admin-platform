"""请求绑定结构契约 —— 结构性防止「列表端点 422」反模式复发（DB-free，make check 跑）。

**背景（P0 回归）**：列表端点若把 Pydantic query-model（``Annotated[XxxListQuery, Query()]``）与
标量 Query 参数（``page: PageQ``、``size: SizeQ`` 等）混进同一端点签名，则任何带 ``?page=&size=``
的真实请求都会 422。**422 的真因**（Codex high + harness 门 meta agent 双源实测确认，FastAPI
0.136 / Pydantic 2.13）：并存的标量参数令整个 model 形参变得**无法从 query 填充**，报
``loc=["query","<model 形参名>"] Field required``——**与 query-model 的 ``extra`` 策略无关**
（canary 实测：``extra`` 切到 ignore 结果一字不差）。该 bug 曾绕过 ``make check``（新过滤测试是
integration 级被 deselect；既有 api 测试裸调端点不带 query）。

本契约遍历生产 ``create_app()`` 的所有路由，对每个端点函数做签名级静态检查：**断言没有任何端点存在
会让 canonical 请求 422 的 query-model 组合**——(a) model-as-Query 与标量 Query 混用，或 (b) 两个
及以上 model-as-Query 并存（同样互相令对方形参不可满足 422）。违规会在失败信息里列出端点 + 参数名。

**已知边界**：本契约只看端点函数**自身签名**，不递归 ``Depends`` 依赖树。把 query-model 藏进
``Depends()`` 是另一种形态——但 ``Depends()`` 会把模型字段拆成独立标量（实测不 422，非反模式），
故无需静态拦；真正的运行时兜底是 ``test_list_endpoint_smoke_contract`` 对每个 ``*Page`` 端点发
canonical 请求断言 ≠ 422。

不连 DB / 不用 Mock：纯 ``inspect`` + ``typing.get_type_hints`` 静态内省路由表。
"""

from __future__ import annotations

import inspect
from typing import Annotated, Any, get_args, get_origin, get_type_hints

import fastapi.params
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

from admin_platform.main import create_app


def _query_markers(metadata: tuple[Any, ...]) -> bool:
    """``Annotated`` 元数据里是否含 ``fastapi.params.Query`` marker。

    ``Query`` 与 ``Depends`` / ``Path`` / ``Body`` 是同级但互不为子类的不同类，``isinstance``
    精确区分——``svc``（Depends）/ 路径参数（Path）不会被误判为 Query。
    """
    return any(isinstance(meta, fastapi.params.Query) for meta in metadata)


def _is_model_query(annotation: Any, default: Any) -> bool:
    """参数是否为 **model-as-Query**：``Annotated[X, Query(...)]`` 且 X 是 ``BaseModel`` 子类。

    这是模型整体接管 query string 的写法（``XxxListQuery`` 把 page/size 等折进字段即此形态）。
    """
    if get_origin(annotation) is not Annotated:
        return False
    base, *metadata = get_args(annotation)
    if not _query_markers(tuple(metadata)):
        return False
    return isinstance(base, type) and issubclass(base, BaseModel)


def _is_scalar_query(annotation: Any, default: Any) -> bool:
    """参数是否为 **标量 Query**：带 Query marker 但底层类型不是 ``BaseModel``。

    覆盖两种 FastAPI 写法：
      * ``Annotated[T, Query(...)]``（如 ``PageQ = Annotated[int, Query(...)]``）；
      * ``param: T = Query(...)``（Query 实例作默认值，无 ``Annotated``）。
    """
    # 写法二：默认值即 Query 实例。
    if isinstance(default, fastapi.params.Query):
        return True
    # 写法一：Annotated 元数据含 Query marker，且底层不是 BaseModel（那是 model-as-Query）。
    if get_origin(annotation) is not Annotated:
        return False
    base, *metadata = get_args(annotation)
    if not _query_markers(tuple(metadata)):
        return False
    return not (isinstance(base, type) and issubclass(base, BaseModel))


# 注解解析失败可豁免的路由 allowlist（fail-closed 的唯一例外）。
# 键 = 端点函数 ``__qualname__``；值 = 豁免原因（必须是框架内建/非业务路由）。
# 业务路由若解析失败必须 FAIL，**不得**塞进这里绕过——加条目前先确认是 FastAPI
# 内建（如 /docs /openapi.json /redoc 的 swagger handler），且写清原因。
# 当前全部业务路由都能静态解析（见 test_no_route_fails_type_hint_resolution），故为空。
_HINT_RESOLUTION_ALLOWLIST: dict[str, str] = {}


class _UnresolvableEndpoint(Exception):
    """端点注解无法静态解析且不在 allowlist——fail-closed 信号（由契约捕获并 FAIL）。"""


def _classify_endpoint(func: Any) -> tuple[list[str], list[str]]:
    """对端点函数的每个参数分类，返回 (model_query 参数名列表, scalar_query 参数名列表)。

    用 ``get_type_hints(include_extras=True)`` 解析注解（保留 ``Annotated`` 元数据，并解开
    ``from __future__ import annotations`` 带来的字符串化注解）。

    **fail-closed**（2026-06-14 硬化）：解析失败时**不再静默跳过**（旧行为会让某生产路由
    的注解解析异常被悄悄吞掉，反模式可绕过契约）。除非该端点在 ``_HINT_RESOLUTION_ALLOWLIST``
    （框架内建非业务路由），否则抛 ``_UnresolvableEndpoint`` 让契约 FAIL 并报出该路由。
    """
    signature = inspect.signature(func)
    try:
        hints = get_type_hints(func, include_extras=True)
    except Exception as exc:
        if func.__qualname__ in _HINT_RESOLUTION_ALLOWLIST:
            # 框架内建路由豁免：注解无法解析也不阻断（fallback 到原始 annotation）。
            hints = {}
        else:
            raise _UnresolvableEndpoint(
                f"{func.__qualname__}: 注解无法静态解析（{type(exc).__name__}: {exc}）——"
                f"业务路由必须可解析；确属框架内建请加进 _HINT_RESOLUTION_ALLOWLIST 并注明原因"
            ) from exc
    model_query: list[str] = []
    scalar_query: list[str] = []
    for name, param in signature.parameters.items():
        annotation = hints.get(name, param.annotation)
        if _is_model_query(annotation, param.default):
            model_query.append(name)
        elif _is_scalar_query(annotation, param.default):
            scalar_query.append(name)
    return model_query, scalar_query


def _iter_api_routes(app: FastAPI) -> list[APIRoute]:
    return [route for route in app.routes if isinstance(route, APIRoute)]


def _unbindable_reason(model_query: list[str], scalar_query: list[str]) -> str | None:
    """返回该端点 query 参数组合「会让 canonical 请求 422」的原因，无则 ``None``。

    两类 FastAPI 实测会 422 的形态（Codex high + harness 门 meta agent 双源实测确认）：
      * **model-Query 与标量 Query 混用**：标量参数令 model 形参本身无法从 query 填充 → 422；
      * **两个及以上 model-Query 并存**：多个模型同时接管 query string，互相令对方形参不可满足 → 422
        （单 model-Query 旧实现漏判此形态：``scalar_query`` 为空 → ``model and scalar`` 为假 → 假绿）。
    422 真因是「model 形参 missing」，与 query-model 的 ``extra`` 策略无关（见 canary 实测）。
    """
    if model_query and scalar_query:
        return (
            f"model-Query={model_query} 与 标量-Query={scalar_query} 混用 "
            f"→ 标量参数令 model 形参无法从 query 填充 422"
        )
    if len(model_query) >= 2:
        return f"多个 model-Query 并存={model_query} → 互相令对方形参无法满足 422"
    return None


def test_no_endpoint_mixes_model_query_and_scalar_query() -> None:
    """没有任何端点存在会让 canonical 请求 422 的 query-model 组合（绑定反模式）。

    覆盖两类 422 形态（见 ``_unbindable_reason``）：model-Query+标量混用、多 model-Query 并存。
    遍历生产 ``create_app()`` 全部 APIRoute，违规端点会被收集进 ``violations`` 并在断言失败信息里
    逐条列出（路径 / 方法 / 函数名 / 参数名），便于精确定位。
    """
    app = create_app()
    violations: list[str] = []
    for route in _iter_api_routes(app):
        model_query, scalar_query = _classify_endpoint(route.endpoint)
        reason = _unbindable_reason(model_query, scalar_query)
        if reason is not None:
            methods = ",".join(sorted(route.methods or set()))
            violations.append(f"{methods} {route.path} ({route.endpoint.__name__}): {reason}")
    assert not violations, (
        "检测到 query-model 绑定反模式端点（canonical 分页请求会 422，应把标量参数折进单一 query 模型）:\n"
        + "\n".join(violations)
    )


def test_unbindable_reason_flags_multiple_model_queries() -> None:
    """负向探针：两个 model-Query 并存（标量为空）必须被判为违规。

    Codex high + harness 门 meta agent 双源实测：``ep(p: Annotated[A,Query()], f: Annotated[B,Query()])``
    的 canonical 请求真 422，但旧判据 ``model_query and scalar_query``（scalar 为空）会放过它（假绿）。
    """
    assert _unbindable_reason(["p", "f"], []) is not None, "多 model-Query 并存未被判违规（假绿）"
    # 防误报：单 model-Query（无标量）是正常的「折进模型」写法，不应判违规。
    assert _unbindable_reason(["q"], []) is None, "单 model-Query 被误判违规"
    # 混用仍判违规。
    assert _unbindable_reason(["q"], ["page"]) is not None


def test_contract_detects_at_least_one_query_param_per_kind() -> None:
    """自检：契约确实「看见」了两类参数（防分类器恒返回空 → 上面的断言变恒真）。

    生产 app 里既有 model-as-Query 端点（如 users/roles/posts 列表），也有标量 Query 端点
    （如 depts/menus 列表的 page/size）。若任一类在全量路由中颗粒无收，说明内省逻辑失效，
    主断言会退化成「空 ∩ 空」恒过——此自检兜底。
    """
    app = create_app()
    saw_model_query = False
    saw_scalar_query = False
    for route in _iter_api_routes(app):
        model_query, scalar_query = _classify_endpoint(route.endpoint)
        saw_model_query = saw_model_query or bool(model_query)
        saw_scalar_query = saw_scalar_query or bool(scalar_query)
    assert saw_model_query, "内省未识别出任何 model-as-Query 参数——分类器可能失效"
    assert saw_scalar_query, "内省未识别出任何标量 Query 参数——分类器可能失效"


def test_no_route_fails_type_hint_resolution() -> None:
    """fail-closed 守门：所有业务路由注解都必须能静态解析（不在 allowlist 里被静默跳过）。

    旧实现 ``try: get_type_hints(...) except Exception: hints = {}`` 会把某生产路由解析失败
    悄悄吞掉——该路由的参数全部「看不见」，混用反模式就能绕过主契约。本测试逐路由调用
    ``_classify_endpoint``，任一非 allowlist 路由解析失败即 ``_UnresolvableEndpoint`` 冒泡 FAIL，
    并报出该路由的 method+path+func，逼业务路由要么可解析要么显式登记原因。
    """
    app = create_app()
    unresolved: list[str] = []
    for route in _iter_api_routes(app):
        try:
            _classify_endpoint(route.endpoint)
        except _UnresolvableEndpoint as exc:
            methods = ",".join(sorted(route.methods or set()))
            unresolved.append(f"{methods} {route.path}: {exc}")
    assert not unresolved, (
        "存在注解无法静态解析的业务路由（fail-closed——不允许静默跳过）:\n" + "\n".join(unresolved)
    )
