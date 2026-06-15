# 标准与原则（统一入口）

> **先标准、原则，后用法。** 本页只做「主题 → 正本」的一句话索引，**不重复抄正本内容**。
> 想动手前先在这里定位「该遵守哪条约束」，再点链接读细节。
> 受众：开源使用者 / Fork 二次开发者 / 业务开发者 / baseline 维护者。

---

## 分层契约（结构边界，机检）

业务模块默认 **5 层**（api → service → repository / schemas / models），层级边界是 hard rule，由 `make check` 的 **import-linter** 机检（直接跨层 import 让 CI 红）。设计原则见 [`architecture/LAYERED_DESIGN.md`](./architecture/LAYERED_DESIGN.md)；机检契约正本是仓库根 [`.importlinter`](../.importlinter)。

当前 **10 条契约**（C1–C10）：

| 契约 | 主题（约束）|
|---|---|
| **C1** domain-layers | 域内 `api > service > repository` 单向，禁反向（containers 纳入已长出完整三层的域）|
| **C2** api-not-repository | `domains.*.api` 禁直接 import `repository`（组合根在 `deps.py`）|
| **C3** service-not-fastapi | `domains.*.service` 禁 import `fastapi` |
| **C4** repository-not-fastapi | `domains.*.repository` 禁 import `fastapi` |
| **C5** schemas-not-models | `domains.*.schemas` 禁 import `models`（共享 enum 放 `enums.py`）|
| **C6** schemas-not-sqlalchemy | `domains.*.schemas` 禁 import `sqlalchemy` |
| **C7** models-not-pydantic | `domains.*.models` 禁 import `pydantic` |
| **C8** authz-not-domains-core | `authz` 纯叶子基座，禁 import `domains` / `core`（避免循环依赖）|
| **C9** apiv1-not-repository | `api.v1` 跨域聚合层禁直接 import `domains.*.repository`（不绕组合根）|
| **C10** excel-leaf | `excel` 纯叶子机制，禁 import `fastapi` / `sqlalchemy` / `domains` / `core` |

> **语义边界**（api 不写业务逻辑、repository 不抛业务异常等无法静态投影的约定）由 code review 兜，不在 import-linter 覆盖范围。

---

## 命名约定

错误码 `type` / OpenAPI `tag` / `operation_id` / 服务前缀 / 表名 / 模块名一张表搞清——**发布到生产即锁死**，新增前必查。正本：[`standards/NAMING_CONVENTIONS.md`](./standards/NAMING_CONVENTIONS.md)。

---

## 错误响应 / AppError

全仓 4xx/5xx 都是同一个 shape——RFC 9457-aligned `ProblemDetail`，由 `core/errors.py` 统一 handler 链产出；业务异常一律用 `AppError(code, title, *, detail=None, status_code=400, errors=None)` 抛出，错误码格式 `{service}.{ERROR_CODE}`。正本：[`architecture/ERROR_RESPONSE.md`](./architecture/ERROR_RESPONSE.md)。

---

## 数据建模

**建模标准**（怎么设计：id / created_at / updated_at / 列级中文 comment / 枚举 / FK / comment 门禁，全部沿用模板基线，单租户回归后无追加）见 [`standards/DATA_MODELING.md`](./standards/DATA_MODELING.md)；**当前 schema 速览**（生成物，从 ORM models 自省，`make schema-doc` 再生）见 [`architecture/DATA_MODEL.md`](./architecture/DATA_MODEL.md)。

---

## AI 编码规则

AI agent（Claude / Codex / Cursor 等）在本仓做业务开发的工作流约束与红线——含决策树、改/禁改文件清单、提交前自检、docstring 默认简体中文。正本：[`standards/AI_CODING_RULES.md`](./standards/AI_CODING_RULES.md)。

> 业务模块代码生成蓝本（`make new-module` 五层骨架）见 [`standards/CODE_GENERATOR.md`](./standards/CODE_GENERATOR.md)。

---

## 可观测性 / 请求生命周期

可观测性三件套（JSON 结构化日志、`X-Request-ID` 链路、W3C `trace-id`）见 [`architecture/OBSERVABILITY.md`](./architecture/OBSERVABILITY.md)；一个请求从落地到响应经过的 middleware 链与处理顺序见 [`architecture/REQUEST_LIFECYCLE.md`](./architecture/REQUEST_LIFECYCLE.md)。

---

## 安全基线

框架层落地的 defense-in-depth 实践汇总（一句话点到，细节见对应 spec）：

- **输入校验**：所有外部输入走 Pydantic schema 统一校验，禁 handler 内手写松散解析。
- **参数化查询**：数据访问走 SQLAlchemy ORM / 参数化，禁字符串拼接 SQL。
- **错误脱敏**：生产不返回 stack trace；`ProblemDetail.detail` / `errors` 受 debug 开关脱敏。见 [`architecture/ERROR_RESPONSE.md`](./architecture/ERROR_RESPONSE.md)。
- **认证加固**：Argon2 密码 + JWT；refresh token 轮换 + reuse detection（RFC 9700）；失败 N 次触算术文本验证码 + 账号软锁 + IP 限流。见 [`specs/2026-06-09-p1.4-login-enhancement.md`](./specs/2026-06-09-p1.4-login-enhancement.md)。
- **文件上传**：扩展名白名单 + 魔数头弱类型校验；`object_key` = uuid4（不含原文件名，防穿越/覆盖）；存储路径 `resolve()` 守卫防 `../` 穿越；边写边累计 size/sha256（不信 Content-Length），超限抛错并清理半成品。见 [`specs/2026-06-11-p5-file-management.md`](./specs/2026-06-11-p5-file-management.md)。
- **文件下载**：`Content-Disposition` 注入防御（RFC 5987，剥 CRLF/引号）+ `X-Content-Type-Options: nosniff`（兜 XSS）。见 [`specs/2026-06-11-p5-file-management.md`](./specs/2026-06-11-p5-file-management.md)。
- **Excel formula injection 防御**：导出 cell 以 `=` `+` `-` `@` 开头 → writer 前缀单引号文本化；导入流式累计 size 超限 413（防 OOM）。见 [`specs/2026-06-11-p5-excel-import-export.md`](./specs/2026-06-11-p5-excel-import-export.md)。
- **定时任务防 RCE**：`JobHandlerRegistry` 白名单——DB 只存 `handler_key` + `params_json`，schema 无任意调用字段，反 RuoYi 任意调用串。见 [`specs/2026-06-10-p4-monitoring-tasks.md`](./specs/2026-06-10-p4-monitoring-tasks.md)。
- **监控字段白名单**：缓存监控只取 Redis INFO 的具名字段，不回整个 INFO dict（不泄露 config_file / 复制密钥线索）。见 [`specs/2026-06-10-p4-monitoring-tasks.md`](./specs/2026-06-10-p4-monitoring-tasks.md)。
- **生产门禁**：CORS 默认拒绝、生产强制校验必填密钥、迁移 gated 需单独授权。见 [`tech-debt/KNOWN_DEVIATIONS.md`](./tech-debt/KNOWN_DEVIATIONS.md)。

> 漏洞报告流程见根目录 [`SECURITY.md`](../SECURITY.md)。

---

## 相关入口

- 文档总导航 → [`INDEX.md`](./INDEX.md)
- 各阶段设计决策（spec 导航）→ [`specs/INDEX.md`](./specs/INDEX.md)
- 贡献流程 → [`../CONTRIBUTING.md`](../CONTRIBUTING.md)
- 全局 Python Web 服务规则 → `~/.claude/rules/python.md`
