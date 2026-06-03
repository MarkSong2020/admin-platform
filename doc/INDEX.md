# 知识库索引

> admin-platform（多租户 admin 平台应用）的全部文档入口。**按角色找最快路径**——先看你是谁，再点链接。

## 🚀 5 分钟新手路径（先跑通，再看文档）

```bash
git clone <repo> && cd admin-platform
make init          # uv sync + pre-commit install
make compose-up    # 起本地 Postgres（端口 5432；Redis 是 opt-in，详见 compose.yaml）
make migrate       # 应用 Alembic 迁移（P0 基线；Task 4 后含 tenant/user 表）
make dev           # 起 FastAPI dev server（端口 8000，hot reload）
```

打开 <http://localhost:8000/docs>，**验证应用能跑**：

1. **`GET /healthz`** → `200`（进程存活）
2. **`GET /readyz`** → `200`（DB 可达；compose 起来后）
3. **`GET /docs`** → OpenAPI 文档（当前是 health + 错误响应契约；认证 / 业务端点随 Task 5+ 落地）

> P0 阶段（多租户认证地基）业务端点尚未落地；隔离机制见 [`../src/admin_platform/db/tenant_filter.py`](../src/admin_platform/db/tenant_filter.py)，完整计划见 [`../docs/specs/2026-06-02-p0-multitenant-auth-foundation.md`](../docs/specs/2026-06-02-p0-multitenant-auth-foundation.md)。

新建业务模块：

```bash
make new-module name=order with-model=1
```

generator 生成 schema → service → repository → api → models 五层骨架，即业务开发蓝本；细节见 [`standards/CODE_GENERATOR.md`](./standards/CODE_GENERATOR.md)。

> 这条路径覆盖："从零到能看见返回值" + "理解我该照哪个模式写代码"。详细分流如下。

## 👋 新加入团队 / 第一次用本仓

1. 5 分钟了解仓库 → [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md)
2. 从 0 到本地能跑 → [operations/LOCAL_SETUP.md](./operations/LOCAL_SETUP.md)
3. 写第一个业务模块 → [standards/CODE_GENERATOR.md](./standards/CODE_GENERATOR.md)
4. 提 PR 前自检 → [standards/AI_CODING_RULES.md](./standards/AI_CODING_RULES.md)

## 🛠 业务开发者 / 加端点 / 改模型

- **domain 五层骨架（必读）** → [standards/CODE_GENERATOR.md](./standards/CODE_GENERATOR.md)（`make new-module` 生成 schema → service → repository → api → models 五层，即业务开发蓝本）
- 命名约定（错误码 / operation_id / tag）→ [standards/NAMING_CONVENTIONS.md](./standards/NAMING_CONVENTIONS.md)
- 数据建模标准（多租户追加；基线见模板）→ [standards/DATA_MODELING.md](./standards/DATA_MODELING.md)
- 数据模型速览（表/列/约束，从 models 自动生成）→ [architecture/DATA_MODEL.md](./architecture/DATA_MODEL.md)（再生 `make schema-doc`）
- 错误响应 shape + AppError 用法 → [architecture/ERROR_RESPONSE.md](./architecture/ERROR_RESPONSE.md)
- 分页 / Idempotency / Auth → [architecture/REQUEST_LIFECYCLE.md](./architecture/REQUEST_LIFECYCLE.md)
- AI 协作规则（决策树 + 红线 + docstring 中文化规则）→ [standards/AI_CODING_RULES.md](./standards/AI_CODING_RULES.md)

## 🔧 Baseline 维护者 / 改 core / 升级依赖

- 5 层分层契约 → [architecture/LAYERED_DESIGN.md](./architecture/LAYERED_DESIGN.md)
- 请求生命周期 + middleware 链 → [architecture/REQUEST_LIFECYCLE.md](./architecture/REQUEST_LIFECYCLE.md)
- 可观测性（X-Request-ID / trace_id / log）→ [architecture/OBSERVABILITY.md](./architecture/OBSERVABILITY.md)
- 已知偏差（必读）→ [tech-debt/KNOWN_DEVIATIONS.md](./tech-debt/KNOWN_DEVIATIONS.md)
- 跨语言协同 ADR（本仓 stub，正本在团队仓）→ [reference/CROSS_LANGUAGE_ADR.md](./reference/CROSS_LANGUAGE_ADR.md)

## 🚀 DevOps / 部署 / 排障

- 本地启动 + Docker compose → [operations/LOCAL_SETUP.md](./operations/LOCAL_SETUP.md)
- 部署 + K8s probe 配置 → [operations/DEPLOYMENT.md](./operations/DEPLOYMENT.md)
- K8s 完整 manifest 模板 → [../examples/k8s/deployment.yaml](../examples/k8s/deployment.yaml)
- 依赖升级 playbook（CVE / 季度 minor / 年度 major）→ [operations/DEPENDENCY_UPGRADE.md](./operations/DEPENDENCY_UPGRADE.md)
- CI 平台说明（业务团队自选）→ [operations/CI_MIGRATION.md](./operations/CI_MIGRATION.md)
- 故障排查 runbook → [operations/RUNBOOK.md](./operations/RUNBOOK.md)

## 📚 历史 / 决策追溯

- 版本演进时间线 → [archive/EVOLUTION.md](./archive/EVOLUTION.md)
- 6 轮 review 发现汇总 → [archive/REVIEW_HISTORY.md](./archive/REVIEW_HISTORY.md)
- 跨语言 ADR 正本 → `team-engineering-adr/0001-cross-language-conventions.md`（不在本仓，[stub](./reference/CROSS_LANGUAGE_ADR.md)）

## 🌐 外部锚点

- 全局规范 → [reference/EXTERNAL_LINKS.md](./reference/EXTERNAL_LINKS.md)
- Glossary（术语表）→ [architecture/GLOSSARY.md](./architecture/GLOSSARY.md)

---

## 文档维护原则

本知识库按 **第一性原理** + **金字塔原理** 组织：

- **结论先行**：每篇文档第一段必须能独立回答"这是讲什么 / 为何要看"
- **按受众分类**，而非按文件类型（不是"所有 md 一锅"）
- **single source of truth**：跨语言约定在团队仓 ADR、不在本仓副本；Python 实现细节在本仓 architecture/、不在 ADR
- **drift 是 bug**：文档与代码不一致比缺文档更糟。修代码时**同步**改对应 doc，否则视为未完成
- 改 doc 结构（增减目录 / 改 INDEX 分支）必须同步改本文件

参见 [archive/EVOLUTION.md](./archive/EVOLUTION.md) 了解本知识库是如何演进过来的（v0.1 散落 4 文件 → v0.4 仿 java-reference-service 7 目录）。
