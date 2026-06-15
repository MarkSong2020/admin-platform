# 外部锚点

> 本仓引用的全局规范 / 上游标准 / 团队资产的真相源位置。

## 全局规范

| 文档 | 位置 | 作用 |
|---|---|---|
| 全局 CLAUDE.md | `~/.claude/CLAUDE.md` | 工作约束、技术栈、安全基线、Git 习惯 |
| Python rules | `~/.claude/rules/python.md` | Python 主栈 / FastAPI 分层规则 / 测试 / Playwright / 异步 |
| Java/Spring rules | `~/.claude/rules/java-spring.md` | Java 维护规则（不主动新建） |
| Frontend rules | `~/.claude/rules/frontend.md` | Vue 3 / React 原型规则 |
| 通用原则 | `~/.claude/rules/principles.md` | Defense-in-Depth / 化简级联 / 测试反模式 / 跨语言代码风格 |

## 团队级 ADR

| 文档 | 位置 | 引用关系 |
|---|---|---|
| Cross-Language Conventions ADR 0001 | `team-engineering-adr/0001-cross-language-conventions.md` | 本仓所有契约的强制力来源；详见 [CROSS_LANGUAGE_ADR.md](./CROSS_LANGUAGE_ADR.md) |
| 服务前缀注册表 | `team-engineering-adr/service-prefix-registry.md` | ADR §3 / Q11 落地 |

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

CI/CD 平台由业务团队按 ADR 决议自选，模板不指定。以下为常见选项（详见 [../operations/CI_MIGRATION.md](../operations/CI_MIGRATION.md)）：

| 平台 | 用途 |
|---|---|
| 阿里云效 | CI 流水线（候选） |
| Jenkins | CI / 部署（候选） |
| GitHub Actions | CI（本仓 `.github/workflows/ci.yml` 是参考资产） |
| GitLab CI | CI（候选） |
| Datadog / ELK / Loki | 日志聚合 + 监控（具体选型 TBD） |
