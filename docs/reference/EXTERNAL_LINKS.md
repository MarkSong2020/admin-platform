# 外部锚点

> 本仓引用的上游标准（RFC / W3C）、工具官方文档与跨语言协同契约的真相源位置。

## 跨语言协同契约

| 文档 | 位置 | 引用关系 |
|---|---|---|
| 跨语言协同契约（错误码 / 链路 / 分页 / 幂等） | 本仓 | HTTP 边界约定 + 实现位置速查 → [CROSS_LANGUAGE_ADR.md](./CROSS_LANGUAGE_ADR.md) |

## 上游标准（RFC / W3C）

| 标准 | 链接 | 用在哪 |
|---|---|---|
| RFC 9457 Problem Details for HTTP APIs | https://datatracker.ietf.org/doc/html/rfc9457 | §1 错误响应 shape 字段命名 |
| RFC 9110 HTTP Semantics §15.5 | https://datatracker.ietf.org/doc/html/rfc9110#name-client-error-4xx | §2 400 vs 422 语义 |
| RFC 7519 JSON Web Token | https://datatracker.ietf.org/doc/html/rfc7519 | §5 JWT claims（sub / iss / aud / exp / iat） |
| W3C Trace Context | https://www.w3.org/TR/trace-context/ | §4 `traceparent` header 解析 |
| RFC 6648 Deprecating X- Prefix | https://datatracker.ietf.org/doc/html/rfc6648 | §4 `X-Request-ID` 留用理由（不改名 `Correlation-ID`） |

## 工具 / 框架文档

| 工具 | 链接 |
|---|---|
| FastAPI | https://fastapi.tiangolo.com/ |
| SQLAlchemy 2.x async | https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html |
| Alembic | https://alembic.sqlalchemy.org/ |
| uv | https://docs.astral.sh/uv/ |
| Pydantic v2 | https://docs.pydantic.dev/latest/ |
| ruff | https://docs.astral.sh/ruff/ |
| pyright | https://microsoft.github.io/pyright/ |
| pip-audit | https://pypi.org/project/pip-audit/ |
| OrbStack | https://orbstack.dev/ |

## 候选平台 / 常见参考

CI/CD 平台按需自选，本仓不指定。以下为常见选项（详见 [../operations/CI_MIGRATION.md](../operations/CI_MIGRATION.md)）：

| 平台 | 用途 |
|---|---|
| 阿里云效 | CI 流水线（候选） |
| Jenkins | CI / 部署（候选） |
| GitHub Actions | CI（本仓 `.github/workflows/ci.yml` 是参考资产） |
| GitLab CI | CI（候选） |
| Datadog / ELK / Loki | 日志聚合 + 监控（具体选型 TBD） |
