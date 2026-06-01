"""Unit tests for ``scripts/new_module.py`` — the domain generator.

Strategy: import the script as a module, redirect ``REPO_ROOT`` to ``tmp_path``
so writes never touch the real repository. Cover happy paths, validation
failures, conflict detection, and the OSError rollback branch.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "new_module.py"


@pytest.fixture(scope="module")
def new_module():
    """Load scripts/new_module.py as an importable module."""
    spec = importlib.util.spec_from_file_location("new_module_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["new_module_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_module):
    """Point REPO_ROOT at tmp_path with a minimal pyproject.toml."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "service-name"\n\n[tool.hatch.build]\npackages = ["src/admin_platform"]\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "admin_platform").mkdir(parents=True)
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    (tmp_path / "tests" / "api").mkdir(parents=True)
    monkeypatch.setattr(new_module, "REPO_ROOT", tmp_path)
    return tmp_path


# --------------------------------------------------------------------------- #
# Pure helpers                                                                #
# --------------------------------------------------------------------------- #


def test_pascal_case_handles_snake_and_singletons(new_module) -> None:
    assert new_module._pascal_case("order") == "Order"
    assert new_module._pascal_case("user_profile") == "UserProfile"
    assert new_module._pascal_case("a") == "A"


@pytest.mark.parametrize(
    "value",
    ["Order", "1order", "order-item", "", "_order", "order.item", "order item"],
)
def test_validate_name_rejects_bad_input(value: str, new_module) -> None:
    with pytest.raises(SystemExit) as exc:
        new_module._validate_name(value, flag="--name")
    assert exc.value.code == 2


@pytest.mark.parametrize(
    "value", ["models", "schemas", "api", "service", "repository", "db", "core"]
)
def test_validate_name_rejects_reserved_package_names(value: str, new_module) -> None:
    with pytest.raises(SystemExit) as exc:
        new_module._validate_name(value, flag="--name")
    assert exc.value.code == 2


