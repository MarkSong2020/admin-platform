"""RBAC 前端契约冻结机检（spec §13.4 / Q17，DB-free）。

三者分工：OpenAPI schema（类型）+ 示例 JSON（若依 payload 语义）+ contract test（抓漂移）。
P1 不做 mock server。样本放 ``tests/contracts/``（测试可读优先），文档引用避免双份漂移。
机检：getInfo/getRouters response schema 必含 §6.1 冻结字段 + 示例能过 Pydantic 模型 +
破坏必冻字段触发探针失败。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from admin_platform.api.v1.rbac_schemas import UserInfoResponse
from admin_platform.domains.menu.routers import RouterVO
from admin_platform.main import create_app

_CONTRACTS = Path(__file__).parent.parent / "contracts"

# §6.1 必冻字段（改动即破前端契约，机检守门）。
_GETINFO_FIELDS = {"user", "roles", "permissions"}
_GETROUTERS_FIELDS = {"name", "path", "component", "redirect", "hidden", "alwaysShow", "meta"}
_META_FIELDS = {"title", "icon", "noCache", "link"}


def _schema() -> dict:
    return create_app().openapi()


def _load(name: str) -> object:
    return json.loads((_CONTRACTS / name).read_text(encoding="utf-8"))


# ---- OpenAPI schema 含必冻字段 -------------------------------------------


def test_getinfo_schema_has_frozen_fields() -> None:
    props = _schema()["components"]["schemas"]["UserInfoResponse"]["properties"]
    assert set(props.keys()) >= _GETINFO_FIELDS


def test_getrouters_schema_has_frozen_fields() -> None:
    schemas = _schema()["components"]["schemas"]
    props = schemas["RouterVO"]["properties"]
    assert set(props.keys()) >= _GETROUTERS_FIELDS
    meta_props = schemas["RouterMeta"]["properties"]
    assert set(meta_props.keys()) >= _META_FIELDS


def test_endpoints_published_in_openapi() -> None:
    paths = _schema()["paths"]
    assert "/api/v1/auth/user-info" in paths
    assert "/api/v1/menus/routers" in paths


# ---- 示例 JSON 能过 Pydantic 模型（若依 payload 语义冻结）------------------


def test_getinfo_example_validates() -> None:
    UserInfoResponse.model_validate(_load("getinfo_super_admin.json"))


def test_getrouters_example_validates() -> None:
    TypeAdapter(list[RouterVO]).validate_python(_load("getrouters_system.json"))


# ---- 破坏必冻字段触发探针失败（证明契约真在守门）--------------------------


def test_getinfo_missing_field_rejected() -> None:
    bad = _load("getinfo_super_admin.json")
    assert isinstance(bad, dict)
    del bad["permissions"]  # 删必冻字段
    with pytest.raises(ValidationError):
        UserInfoResponse.model_validate(bad)
