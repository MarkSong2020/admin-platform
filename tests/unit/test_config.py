"""Settings tests — defaults, env prefix, source priority (Errata #4), CORS validator."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from admin_platform.core.config import Settings, get_settings
from admin_platform.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "admin-platform"
    assert settings.service_id == "admin_platform"
    assert settings.debug is False
    assert settings.log_level == "INFO"
    assert settings.request_id_header == "X-Request-ID"
    assert settings.cors_allow_origins == []
    assert settings.cors_allow_credentials is True


def test_service_id_overrides_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR §3 / §5 service prefix — sourced from APP_SERVICE_ID env var."""
    monkeypatch.setenv("APP_SERVICE_ID", "payment")
    settings = Settings()
    assert settings.service_id == "payment"


def test_startup_eager_connect_default_false() -> None:
    """Baseline: lifespan stays lazy (test / dev don't need live deps)."""
    assert Settings().startup_eager_connect is False


def test_startup_eager_connect_overrides_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production opt-in via APP_STARTUP_EAGER_CONNECT=true."""
    monkeypatch.setenv("APP_STARTUP_EAGER_CONNECT", "true")
    assert Settings().startup_eager_connect is True


def test_idempotency_lock_ttl_default_is_30s() -> None:
    """v0.4.9: baseline must NOT be longer — services with slow handlers
    must opt up via APP_IDEMPOTENCY_LOCK_TTL_SECONDS, deliberately."""
    assert Settings().idempotency_lock_ttl_seconds == 30


def test_idempotency_lock_ttl_overrides_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Services with handlers > 30s MUST raise this above
    (slowest handler runtime + upstream retry window) per DEPLOYMENT.md."""
    monkeypatch.setenv("APP_IDEMPOTENCY_LOCK_TTL_SECONDS", "180")
    assert Settings().idempotency_lock_ttl_seconds == 180


def test_access_token_ttl_default_is_30min() -> None:
    """默认 TTL 30min（1800s，hardening-r1 E2）：access 不可即时撤销，TTL = 踢人后最长残留窗口。"""
    assert Settings().auth_access_token_ttl_seconds == 1800


def test_access_token_ttl_overrides_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """部署可经 APP_AUTH_ACCESS_TOKEN_TTL_SECONDS 调整令牌存活时长。"""
    monkeypatch.setenv("APP_AUTH_ACCESS_TOKEN_TTL_SECONDS", "3600")
    assert Settings().auth_access_token_ttl_seconds == 3600


def test_access_token_ttl_below_minimum_is_rejected() -> None:
    """下限 60s —— 比这更短令牌还没用就过期，应在构造时报错而非运行期。"""
    with pytest.raises(ValidationError, match="auth_access_token_ttl_seconds"):
        Settings(auth_access_token_ttl_seconds=59)


def test_env_with_prefix_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.debug is True
    assert settings.log_level == "DEBUG"


def test_env_without_prefix_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = Settings()
    assert settings.debug is False
    assert settings.log_level == "INFO"


def test_init_kwargs_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_LOG_LEVEL", "DEBUG")
    settings = Settings(log_level="WARNING")
    assert settings.log_level == "WARNING"


def test_log_level_accepts_valid_levels(monkeypatch: pytest.MonkeyPatch) -> None:
    """LogLevel Literal: 5 official names must all pass at construction time."""
    for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        monkeypatch.setenv("APP_LOG_LEVEL", level)
        assert Settings().log_level == level


def test_log_level_rejects_typos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Typos like APP_LOG_LEVEL=INOF must fail at Settings construction,
    not silently fall through to a runtime ValueError in configure_logging()."""
    monkeypatch.setenv("APP_LOG_LEVEL", "INOF")
    with pytest.raises(ValidationError, match="log_level"):
        Settings()


def test_database_url_scheme_typo_is_rejected() -> None:
    """v0.4.14: ``database_url`` validator catches ``postgres://`` (missing
    ``ql``) and other dialect typos at construction time, not at first query.
    Pre-v0.4.14 the typo only surfaced as a SQLAlchemy dialect-load error
    deep in the first DB call."""
    with pytest.raises(ValidationError, match="database_url"):
        Settings(database_url="postgres://localhost/x")  # missing 'ql'


def test_database_url_asyncpg_dialect_is_allowed() -> None:
    assert Settings(database_url="postgresql+asyncpg://u:p@h:5432/d").database_url


def test_redis_url_scheme_typo_is_rejected() -> None:
    """v0.4.14: catch ``reds://`` typos before Redis.from_url() does."""
    with pytest.raises(ValidationError, match="redis_url"):
        Settings(redis_url="reds://localhost:6379/0")


def test_redis_tls_scheme_is_allowed() -> None:
    """``rediss://`` (TLS) is a first-class supported scheme."""
    assert Settings(redis_url="rediss://prod-cache.example.com:6380/0").redis_url