def test_validate_name_camelcase_error_suggests_snake_case(
    new_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """v0.4.20: 第八轮 review 发现 generator 报错"must match regex"对新人
    不友好（尤其 Java 背景），应当直接给出 snake_case 建议。"""
    with pytest.raises(SystemExit):
        new_module._validate_name("OrderItem", flag="--name")
    err = capsys.readouterr().err
    assert "order_item" in err, (
        "error message should suggest the snake_case form for CamelCase input"
    )
    assert "lowercase snake_case" in err


def test_validate_name_reserved_error_lists_options(
    new_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reserved-name 报错也应列出所有保留名，省去新人去翻 NAME_REGEX 常量。"""
    with pytest.raises(SystemExit):
        new_module._validate_name("models", flag="--name")
    err = capsys.readouterr().err
    assert "reserved package" in err
    # 至少应该看到几个具体保留名
    assert "models" in err and "schemas" in err


def test_validate_name_rejects_python_keyword(new_module) -> None:
    with pytest.raises(SystemExit):
        new_module._validate_name("class", flag="--name")


# --------------------------------------------------------------------------- #
# Service package resolution                                                  #
# --------------------------------------------------------------------------- #


def test_resolve_service_package_from_hatch_packages(fake_repo: Path, new_module) -> None:
    assert new_module._resolve_service_package(None) == "admin_platform"


def test_resolve_service_package_falls_back_to_project_name(fake_repo: Path, new_module) -> None:
    (fake_repo / "pyproject.toml").write_text('[project]\nname = "my-svc"\n', encoding="utf-8")
    assert new_module._resolve_service_package(None) == "my_svc"


def test_resolve_service_package_fails_without_pyproject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, new_module
) -> None:
    monkeypatch.setattr(new_module, "REPO_ROOT", tmp_path)
    with pytest.raises(SystemExit) as exc:
        new_module._resolve_service_package(None)
    assert exc.value.code == 1


def test_resolve_service_package_explicit_wins(fake_repo: Path, new_module) -> None:
    assert new_module._resolve_service_package("custom_svc") == "custom_svc"


# --------------------------------------------------------------------------- #
# main() — dry run                                                            #
# --------------------------------------------------------------------------- #


def test_dry_run_lists_seven_files_without_model(
    fake_repo: Path, new_module, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = new_module.main(["--name", "order", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Would generate" in out
    # 4 domain files + tests (service + api) + domains/__init__.py = 7
    assert "src/admin_platform/domains/order/schemas.py" in out
    assert "src/admin_platform/domains/order/service.py" in out
    assert "src/admin_platform/domains/order/repository.py" in out
    assert "src/admin_platform/domains/order/api.py" in out
    assert "tests/unit/test_order_service.py" in out
    assert "tests/api/test_order_api.py" in out
    assert "models.py" not in out
    # No files actually written
    assert not (fake_repo / "src" / "admin_platform" / "domains").exists()


def test_dry_run_with_model_adds_models_file(
    fake_repo: Path, new_module, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = new_module.main(["--name", "order", "--with-model", "--dry-run"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "src/admin_platform/domains/order/models.py" in out


# --------------------------------------------------------------------------- #
# main() — real writes                                                        #
# --------------------------------------------------------------------------- #


def test_generate_minimal_module_writes_expected_files(fake_repo: Path, new_module) -> None:
    rc = new_module.main(["--name", "order"])
    assert rc == 0
    domain = fake_repo / "src" / "admin_platform" / "domains" / "order"
    assert (domain / "__init__.py").exists()
    assert (domain / "schemas.py").exists()
    assert (domain / "service.py").exists()
    assert (domain / "repository.py").exists()
    assert (domain / "api.py").exists()
    assert not (domain / "models.py").exists()
    assert (fake_repo / "tests" / "unit" / "test_order_service.py").exists()
    assert (fake_repo / "tests" / "api" / "test_order_api.py").exists()


def test_generated_code_substitutes_placeholders(fake_repo: Path, new_module) -> None:
    new_module.main(["--name", "order"])
    schemas = (
        fake_repo / "src" / "admin_platform" / "domains" / "order" / "schemas.py"
    ).read_text()
    api = (fake_repo / "src" / "admin_platform" / "domains" / "order" / "api.py").read_text()
    assert "class OrderCreate" in schemas
    assert "class OrderRead" in schemas
    assert "{Name}" not in schemas  # no unfilled placeholders
    assert "/api/v1/orders" in api
    assert "ORDER_NOT_FOUND" not in api  # NOT_FOUND lives in service.py
    service = (
        fake_repo / "src" / "admin_platform" / "domains" / "order" / "service.py"
    ).read_text()
    assert "ORDER_NOT_FOUND" in service


_ENV_PY_FIXTURE = """\
\"\"\"alembic env fixture for tests.\"\"\"

# --- Register models here for autogenerate ----------------------------------
# Example:
#     from admin_platform.domains.user.models import User
# ----------------------------------------------------------------------------

# rest of env.py omitted for tests
"""


@pytest.fixture
def fake_repo_with_alembic(fake_repo: Path) -> Path:
    """Augment fake_repo with a stub migrations/env.py whose register block
    matches the layout the generator's patch routine expects."""
    (fake_repo / "migrations").mkdir(parents=True, exist_ok=True)
    (fake_repo / "migrations" / "env.py").write_text(_ENV_PY_FIXTURE, encoding="utf-8")
    return fake_repo


def test_with_model_patches_alembic_env_register_block(
    fake_repo_with_alembic: Path, new_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """v0.4.13: --with-model auto-patches migrations/env.py so callers can't
    forget the import and end up with empty autogenerated migrations."""
    new_module.main(["--name", "order", "--with-model"])
    env_text = (fake_repo_with_alembic / "migrations" / "env.py").read_text()
    assert "from admin_platform.domains.order.models import Order  # noqa: F401" in env_text
    # v0.4.15 regression guard: the inserted import MUST be followed by a
    # blank line so ruff's isort rule (I001) treats it as the end of the
    # import group. Without this, ``make check`` fails immediately after a
    # fresh ``make new-module ... with-model=1`` — surprising new users.
    assert "from admin_platform.domains.order.models import Order  # noqa: F401\n\n" in env_text, (
        "patched import must be followed by a blank line (ruff I001)"
    )
    # Next-steps message must confirm the auto-patch (so caller knows to diff).
    out = capsys.readouterr().out
    assert "Patched migrations/env.py" in out


def test_with_model_patch_is_idempotent(fake_repo_with_alembic: Path, new_module) -> None:
    """Running the generator twice with --force must not duplicate the
    import line (idempotent contract)."""
    new_module.main(["--name", "order", "--with-model"])
    new_module.main(["--name", "order", "--with-model", "--force"])
    env_text = (fake_repo_with_alembic / "migrations" / "env.py").read_text()
    assert (
        env_text.count("from admin_platform.domains.order.models import Order  # noqa: F401") == 1
    )


def test_with_model_appends_subsequent_patches_without_blank_line(
    fake_repo_with_alembic: Path, new_module
) -> None:
    """v0.5.0 regression guard: smoke-generator caught that patching env.py
    twice (different domains) left a blank line between the two patched
    ``from ... import ...`` lines, which breaks ruff isort I001 — the
    import block is no longer contiguous. Fix: subsequent patches append
    directly after the prior patched import; only the LAST patch keeps a
    trailing blank line."""
    new_module.main(["--name", "order", "--with-model"])
    new_module.main(["--name", "ledger", "--with-model"])
    env_text = (fake_repo_with_alembic / "migrations" / "env.py").read_text()

    assert "from admin_platform.domains.order.models import Order  # noqa: F401" in env_text
    assert "from admin_platform.domains.ledger.models import Ledger  # noqa: F401" in env_text

    # CRITICAL: no blank line between the two patched imports — they must
    # form a single contiguous import block (otherwise ruff I001 fires).
    lines = env_text.splitlines()
    order_idx = next(i for i, line in enumerate(lines) if "order.models import Order" in line)
    ledger_idx = next(i for i, line in enumerate(lines) if "ledger.models import Ledger" in line)
    between = lines[min(order_idx, ledger_idx) + 1 : max(order_idx, ledger_idx)]
    assert all(line.strip() != "" for line in between), (
        f"no blank line allowed between consecutive patched imports "
        f"(ruff I001 regression — smoke-generator guard). got: {between!r}"
    )


def test_without_model_does_not_patch_env(fake_repo_with_alembic: Path, new_module) -> None:
    """In-memory generation (no ORM) must leave migrations/env.py untouched."""
    original = (fake_repo_with_alembic / "migrations" / "env.py").read_text()
    new_module.main(["--name", "order"])
    assert (fake_repo_with_alembic / "migrations" / "env.py").read_text() == original


def test_with_model_handles_missing_env_py_gracefully(
    fake_repo: Path, new_module, capsys: pytest.CaptureFixture[str]
) -> None:
    """Forks may have removed Alembic entirely. Missing env.py is a soft
    skip with a clear instruction in next-steps, not a crash."""
    rc = new_module.main(["--name", "order", "--with-model"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Could not auto-patch" in out
    assert "Add manually:" in out


def test_with_model_generates_orm_class_and_db_repository(fake_repo: Path, new_module) -> None:
    new_module.main(["--name", "order", "--with-model"])
    models = (fake_repo / "src" / "admin_platform" / "domains" / "order" / "models.py").read_text()
    repo = (
        fake_repo / "src" / "admin_platform" / "domains" / "order" / "repository.py"
    ).read_text()
    assert "class Order" in models
    assert "AsyncSession" in repo
    assert "select(Order)" in repo
    # v0.4.12: __table_args__ placeholder must exist with usage hint —
    # adding composite indexes after the fact is expensive on hot tables.
    assert "__table_args__" in models
    assert "Index(" in models  # hint comment must remain


def test_custom_plural_overrides_default(fake_repo: Path, new_module) -> None:
    rc = new_module.main(["--name", "category", "--plural", "categories"])
    assert rc == 0
    api = (fake_repo / "src" / "admin_platform" / "domains" / "category" / "api.py").read_text()
    assert "/api/v1/categories" in api
    assert "/api/v1/categorys" not in api


# --------------------------------------------------------------------------- #
# Validation & error paths                                                    #
# --------------------------------------------------------------------------- #


def test_plural_equal_to_name_is_rejected(fake_repo: Path, new_module) -> None:
    with pytest.raises(SystemExit) as exc:
        new_module.main(["--name", "order", "--plural", "order"])
    assert exc.value.code == 2


def test_existing_files_without_force_fail(
    fake_repo: Path, new_module, capsys: pytest.CaptureFixture[str]
) -> None:
    new_module.main(["--name", "order"])
    with pytest.raises(SystemExit) as exc:
        new_module.main(["--name", "order"])
    assert exc.value.code == 1
    assert "conflict" in capsys.readouterr().err


def test_force_flag_overwrites(fake_repo: Path, new_module) -> None:
    new_module.main(["--name", "order"])
    schemas = fake_repo / "src" / "admin_platform" / "domains" / "order" / "schemas.py"
    schemas.write_text("# tampered\n", encoding="utf-8")
    rc = new_module.main(["--name", "order", "--force"])
    assert rc == 0
    assert "tampered" not in schemas.read_text()


def test_generated_api_tests_mount_request_id_middleware(fake_repo: Path, new_module) -> None:
    """v0.4.12: generated API test app MUST mirror production middleware
    topology so error responses' request_id field matches what the live
    service emits. Without RequestIDMiddleware request_id is None — a
    silent contract drift that propagates to every generated service."""
    new_module.main(["--name", "order"])
    inmem = (fake_repo / "tests" / "api" / "test_order_api.py").read_text()
    assert "from admin_platform.core.middleware import RequestIDMiddleware" in inmem
    assert "app.add_middleware(RequestIDMiddleware)" in inmem


def test_generated_api_tests_mount_request_id_middleware_db_template(
    fake_repo: Path, new_module
) -> None:
    """Same guarantee for --with-model template."""
    new_module.main(["--name", "order", "--with-model"])
    db = (fake_repo / "tests" / "api" / "test_order_api.py").read_text()
    assert "from admin_platform.core.middleware import RequestIDMiddleware" in db
    assert "app.add_middleware(RequestIDMiddleware)" in db


def test_post_endpoints_advertise_idempotency_errors_in_openapi(
    fake_repo: Path, new_module
) -> None:
    """v0.4.16: @idempotent POST middleware 可能返回:
    - 400 framework.IDEMPOTENCY_KEY_INVALID (key 超 255 字符)
    - 409 framework.IDEMPOTENT_RETRY_IN_FLIGHT (同 key 同 body 仍在执行)
    - 422 framework.IDEMPOTENCY_KEY_REUSED (同 key 异 body)

    三条都在 middleware 层 reject, FastAPI 不知道——必须 generator 显式声明
    responses, 否则 SDK 生成器看不到这些错误路径, 业务侧只能 catch 通用 Error.
    """
    new_module.main(["--name", "order"])
    api_inmem = (fake_repo / "src" / "admin_platform" / "domains" / "order" / "api.py").read_text()
    assert "IDEMPOTENT_POST_ERROR_RESPONSES" in api_inmem
    assert "400" in api_inmem
    assert "409" in api_inmem
    assert "422" in api_inmem
    assert "responses=IDEMPOTENT_POST_ERROR_RESPONSES" in api_inmem


def test_post_endpoints_advertise_idempotency_errors_in_db_template(
    fake_repo: Path, new_module
) -> None:
    """Same guarantee for --with-model DB template."""
    new_module.main(["--name", "order", "--with-model"])
    api_db = (fake_repo / "src" / "admin_platform" / "domains" / "order" / "api.py").read_text()
    assert "IDEMPOTENT_POST_ERROR_RESPONSES" in api_db
    assert "responses=IDEMPOTENT_POST_ERROR_RESPONSES" in api_db


def test_patch_endpoints_advertise_404_and_422(fake_repo: Path, new_module) -> None:
    """v0.4.16: PATCH /resource/{id} 可触发 404 (不存在) 和 422 (schema 校验).
    显式声明 responses 让 _custom_openapi 把 schema rewrite 成 ProblemDetail
    (否则 FastAPI 自动给 422 用 HTTPValidationError schema, 不符合 ADR §1).
    """
    new_module.main(["--name", "order", "--with-model"])
    api_db = (fake_repo / "src" / "admin_platform" / "domains" / "order" / "api.py").read_text()
    assert "PATCH_ERROR_RESPONSES" in api_db
    assert "responses=PATCH_ERROR_RESPONSES" in api_db


def test_repository_update_uses_patch_semantics(fake_repo: Path, new_module) -> None:
    """Generator templates 必须按 RFC 7396 PATCH 语义: 用 exclude_unset=True,
    不在 update() 里过滤 None。InMem / DB / StubRepo 三个 update 实现必须对齐,
    否则业务从 InMem 切到 DB 时会出现"显式置 None"行为差异。"""
    new_module.main(["--name", "order", "--with-model"])
    repo = (
        fake_repo / "src" / "admin_platform" / "domains" / "order" / "repository.py"
    ).read_text()
    test_service = (fake_repo / "tests" / "unit" / "test_order_service.py").read_text()

    assert "exclude_unset=True" in repo
    assert "if value is not None" not in repo  # DB update 不该过滤 None
    assert "if v is not None" not in repo  # 旧 InMem update pattern 不该回归
    assert "exclude_unset=True" in test_service
    assert "if value is not None" not in test_service  # _StubRepo 不该过滤 None


def test_write_rolls_back_on_oserror(
    fake_repo: Path, new_module, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the 3rd file write fails, the first 2 must be rolled back."""
    call_count = {"n": 0}
    real_write = Path.write_text

    def flaky_write(self: Path, content: str, *args, **kwargs) -> int:
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise OSError("disk full")
        return real_write(self, content, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", flaky_write)
    with pytest.raises(SystemExit) as exc:
        new_module.main(["--name", "order"])
    assert exc.value.code == 3
    # Domain dir may exist (mkdir succeeds) but should be empty after rollback
    domain = fake_repo / "src" / "admin_platform" / "domains" / "order"
    written_files = [p for p in domain.rglob("*") if p.is_file()]
    assert written_files == []


_FRAMEWORK_CODE_RE = re.compile(r"framework\.([A-Z][A-Z0-9_]*)")


def test_generator_text_only_cites_real_framework_codes() -> None:
    """守门：scripts/new_module.py 里出现的所有 framework.* 字面量必须能在
    core/idempotency.py 或 core/errors.py grep 到。

    历史：第七轮 review 发现 v0.4.17 我在 generator 注释里写了
    ``framework.IDEMPOTENT_KEY_REPLAY_MISMATCH``——这个常量根本不存在
    （真实值是 ``framework.IDEMPOTENCY_KEY_REUSED``）。新人按错误名做监控
    告警/日志 grep/SDK 枚举都会落空。

    设计：把 ``core/`` 里真实定义的字面量当 source-of-truth，generator 模板
    出现的每一个 ``framework.X`` 都必须在 SoT 里找到对应字符串。"""
    project_root = Path(__file__).resolve().parents[2]
    core = project_root / "src" / "admin_platform" / "core"
    sot = (core / "idempotency.py").read_text(encoding="utf-8") + (core / "errors.py").read_text(
        encoding="utf-8"
    )
    known_codes = set(_FRAMEWORK_CODE_RE.findall(sot))

    gen_text = (project_root / "scripts" / "new_module.py").read_text(encoding="utf-8")
    cited = set(_FRAMEWORK_CODE_RE.findall(gen_text))

    unknown = cited - known_codes
    assert not unknown, (
        f"scripts/new_module.py cites framework error codes not defined in "
        f"core/idempotency.py or core/errors.py: {sorted(unknown)}. "
        "Either add the constant to core/, or fix the typo in the generator."
    )
