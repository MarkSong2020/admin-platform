# admin-platform

> 单租户后台管理脚手架（对标 RuoYi / 若依），用现代 Python 栈实现。
> **FastAPI + uv + SQLAlchemy 2.x (async) + Alembic + Redis + Ruff + Pyright + Pytest**。

开箱即用的后台「刚需地基」——认证、RBAC、审计、运营配置、监控、文件与 Excel 全部内置，照同一套五层分层 + 契约约束生长业务域。适合：**Fork 来搭自己的后台**、**直接部署当成品**、或**读代码学架构**。

> 当前应用版本 **`v0.0.1`**，阶段 P0–P5 全部落地（后端），P6 Vue 前端进行中。派生自团队脚手架 `python-web-service-template`（lineage v0.5.3）。

---

## ✨ 内置能力（对标 RuoYi）

| 领域 | 已落地 |
|---|---|
| 认证 | JWT 签发/校验 + Argon2 密码 + refresh 轮换 + 图形验证码 + 登录限流 + CLI 建超管 |
| RBAC | 部门 / 角色 / 菜单 / 岗位 + RuoYi 五档数据权限 + `getInfo`/`getRouters` |
| 审计 | 操作日志 + 登录日志持久化（成功 in-tx 原子 / 失败缓冲）+ 中间件捕获 IP/UA |
| 运营配置 | 字典（类型+数据，FK RESTRICT）+ 参数（热更新读穿）+ 通知公告 |
| 监控 | 服务监控（psutil CPU/内存/磁盘）+ 缓存监控（Redis INFO 降级）+ 在线用户（强制下线）|
| 定时任务 | APScheduler + PG leader election + DB execution claim（多 worker 安全）+ handler 白名单（防 RCE）|
| 文件 | 对标 sys_oss：存储抽象 + 扩展名白名单 + 魔数校验 + 流式上传下载 + 软删 |
| Excel | 通用导入导出机制（formula injection 防御 + 全量错误报告）|
| 工程基线 | RFC9457 错误响应 + X-Request-ID/traceparent + Idempotency-Key + 三轨健康检查 + OpenAPI 契约守门 |

---

## 🚀 快速开始

```bash
make init                       # uv sync --all-extras --dev
uv run pre-commit install       # 必须：装 git hook（漏装首次 commit 必被拦）
make compose-up && make migrate # 起 PostgreSQL + 应用 Alembic 迁移
make dev                        # http://127.0.0.1:8000/healthz
make check                      # ruff + pyright + pytest 全绿
```

打开 <http://localhost:8000/docs> 看 OpenAPI。完整起步（建超管、登录拿 token）→ **[`docs/guide/GETTING_STARTED.md`](./docs/guide/GETTING_STARTED.md)**。

## 📖 文档

先读**标准与原则**，再看**怎么用**——这是本仓的文档次序。

| 你是谁 | 从这里进 |
|---|---|
| 🧭 找最快路径 | **[`docs/INDEX.md`](./docs/INDEX.md)**（按角色导航总入口）|
| 📐 想先搞清标准/原则 | **[`docs/STANDARDS.md`](./docs/STANDARDS.md)**（分层/命名/错误码/数据建模/安全 总览）|
| 🏃 想直接部署运行 | [`docs/guide/GETTING_STARTED.md`](./docs/guide/GETTING_STARTED.md) |
| 🛠 想 Fork 二次开发 | [`docs/guide/USE_AS_SCAFFOLD.md`](./docs/guide/USE_AS_SCAFFOLD.md) |
| 📚 想读代码学架构 | [`docs/guide/ARCHITECTURE_TOUR.md`](./docs/guide/ARCHITECTURE_TOUR.md) + [`docs/PROJECT_OVERVIEW.md`](./docs/PROJECT_OVERVIEW.md) |
| 🤝 想贡献 | [`CONTRIBUTING.md`](./CONTRIBUTING.md) ・ 安全见 [`SECURITY.md`](./SECURITY.md) |
| 📋 看设计决策 | [`docs/specs/INDEX.md`](./docs/specs/INDEX.md)（各阶段 spec）・ [`CHANGELOG.md`](./CHANGELOG.md) |

## ➕ 添加业务模块

新业务域**必走** generator（确定性护栏：五层结构 + import-linter + schema-doc 自动注册，不要手抄）：

```bash
make new-module name=order                    # 最小（内存仓储桩）
make new-module name=product with-model=1     # 含 ORM model
```

生成器细节与五层蓝本 → [`docs/standards/CODE_GENERATOR.md`](./docs/standards/CODE_GENERATOR.md)。

## 🏗️ 技术栈

Python 3.14（uv 管理）・ FastAPI ・ SQLAlchemy 2.x async + asyncpg ・ Alembic ・ Redis（idempotency + cache）・ Argon2 + PyJWT ・ Ruff（format+lint）・ Pyright ・ Pytest ・ import-linter（分层契约）。

测试：`make check`（fast lane：unit + api，DB-free）/ `make test-integration`（需 docker compose 起 DB+Redis）/ `make coverage`（门槛 85%）。

## 🤝 贡献与许可

- 贡献流程、提交规范、分层红线 → [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- 安全漏洞报告 → [`SECURITY.md`](./SECURITY.md)
- **License**：[MIT](./LICENSE)。

---

> 方向变更（2026-06-05）：原 SaaS 多租户定位已废弃，回归单租户对标 RuoYi 本体，背景见 [`docs/architecture/MULTI_TENANCY.md`](./docs/architecture/MULTI_TENANCY.md)（废弃说明）。
