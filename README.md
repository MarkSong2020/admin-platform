# admin-platform

> 多租户 admin 平台。FastAPI + uv + SQLAlchemy 2.x + Alembic + Redis + Ruff + Pytest。
> 派生自团队脚手架 `python-web-service-template`（lineage v0.5.3）。

**当前阶段：P0 多租户认证地基开发中**（应用版本 `v0.0.1`）。SaaS 共享库多租户，
fail-closed 隔离 + JWT 认证；后续长出 RBAC / 审计 / admin 业务域。

---

## 📖 完整文档

→ **[`doc/INDEX.md`](./doc/INDEX.md)** ← 按角色找最快路径（onboarding / 业务开发 / baseline 维护 / DevOps）

→ [`doc/PROJECT_OVERVIEW.md`](./doc/PROJECT_OVERVIEW.md) ← 5 分钟了解仓库（架构图 + 契约表）

→ [`CHANGELOG.md`](./CHANGELOG.md) ← 完整版本演进

## 🚀 快速开始

```bash
make init                       # uv sync --all-extras --dev
uv run pre-commit install       # 必须：装 git hook（漏装首次 commit 必被拦）
make check                      # ruff + pyright + pytest 全绿
make dev                        # http://127.0.0.1:8000/healthz
```

详细本地启动 + Docker → [`doc/operations/LOCAL_SETUP.md`](./doc/operations/LOCAL_SETUP.md)

## ➕ 添加业务模块

```bash
make new-module name=order                    # 最小（内存仓储桩）
make new-module name=product with-model=1     # 含 ORM model
```

蓝本对照 → [`doc/architecture/EXAMPLE_DOMAIN.md`](./doc/architecture/EXAMPLE_DOMAIN.md)；generator 细节 → [`doc/standards/CODE_GENERATOR.md`](./doc/standards/CODE_GENERATOR.md)

## 🎯 当前状态（v0.0.1 — P0 多租户认证地基）

- **Python 3.14**（`requires-python = ">=3.14"`）+ **测试**：`make check` 202 ✓（含租户隔离单测）/ `make coverage` 门槛 85%
- **P0 进度**：Task 1 scaffold ✓ / Task 2 argon2 密码哈希依赖 + access token TTL ✓ / Task 3 fail-closed 租户隔离（`session.info` + `do_orm_execute`/`before_flush`）✓；下一步 Task 4 数据模型（Tenant/User）+ 迁移
- **完整计划** → [`docs/specs/2026-06-02-p0-multitenant-auth-foundation.md`](./docs/specs/2026-06-02-p0-multitenant-auth-foundation.md)
- **脚手架 lineage**：派生自 `python-web-service-template` v0.5.3（example domain `todo`/`tag`、generator、CI 等模板资产暂保留，后续按需裁剪）→ [`CHANGELOG.md`](./CHANGELOG.md)

## 🌐 跨语言协同

跨语言 ADR（Java / Python 边界对齐）正本在团队级独立仓：

→ `team-engineering-adr/0001-cross-language-conventions.md`

本仓 stub：[`doc/reference/CROSS_LANGUAGE_ADR.md`](./doc/reference/CROSS_LANGUAGE_ADR.md)

## 📝 改了代码？同步改 doc

文档 drift 视为 bug。代码改 → 找对应 `doc/` 子目录同步改。详见 [`doc/standards/AI_CODING_RULES.md`](./doc/standards/AI_CODING_RULES.md)。

## 🔧 不在 MVP 范围

避免范围膨胀 — 前端 / SDK 自动生成 / Sentry / OTel collector / K8s manifests / Helm chart / 内部 RPC（gRPC / Thrift）/ 业务垂直域（compliance / channels / risk）都**不**做。

---

**License / 维护者 / 贡献指南** → 见团队 Wiki（不在本仓重复）。
