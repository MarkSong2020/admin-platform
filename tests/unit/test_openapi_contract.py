"""OpenAPI spec 契约 —— 数据驱动规则表 + 违规探针（阶段 1 / D1·D2）。

规则用稳定 ID（``api.*``）表达，作用于 ``create_app().openapi()`` 的 runtime
spec。引擎纯 pytest（Python-native，不引入 Spectral/node）。违规探针证明
"非空绿"——规则真会拦，而不是恰好没触发。
"""

from __future__ import annotations

import re

import pytest

from admin_platform.main import create_app

OPERATION_ID_RE = re.compile(
    r"^[a-z][a-z0-9_]*$"
)  # 允许单 token（healthz）；业务 {plural}_{action}
PROBLEM_REF = "#/components/schemas/ProblemDetail"
_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "trace"}


def _spec() -> dict:
    return create_app().openapi()


def _iter_operations(spec: dict):
    for path, item in spec.get("paths", {}).items():
        for method, op in item.items():
            if method in _HTTP_METHODS and isinstance(op, dict):
                yield method, path, op


# ---- operation-scope 规则：check(method, path, op) -> list[str] -------------


def _rule_operation_id_snake_case(method: str, path: str, op: dict) -> list[str]:
    opid = op.get("operationId")
    if opid and not OPERATION_ID_RE.fullmatch(opid):
        return [f"{method.upper()} {path}: operationId {opid!r} 不符 ^[a-z][a-z0-9_]*$"]
    return []


def _rule_tags_required(method: str, path: str, op: dict) -> list[str]:
    if not op.get("tags"):
        return [f"{method.upper()} {path}: 缺 tags"]
    return []


def _rule_error_problem_detail_ref(method: str, path: str, op: dict) -> list[str]:
    out: list[str] = []
    for code, resp in op.get("responses", {}).items():
        if str(code)[:1] not in {"4", "5"}:
            continue
        ref = resp.get("content", {}).get("application/json", {}).get("schema", {}).get("$ref")
        if ref != PROBLEM_REF:  # 含 ref=None（4xx/5xx 缺 ProblemDetail schema 也算违规）
            out.append(f"{method.upper()} {path}: {code} schema {ref} != ProblemDetail")
    return out


# ---- spec-scope 规则：check(spec) -> list[str] -----------------------------


def _rule_operation_id_unique(spec: dict) -> list[str]:
    seen: dict[str, str] = {}
    dups: list[str] = []
    for method, path, op in _iter_operations(spec):
        opid = op.get("operationId")
        if not opid:
            continue
        loc = f"{method.upper()} {path}"
        if opid in seen:
            dups.append(f"operationId {opid!r} 重复: {seen[opid]} & {loc}")
        seen[opid] = loc
    return dups


def _rule_problem_detail_published(spec: dict) -> list[str]:
    schemas = spec.get("components", {}).get("schemas", {})
    if "ProblemDetail" not in schemas:
        return ["components.schemas 缺 ProblemDetail"]
    props = schemas["ProblemDetail"].get("properties", {})
    required = ("type", "title", "status", "detail", "instance", "request_id", "trace_id", "errors")
    return [f"ProblemDetail 缺字段 {f}" for f in required if f not in props]


def _rule_bearer_scheme_declared(spec: dict) -> list[str]:
    bearer = spec.get("components", {}).get("securitySchemes", {}).get("bearerAuth")
    if not bearer:
        return ["securitySchemes 缺 bearerAuth"]
    bad = []
    if bearer.get("type") != "http":
        bad.append("bearerAuth.type != http")
    if bearer.get("scheme") != "bearer":
        bad.append("bearerAuth.scheme != bearer")
    if bearer.get("bearerFormat") != "JWT":
        bad.append("bearerAuth.bearerFormat != JWT")
    return bad


OPERATION_RULES = {
    "api.operation_id.snake_case": _rule_operation_id_snake_case,
    "api.operation.tags.required": _rule_tags_required,
    "api.error.problem_detail_ref": _rule_error_problem_detail_ref,
}
SPEC_RULES = {
    "api.operation_id.unique": _rule_operation_id_unique,
    "api.schema.problem_detail_published": _rule_problem_detail_published,
    "api.security.bearer_scheme_declared": _rule_bearer_scheme_declared,
}


# ---- 主断言：现有 spec 必须全绿 --------------------------------------------


@pytest.mark.parametrize("rule_id", list(OPERATION_RULES))
def test_operation_rule_holds_on_live_spec(rule_id: str) -> None:
    spec = _spec()
    check = OPERATION_RULES[rule_id]
    violations = [v for m, p, op in _iter_operations(spec) for v in check(m, p, op)]
    assert not violations, f"[{rule_id}] " + "; ".join(violations)


@pytest.mark.parametrize("rule_id", list(SPEC_RULES))
def test_spec_rule_holds_on_live_spec(rule_id: str) -> None:
    violations = SPEC_RULES[rule_id](_spec())
    assert not violations, f"[{rule_id}] " + "; ".join(violations)


# ---- 违规探针：证明规则真会拦（非空绿） ------------------------------------
#
# 探针**直接喂 synthetic op dict 给规则函数**，不走 create_app().openapi()。
# 原因：main.py 的 _custom_openapi 会把所有已声明 4xx/5xx schema 重写成
# ProblemDetail（见 main.py:116），错误类探针经它一洗就变绿、证明不了规则有效
# （实测验证）。规则在真实 spec 上的触达由上面 test_*_holds_on_live_spec 覆盖；
# 这里只证规则逻辑确实会拦坏输入。


def test_probe_camel_case_operation_id_is_caught() -> None:
    op = {"operationId": "badOpId", "tags": ["x"]}
    assert _rule_operation_id_snake_case("get", "/__synthetic", op), (
        "snake_case 规则没抓到 camelCase operationId —— 规则失效（空绿）"
    )


def test_probe_missing_tags_is_caught() -> None:
    op = {"operationId": "synthetic_get", "responses": {}}
    assert _rule_tags_required("get", "/__synthetic", op), (
        "tags.required 规则没抓到无 tags 的路由 —— 规则失效（空绿）"
    )


def test_probe_non_problem_detail_error_ref_is_caught() -> None:
    op = {
        "responses": {
            "400": {
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Other"}}}
            }
        }
    }
    assert _rule_error_problem_detail_ref("post", "/__synthetic", op), (
        "problem_detail_ref 规则没抓到非 ProblemDetail 的 4xx schema —— 规则失效"
    )


def test_probe_missing_error_schema_is_caught() -> None:
    # stricter：4xx/5xx 缺 ProblemDetail schema（ref=None）也算违规
    op = {"responses": {"500": {"description": "boom"}}}
    assert _rule_error_problem_detail_ref("get", "/__synthetic", op), (
        "problem_detail_ref 规则没抓到缺 schema 的 5xx —— 规则失效"
    )
