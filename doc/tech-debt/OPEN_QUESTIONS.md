# Open Questions（ADR 待评审项）

> ADR 0001 Open Questions 在本仓的跟踪（团队仓 ADR 中也维护一份）。已决议项划除；新议题在团队 PR 中提，**不**在本仓单独加。

| # | 议题 | 触发条件 | P |
|---|---|---|---|
| Q1 | 完全切到 RFC 9457 `application/problem+json`（严格 Content-Type + 字段严格化） | 前端 / 移动端 SDK 对接前 | P2 |
| Q2 | 错误响应是否在 5xx 时强制带 `trace_id`（即使 OTel 未接入也生成）| OTel 接入或第一次跨服务 5xx 排障困难 | P2 |
| Q3 | `errors` 字段 schema 跨语言统一（Pydantic vs Bean Validation 不同形）| **触发条件半到位**：v0.4.13 Python 侧已去掉 `input` 字段（脱敏），剩 `loc/msg/type/ctx`；下一步等 Java 侧 `BeanValidation` errors shape 对齐评审 | P1 |
| Q4 | JWT `iss` / `aud` 校验策略（白名单 vs 通配 vs 内部签发服务）| 团队 SSO 上线前 | P1 | v0.5.3 `core/auth.py` 已支持 `APP_AUTH_JWT_ISSUER` / `APP_AUTH_JWT_AUDIENCE` 配置开关；决议后只需开启 env 即可启用校验 |

> **Q4 边界提醒（aud 默认不校验）**：ADR §5 正文写 `aud` **必填**，但本模板默认 `APP_AUTH_JWT_AUDIENCE` 为空 → 即便 `auth_enabled=True` 也**不强制校验 aud**（向后兼容 + 等本 Q 决议，见 `core/auth.py::AuthConfig.validate_audience`）。这是有意权衡，非遗漏。**上线接 SSO 时务必把 `APP_AUTH_JWT_AUDIENCE` 配成本服务 service_id**，否则 service A 签发的 token 可被拿去访问 service B（ADR §5 的核心防护点）。
| Q5 | v1 → v2 共存机制（双 `@RouterDeprecation` 标记？同进程两套 router？） | 第一个 v2 接口出现前 | P1 |
| Q6 | Contract test 选型（schemathesis / pact / OpenAPI snapshot diff） | 第一个跨语言契约 regression 出现前 | P2 |
| ~~Q7~~ | ~~Idempotency-Key 服务端实现：Redis 存储 / TTL / 冲突响应码~~ | ✅ **v0.4.3 已决议**（Redis / endpoint opt-in / 24h / Stripe cached replay） | — |
| ~~Q8~~ | ~~startup probe 是否强制；K8s 部署 manifest 模板~~ | ✅ **v0.4.4 已决议**（`/startupz` 强制；ADR §6 加 K8s yaml 示例） | — |
| Q9 | `operation_id` snake_case vs camelCase（SDK 生成器跨语言偏好分歧）| SDK 自动生成上线前 | P2 |
| Q10 | 监控指标命名独立 ADR（Prometheus label / Datadog service tag 规范） | 第一个跨服务监控告警建立时 | P2 |
| ~~Q11~~ | ~~服务前缀命名空间治理~~ | ✅ **v0.4.5 已决议**：`~/IdeaProjects/team-engineering-adr/service-prefix-registry.md` 落地——6 条命名规则 / 5 处上下文同源映射 / PR 申请流程 + Platform team 仲裁 / 6 个月弃用窗口 | — |

## 状态解读

- **触发条件未到** → 暂不决议，记在此表
- **触发条件到了** → 团队 PR 提决议草稿，合入 ADR 0001
- **决议后** → ADR Revision history 记一笔，本表划除

## 与 KNOWN_DEVIATIONS.md 的区别

- KNOWN_DEVIATIONS = **实现 vs ADR 差距**（ADR 已决议，代码没跟）
- OPEN_QUESTIONS = **ADR 尚未决议**（在等触发条件 / 待团队评审）

修一个 known deviation = 改代码；解一个 open question = 改 ADR + 可能改代码。

## 历史决议（已划除）

详见团队仓 ADR Revision history。
