# python-web-service-template

> 团队 Python Web 服务脚手架。FastAPI + uv + SQLAlchemy 2.x + Alembic + Redis + Ruff + Pytest。

**新建后端 API / 微服务的默认起点**。从克隆到 `/healthz` 可访问 + 测试通过 ≤ 30 分钟。

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

## 🎯 当前状态（v0.5.3）

- **Python 3.14**（`requires-python = ">=3.14"`）+ **测试**：`make check` 189 ✓ / `make test-integration` 29 selected ✓ / `make coverage` 门槛 85%（`fail_under = 85`，实测 ~87.19%）
- **2 个 example domain**（v0.5.0 / v0.5.1）：`todo` 单 domain 蓝本 + `tag` 多对多关联 + N+1 守门
- **代码 docstring 一致简体中文**（v0.5.2 — 含 generator 模板 + core/db/health）
- **CI**：`.github/workflows/ci.yml` 是参考资产；真实 CI 平台由业务团队按 ADR 决议自选（[`doc/operations/CI_MIGRATION.md`](./doc/operations/CI_MIGRATION.md)）

详细历史（v0.1 → v0.5.3 全部 milestone）→ [`CHANGELOG.md`](./CHANGELOG.md) / [`doc/archive/EVOLUTION.md`](./doc/archive/EVOLUTION.md)

## 🌐 跨语言协同

跨语言 ADR（Java / Python 边界对齐）正本在团队级独立仓：

→ `~/IdeaProjects/team-engineering-adr/0001-cross-language-conventions.md`

本仓 stub：[`doc/reference/CROSS_LANGUAGE_ADR.md`](./doc/reference/CROSS_LANGUAGE_ADR.md)

## 📝 改了代码？同步改 doc

文档 drift 视为 bug。代码改 → 找对应 `doc/` 子目录同步改。详见 [`doc/standards/AI_CODING_RULES.md`](./doc/standards/AI_CODING_RULES.md)。

## 🔧 不在 MVP 范围

避免范围膨胀 — 前端 / SDK 自动生成 / Sentry / OTel collector / K8s manifests / Helm chart / 内部 RPC（gRPC / Thrift）/ 业务垂直域（compliance / channels / risk）都**不**做。

---

**License / 维护者 / 贡献指南** → 见团队 Wiki（不在本仓重复）。
