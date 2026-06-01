"""OpenAPI spec contract — ADR 0001 §1 §8 enforced at schema gen time."""

from fastapi import FastAPI
from pydantic import BaseModel

from admin_platform.main import create_app


def _spec() -> dict:
    app: FastAPI = create_app()
    return app.openapi()


class _Payload(BaseModel):
    """Minimal Pydantic body so FastAPI auto-generates a 422 response."""

    name: str


def _spec_with_body_route() -> dict:
    """Build an app with a POST route taking a Pydantic body — forces 422."""
    app: FastAPI = create_app()

    @app.post("/__contract_probe")
    def _probe(payload: _Payload) -> dict[str, str]:
        return {"name": payload.name}

    # Bust the cached schema so the new route is included.
    app.openapi_schema = None
    return app.openapi()


def test_problem_detail_schema_is_published() -> None:
    """ADR §1: ProblemDetail must land in components.schemas for SDK generators."""
    schema = _spec()
    components = schema["components"]["schemas"]
    assert "ProblemDetail" in components
    properties = components["ProblemDetail"]["properties"]
    # All 8 ADR §1 fields must be on the wire.
    for field in (
        "type",
        "title",
        "status",
        "detail",
        "instance",
        "request_id",
        "trace_id",
        "errors",
    ):
        assert field in properties, f"ProblemDetail missing {field}"


def test_route_with_pydantic_body_advertises_problem_detail_on_422() -> None:
    """ADR §1: a route with a Pydantic body must show 422 → ProblemDetail (not the FastAPI default HTTPValidationError)."""
    schema = _spec_with_body_route()
    problem_ref = "#/components/schemas/ProblemDetail"
    op = schema["paths"]["/__contract_probe"]["post"]
    resp_422 = op["responses"]["422"]
    ref = resp_422["content"]["application/json"]["schema"].get("$ref")
    assert ref == problem_ref, f"422 schema is {ref}, expected {problem_ref}"


def test_bearer_jwt_security_scheme_is_declared() -> None:
    """v0.4.14: securitySchemes.bearerAuth is a stable placeholder so SDK
    auto-generators emit a typed ``Authorization: Bearer ...`` slot from
    day one. v0.5.3: auth middleware 已落地（core/auth.py）。
    Business modules 在 operation 上加 ``security: [{bearerAuth: []}]`` 标记。"""
    schema = _spec()
    schemes = schema["components"].get("securitySchemes", {})
    assert "bearerAuth" in schemes, "JWT Bearer security scheme placeholder missing"
    bearer = schemes["bearerAuth"]
    assert bearer["type"] == "http"
    assert bearer["scheme"] == "bearer"
    assert bearer["bearerFormat"] == "JWT"


def test_readyz_advertises_503_problem_detail_in_openapi() -> None:
    """v0.4.21: /readyz can fail-close 503 with ProblemDetail when DB or
    Redis ping fails (see ``api/v1/health.py`` and ``test_health.py``).
    Without ``responses=`` on the route, FastAPI only puts 200 in OpenAPI
    → SDK generators assume "always 200" and break on 503. Declaring the
    503 lets ``_custom_openapi`` rewrite the schema ref to ProblemDetail.

    Guards against future removal of the ``responses=`` kwarg on readyz."""
    schema = _spec()
    readyz = schema["paths"]["/readyz"]["get"]["responses"]
    assert "503" in readyz, (
        "/readyz must declare its 503 failure path — without it SDKs can't "
        "see the typed not-ready response. Re-add `responses=_NOT_READY_RESPONSE` "
        "on the route decorator in api/v1/health.py."
    )
    ref = readyz["503"]["content"]["application/json"]["schema"].get("$ref")
    assert ref == "#/components/schemas/ProblemDetail", (
        f"/readyz 503 schema is {ref}, expected ProblemDetail $ref"
    )


def test_no_route_in_full_spec_leaks_fastapi_default_validation_error() -> None:
    """ADR §1: belt-and-suspenders — scan every 422 in the live spec."""
    schema = _spec_with_body_route()
    problem_ref = "#/components/schemas/ProblemDetail"
    for path, path_item in schema.get("paths", {}).items():
        for method, op in path_item.items():
            if not isinstance(op, dict):
                continue
            resp_422 = op.get("responses", {}).get("422")
            if resp_422 is None:
                continue
            ref = (
                resp_422.get("content", {})
                .get("application/json", {})
                .get("schema", {})
                .get("$ref")
            )
            assert ref == problem_ref, (
                f"{method.upper()} {path}: 422 schema is {ref}, expected {problem_ref}"
            )
