"""Settings tests — defaults, env prefix, source priority (Errata #4), CORS validator."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from admin_platform.core.config import Settings

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


def test_access_token_ttl_default_is_2h() -> None:
    """P0 只发 access token、不做 refresh，默认 TTL 2h（7200s）收敛失窃窗口。"""
    assert Settings().auth_access_token_ttl_seconds == 7200


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
