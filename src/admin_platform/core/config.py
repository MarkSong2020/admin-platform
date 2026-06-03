"""通过 Pydantic Settings 读应用配置。

Errata #4 —— 官方源优先级（init kwargs > env > .env > secrets > defaults）。
生产部署通过 env vars 注入 secret；``.env`` 仅供本地开发用。

所有 env vars 都用 ``APP_`` 前缀，避免与平台 env 冲突。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# 允许的 URL scheme。``database_url`` / ``redis_url`` 类型保持 ``str`` 而不是
# 换成 Pydantic 的 URL 类型，这样下游消费方（``create_async_engine`` /
# ``Redis.from_url``）熟悉的 str 入参契约不变；validator 提供 typo 早失败
# （比如 ``reds://`` 或 ``postgresql+wrong://``），不必把类型拆开。
_ALLOWED_DB_SCHEMES = (
    "postgresql://",
    "postgresql+asyncpg://",
    "postgresql+psycopg://",
    "postgresql+psycopg2://",
)
_ALLOWED_REDIS_SCHEMES = (
    "redis://",
    "rediss://",  # TLS — Redis 6+
    "unix://",
)

_ALLOWED_JWT_ALGORITHMS = (
    "HS256",
    "HS384",
    "HS512",
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "admin-platform"
    # ADR §3 / §5 / §8 / §10 服务前缀 —— 必须与部署单元名、OpenAPI tag root、
    # Prometheus / Datadog `service` label、JWT `aud` claim 一致。详见
    # ~/IdeaProjects/team-engineering-adr/service-prefix-registry.md 的
    # 权威注册表与命名规则。
    # README 的 sed-rename 流程克隆模板时会和包名一起替换这个值。
    service_id: str = "admin_platform"
    debug: bool = False
    # 用 Literal 约束 —— Pydantic 在 Settings 构造时就拒掉 typo（如
    # APP_LOG_LEVEL=INOF），不会推迟到后面 configure_logging() 才报错。
    log_level: LogLevel = "INFO"
    request_id_header: str = "X-Request-ID"

    cors_allow_origins: list[str] = []
    cors_allow_credentials: bool = True

    # 数据库 —— 默认指向本地 compose db；生产必须通过 env 注入。
    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/app"
    db_echo: bool = False
    # Pool 大小有边界，避免类似 ``APP_DB_POOL_SIZE=-1`` /
    # ``APP_DB_MAX_OVERFLOW=10000`` 这种 typo 在构造时被抓到，
    # 而不是延后到第一次 query 时变成晦涩的 SQLAlchemy 错误。
    # 上限放得宽松但有限 —— 更紧的指南见 DEPLOYMENT.md「DB pool 大小」段。
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=200)

    # Idempotency-Key（ADR §11）：Redis-backed cache，POST 安全重试用。
    redis_url: str = "redis://localhost:6379/0"
    idempotency_enabled: bool = True
    # ADR §11 规定 24h。最低 60s —— 比这更短等于事实上关闭幂等
    # （客户端网络抖动后的重试会击穿 cache）。
    idempotency_ttl_seconds: int = Field(default=86400, ge=60)
    # In-flight SET NX 锁的 TTL（v0.4.9+）。**必须**大于最慢合法 handler
    # 的运行时间 + 上游重试窗口 —— 否则一个长 POST 在锁到期之后才完成，
    # 重试会重跑副作用。容量规划见 doc/operations/DEPLOYMENT.md。
    # 下限 5s（亚秒级锁与 handler 冷启会有竞态）；上限 1h（更长就应该
    # 走 DB idempotency_keys 表，而不是 Redis 锁）。
    idempotency_lock_ttl_seconds: int = Field(default=30, ge=5, le=3600)

    # ASGI lifespan 启动时立即 probe DB + Redis。True 时不可达依赖会让 startup
    # 失败 → uvicorn 退出 → K8s 不把 pod 标记为 ready。False（向后兼容默认）
    # 时连接保持 lazy，只有 ``/readyz`` 轮询能发现故障。生产应当显式设置
    # ``APP_STARTUP_EAGER_CONNECT=true``。
    startup_eager_connect: bool = False

    # OpenTelemetry SDK（ADR §4）。默认关闭；生产设 APP_OTEL_ENABLED=true。
    # exporter endpoint / service name 走标准 OTEL_EXPORTER_OTLP_ENDPOINT /
    # OTEL_SERVICE_NAME env vars，不在此重复。
    otel_enabled: bool = False

    # JWT Bearer 鉴权（ADR §5）。默认关闭（向后兼容）；生产必须显式开启。
    # iss/aud 校验默认不启用 —— 等团队 SSO 上线 + Q4 决议后配置。
    auth_enabled: bool = False
    auth_jwt_secret: str = ""  # HMAC shared secret 或 RSA/EC public key PEM
    auth_jwt_algorithm: str = "HS256"  # HS256 / RS256 / ES256
    auth_jwt_issuer: str = ""  # 非空时校验 iss claim
    auth_jwt_audience: str = ""  # 非空时校验 aud claim（单值，应与 Settings.service_id 一致）
    # 无需 token 的公开路径前缀。精确前缀匹配（不含 query string）。
    # /api/v1/auth/login：登录端点本身免 token（它负责签发 token）。
    auth_public_paths: list[str] = Field(
        default=[
            "/healthz",
            "/startupz",
            "/readyz",
            "/docs",
            "/openapi.json",
            "/api/v1/auth/login",
        ]
    )
    # access token 存活时长（秒）。P0 只签发 access token，不做 refresh，
    # 所以 TTL 短一点（默认 2h）以收敛失窃 token 的暴露窗口；refresh + 撤销
    # 下放 P1（须存 jti+hash 才能撤销）。下限 60s —— 比这更短令牌还没用就过期。
    auth_access_token_ttl_seconds: int = Field(default=7200, ge=60)

    @field_validator("database_url")
    @classmethod
    def _validate_database_url_scheme(cls, value: str) -> str:
        # 让 scheme typo（漏写 ``ql`` 的 ``postgres://``、或
        # ``postgresql+asynpcg``）在 Settings 构造时就暴露，不要拖到
        # ``create_async_engine`` 在第一次 DB 调用时吐晦涩的 dialect-load 错。
        if not value.startswith(_ALLOWED_DB_SCHEMES):
            allowed = ", ".join(_ALLOWED_DB_SCHEMES)
            raise ValueError(f"database_url must start with one of: {allowed}")
        return value

    @field_validator("redis_url")
    @classmethod
    def _validate_redis_url_scheme(cls, value: str) -> str:
        if not value.startswith(_ALLOWED_REDIS_SCHEMES):
            allowed = ", ".join(_ALLOWED_REDIS_SCHEMES)
            raise ValueError(f"redis_url must start with one of: {allowed}")
        return value

    @field_validator("auth_jwt_algorithm")
    @classmethod
    def _validate_jwt_algorithm(cls, value: str) -> str:
        if value not in _ALLOWED_JWT_ALGORITHMS:
            allowed = ", ".join(_ALLOWED_JWT_ALGORITHMS)
            raise ValueError(f"auth_jwt_algorithm must be one of: {allowed}")
        return value

    @model_validator(mode="after")
    def _reject_wildcard_with_credentials(self) -> Self:
        if self.cors_allow_credentials and "*" in self.cors_allow_origins:
            raise ValueError(
                "CORS: allow_credentials=True 与 allow_origins=['*'] 不兼容, 请使用具体域名白名单"
            )
        return self

    @model_validator(mode="after")
    def _validate_auth_secret_when_enabled(self) -> Self:
        if not self.auth_enabled:
            return self
        if not self.auth_jwt_secret:
            raise ValueError("auth_jwt_secret 不能为空；auth_enabled=true 时必须提供 JWT 签名密钥")
        if self.auth_jwt_algorithm.startswith("HS"):
            min_len = 32
            if len(self.auth_jwt_secret) < min_len:
                raise ValueError(
                    f"auth_jwt_secret 长度 {len(self.auth_jwt_secret)} < {min_len} "
                    f"(HS* 算法要求至少 {min_len} bytes, RFC 7518 §3.2)"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
