"""FastAPI query-binding 框架行为 canary —— 锁住本仓「列表端点 422」bug 所依赖的框架语义。

本仓的列表端点把 ``page`` / ``size`` **折进 query-model**（``UserListQuery`` 等），而**不是**让
query-model 与标量 ``page`` / ``size`` Query 参数并存。这条选型的正确性取决于两条 FastAPI/Pydantic
框架契约（FastAPI 0.136 / Pydantic 2.13 实测）：

  ① query-model（``Annotated[Model, Query()]``）把 ``page`` / ``size`` 作为模型字段 → 请求带
     ``?page=1&size=10`` 命中字段，**200**；
  ② query-model 与独立标量 ``page`` Query 参数**并存** → **422**。真因是并存的标量参数令整个 model
     形参变得无法从 query 填充，报 ``loc=["query","<model 形参名>"] Field required``——**与 query-model
     的 ``extra`` 策略无关**（实测把 ``extra`` 切到 ignore 结果一字不差，连标量改名避开同名碰撞也照样 422）。

⚠️ **勿把 ② 误归因为「query-model 默认 extra='forbid' 把额外参数拒掉」**——本版本实测 query-model
**不** forbid 未知 url 参数（见 ``test_standalone_model_query_ignores_unknown_params``：``?bogus=x``
返回 200）。两条都**不是本仓代码**，是 FastAPI 行为。若将来升级改了这些语义（① 不再 200 / ② 不再
422 / 单 model-query 改成 forbid 额外参数），本 canary 第一个 FAIL，提醒重审折进策略与静态契约前提。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from pydantic import BaseModel


class _PageQuery(BaseModel):
    """合成 query-model：page / size 作为字段（镜像本仓 ``XxxListQuery`` 折进分页的写法）。"""

    page: int = 1
    size: int = 20


def _app_with_model_query() -> FastAPI:
    """① page/size 折进 query-model —— canonical 请求应 200。"""
    app = FastAPI()

    @app.get("/items")
    async def list_items(query: Annotated[_PageQuery, Query()]) -> dict[str, int]:
        return {"page": query.page, "size": query.size}

    return app


def _app_with_mixed_query() -> FastAPI:
    """② query-model 与独立标量 page Query 并存 —— 标量令 model 形参不可满足，应 422。"""
    app = FastAPI()

    @app.get("/items")
    async def list_items(
        query: Annotated[_PageQuery, Query()],
        page: Annotated[int, Query()] = 1,
    ) -> dict[str, int]:
        return {"page": page, "size": query.size}

    return app


def test_model_query_accepts_canonical_page_size() -> None:
    """① page/size 折进 query-model → ``?page=1&size=10`` 命中字段，返回 200 且回显正确。

    这是本仓所有「折进模型」列表端点依赖的 happy path 框架语义。
    """
    res = TestClient(_app_with_model_query()).get("/items?page=1&size=10")
    assert res.status_code == 200
    assert res.json() == {"page": 1, "size": 10}


def test_model_query_plus_scalar_query_is_422() -> None:
    """② query-model + 标量 page Query 并存 → 422（标量令 model 形参无法从 query 填充）。

    锁住正是这次 bug 的框架行为：混用必 422。下面断言 422 的真因是 **model 形参 missing**（``loc``
    指向那个 model 形参 ``query``、``type=missing``），而**非** extra='forbid' 拒额外参数——证明机制，
    防有人据错误归因误改静态契约。若升级后此处不再 422，本仓「折进模型」策略前提变了，需重审。
    """
    res = TestClient(_app_with_mixed_query()).get("/items?page=1&size=10")
    assert res.status_code == 422
    detail = res.json().get("detail", [])
    assert any(err.get("type") == "missing" and "query" in err.get("loc", []) for err in detail), (
        f"422 应为 model 形参 query missing（非 extra 拒额外参数），实际 detail={detail}"
    )


def test_standalone_model_query_ignores_unknown_params() -> None:
    """单独 query-model 对未知 url 参数返回 200（**不** forbid）——锁住「query-model 不 extra-forbid」语义。

    这是 ② 不该被误归因为 extra='forbid' 的直接证据，也是真正的 extra-策略 canary：若将来 FastAPI /
    Pydantic 把 query-model 默认改成 forbid 额外参数，``?bogus_unknown=zzz`` 将变 422，本断言第一个 FAIL。
    """
    res = TestClient(_app_with_model_query()).get("/items?page=1&size=10&bogus_unknown=zzz")
    assert res.status_code == 200, (
        f"query-model 不应 forbid 未知 url 参数（实测语义），实际 {res.status_code}: {res.text}"
    )
    assert res.json() == {"page": 1, "size": 10}