def test_idempotency_ttl_below_minimum_is_rejected() -> None:
    """v0.4.14: ``APP_IDEMPOTENCY_TTL_SECONDS=0`` would silently disable
    de-dupe — bound it at 60s minimum to make the misconfiguration loud."""
    with pytest.raises(ValidationError, match="idempotency_ttl_seconds"):
        Settings(idempotency_ttl_seconds=0)


def test_idempotency_lock_ttl_bounds() -> None:
    """v0.4.14: 5s floor (handler cold-start race) / 1h ceiling (use DB table
    for longer protection)."""
    with pytest.raises(ValidationError, match="idempotency_lock_ttl_seconds"):
        Settings(idempotency_lock_ttl_seconds=1)
    with pytest.raises(ValidationError, match="idempotency_lock_ttl_seconds"):
        Settings(idempotency_lock_ttl_seconds=99999)


def test_db_pool_size_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="db_pool_size"):
        Settings(db_pool_size=0)
    with pytest.raises(ValidationError, match="db_pool_size"):
        Settings(db_pool_size=-1)


def test_db_max_overflow_allows_zero_but_not_negative() -> None:
    """Overflow == 0 is a legitimate "strict pool" config; negative is not."""
    assert Settings(db_max_overflow=0).db_max_overflow == 0
    with pytest.raises(ValidationError, match="db_max_overflow"):
        Settings(db_max_overflow=-5)


def test_cors_wildcard_with_credentials_is_rejected() -> None:
    with pytest.raises(ValidationError, match="CORS"):
        Settings(cors_allow_origins=["*"], cors_allow_credentials=True)


def test_cors_wildcard_without_credentials_is_allowed() -> None:
    settings = Settings(cors_allow_origins=["*"], cors_allow_credentials=False)
    assert settings.cors_allow_origins == ["*"]


_ENV_KEY_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def test_env_example_covers_all_settings_fields() -> None:
    """`.env.example` 必须列全 Settings 每个可配字段，键带 APP_ 前缀。

    历史：v0.4.16 review 发现 Settings 已加 service_id / Redis / 幂等 TTL /
    startup eager-connect 等字段，但 .env.example 还停在 v0.4.6 的 5 项。
    新服务复制 .env.example 时看不到生产开关，踩坑。

    守门：以 ``Settings.model_fields`` 为 source of truth，强制 .env.example
    每个字段出现一次（值是什么不约束，只看键覆盖）。
    """
    example_path = REPO_ROOT / ".env.example"
    example_keys = set(_ENV_KEY_RE.findall(example_path.read_text(encoding="utf-8")))

    settings_fields = set(Settings.model_fields)
    expected_env_keys = {f"APP_{name.upper()}" for name in settings_fields}

    missing = expected_env_keys - example_keys
    extra = example_keys - expected_env_keys

    assert not missing, f".env.example missing APP_* keys for Settings fields: {sorted(missing)}"
    assert not extra, f".env.example has APP_* keys that no longer map to Settings: {sorted(extra)}"


# ---- 生产门禁 _enforce_production_safety（hardening：脚手架默认值裸奔到生产的 fail-fast）----

# environment=production 的合法基线：auth 开 + 强 secret + pepper + debug 关。
# 各测试在此基础上单独打破一项，验证门禁逐项把关。
_PROD_OK = {
    "environment": "production",
    "auth_enabled": True,
    "auth_jwt_secret": "x" * 32,  # HS256 要求 ≥32 bytes
    "auth_refresh_token_pepper": "prod-pepper",
    "debug": False,
}


def test_environment_defaults_to_local() -> None:
    """默认 local —— 保持现有零强制行为，不破坏本地/CI。"""
    assert Settings().environment == "local"


def test_non_production_does_not_enforce_safety() -> None:
    """local/dev/staging 不触发门禁：auth 关 + debug 开 + 空 pepper 均可构造（脚手架默认即此态）。"""
    for env in ("local", "dev", "staging"):
        settings = Settings(environment=env, auth_enabled=False, debug=True)
        assert settings.environment == env


def test_production_happy_path_passes() -> None:
    """production 全部安全项就位时正常构造。"""
    settings = Settings(**_PROD_OK)
    assert settings.environment == "production"
    assert settings.auth_enabled is True


def test_production_rejects_auth_disabled() -> None:
    """production 关鉴权 → 启动期拒绝。"""
    with pytest.raises(ValidationError, match="auth_enabled 必须为 True"):
        Settings(**{**_PROD_OK, "auth_enabled": False})


def test_production_rejects_debug_enabled() -> None:
    """production 开 debug → 启动期拒绝（不允许暴露堆栈/调试细节）。"""
    with pytest.raises(ValidationError, match="debug 必须为 False"):
        Settings(**{**_PROD_OK, "debug": True})


def test_production_rejects_empty_pepper() -> None:
    """production 空 refresh pepper → 启动期拒绝。"""
    with pytest.raises(ValidationError, match="auth_refresh_token_pepper 不能为空"):
        Settings(**{**_PROD_OK, "auth_refresh_token_pepper": ""})


def test_production_empty_secret_caught_by_existing_validator() -> None:
    """production 强制 auth_enabled=True 会连带触发已有 secret 校验：空 secret 被 _validate_auth_secret_when_enabled 拦下。"""
    with pytest.raises(ValidationError, match="auth_jwt_secret 不能为空"):
        Settings(**{**_PROD_OK, "auth_jwt_secret": ""})


def test_production_aggregates_all_violations() -> None:
    """多项缺失一次性收齐（运维一眼看全，不用改一处重启再撞下一处）。"""
    with pytest.raises(ValidationError) as exc_info:
        Settings(environment="production", auth_enabled=True, auth_jwt_secret="x" * 32, debug=True)
    message = str(exc_info.value)
    assert "debug 必须为 False" in message
    assert "auth_refresh_token_pepper 不能为空" in message


def test_production_enforced_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """门禁经 APP_ENVIRONMENT=production env var 也生效（真实部署注入路径）。"""
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    with pytest.raises(ValidationError, match="auth_enabled 必须为 True"):
        Settings()


def test_production_default_public_paths_pass() -> None:
    """脚手架默认 auth_public_paths 全是具体端点，不触发命名空间遮蔽检查。"""
    assert Settings(**_PROD_OK).auth_public_paths  # 默认值未被改写即通过


@pytest.mark.parametrize("broad", ["/", "/api", "/api/v1", "/api/v1/"])
def test_production_rejects_namespace_shadowing_public_path(broad: str) -> None:
    """production 下 public_paths 含 /、/api、/api/v1 级宽前缀 → 拒绝（AuthMiddleware 会全量放行）。"""
    with pytest.raises(ValidationError, match="命名空间宽前缀"):
        Settings(**{**_PROD_OK, "auth_public_paths": ["/healthz", broad]})


def test_production_allows_specific_public_path() -> None:
    """具体公开端点（含 /api/v1 下的具体子路径）不被误拒——只拦命名空间级宽前缀。"""
    settings = Settings(
        **{
            **_PROD_OK,
            "auth_public_paths": ["/healthz", "/api/v1/auth/login", "/api/v1/public/ping"],
        }
    )
    assert "/api/v1/public/ping" in settings.auth_public_paths


# ---- OWASP API9 防护：生产默认关闭交互式文档（/docs、/redoc、/openapi.json）----
#
# create_app() 读 get_settings()（lru_cache），故经 APP_* env var 注入生产配置 + 清缓存，
# 让 create_app 看到 production 设置（与现有 test_production_enforced_via_env 同模式）。
# 这里把 _PROD_OK 基线（auth/secret/pepper/debug）经 env 给齐，否则生产门禁会拒绝构造。

# _PROD_OK 的 env 形态（同值，键加 APP_ 前缀）—— 满足 _enforce_production_safety 门禁。
_PROD_OK_ENV = {
    "APP_ENVIRONMENT": "production",
    "APP_AUTH_ENABLED": "true",
    "APP_AUTH_JWT_SECRET": "x" * 32,
    "APP_AUTH_REFRESH_TOKEN_PEPPER": "prod-pepper",
    "APP_DEBUG": "false",
}


def _build_app_with_env(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]):
    """注入 env + 清 get_settings 缓存后构造 app（避免 lru_cache 命中陈旧配置）。"""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    try:
        return create_app()
    finally:
        get_settings.cache_clear()


def test_production_hides_docs_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产 + 默认（expose=False）→ openapi_url is None，三条文档路由不存在。"""
    app = _build_app_with_env(monkeypatch, _PROD_OK_ENV)
    assert app.openapi_url is None
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/openapi.json" not in paths
    assert "/docs" not in paths
    assert "/redoc" not in paths


def test_production_exposes_docs_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产 + APP_EXPOSE_DOCS_IN_PRODUCTION=true → 三条文档路由恢复存在。"""
    app = _build_app_with_env(
        monkeypatch, {**_PROD_OK_ENV, "APP_EXPOSE_DOCS_IN_PRODUCTION": "true"}
    )
    assert app.openapi_url == "/openapi.json"
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/openapi.json" in paths
    assert "/docs" in paths
    assert "/redoc" in paths


def test_local_keeps_docs_exposed(monkeypatch: pytest.MonkeyPatch) -> None:
    """非生产（默认 local）→ 文档路由常开（回归守门：本地/CI 不受影响）。"""
    app = _build_app_with_env(monkeypatch, {})
    assert app.openapi_url == "/openapi.json"
    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/openapi.json" in paths
    assert "/docs" in paths
    assert "/redoc" in paths
