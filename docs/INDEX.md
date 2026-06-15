# 知识库索引

> admin-platform（单租户后台管理脚手架，对标 RuoYi）的全部文档入口。**先按主题**（技术栈 / 设计规范 / 约束边界 / 怎么用）找正本，**再按角色**找最快路径。

## 🚀 5 分钟新手路径（先跑通，再看文档）

```bash
git clone https://github.com/MarkSong2020/admin-platform.git && cd admin-platform
make init          # uv sync + pre-commit install
make compose-up    # 起本地 Postgres（端口 5432；Redis 是 opt-in，详见 compose.yaml）
make migrate       # 应用 Alembic 迁移（当前 head 0020；0013–0020 仅本地 dev + CI 跑过，生产迁移 gated）
make dev           # 起 FastAPI dev server（端口 8000，hot reload）
```

打开 <http://localhost:8000/docs>，**验证应用能跑**：

1. **`GET /healthz`** → `200`（进程存活）
2. **`GET /readyz`** → `200`（DB 可达；compose 起来后）
3. **`GET /docs`** → OpenAPI 文档（health + 错误响应契约 + 认证 / RBAC / 审计 / 字典·参数·通知 / 监控·定时任务等已落地端点）

> 当前 **P0–P6 全部落地**（认证 / RBAC / 审计 / 字典·参数·通知 / 监控·在线用户·定时任务 / 文件·Excel / Vue 前端，单租户对标 RuoYi）。各阶段设计决策与对标路线图见 [设计决策溯源](./archive/specs/INDEX.md)。

新建业务模块：

```bash
make new-module name=order with-model=1
```

generator 生成 schema → service → repository → api → models 五层骨架，即业务开发蓝本；细节见 [`standards/CODE_GENERATOR.md`](./standards/CODE_GENERATOR.md)。

> 这条路径覆盖："从零到能看见返回值" + "理解我该照哪个模式写代码"。

## 🧭 按主题找正本（重点）

| 主题 | 正本入口 |
|---|---|
| 🧱 **技术栈与架构** | [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md)（一页概览）・[guide/ARCHITECTURE_TOUR.md](./guide/ARCHITECTURE_TOUR.md)（架构导览）・[../README.md](../README.md)（能力矩阵 + 技术栈） |
| 📐 **设计规范** | [STANDARDS.md](./STANDARDS.md)（总入口）→ 分层 [architecture/LAYERED_DESIGN.md](./architecture/LAYERED_DESIGN.md)・命名 [standards/NAMING_CONVENTIONS.md](./standards/NAMING_CONVENTIONS.md)・错误码 [architecture/ERROR_RESPONSE.md](./architecture/ERROR_RESPONSE.md)・数据建模 [standards/DATA_MODELING.md](./standards/DATA_MODELING.md) |
| 🚧 **约束与边界** | [STANDARDS.md](./STANDARDS.md) 安全基线段・[standards/AI_CODING_RULES.md](./standards/AI_CODING_RULES.md)（红线 + 决策树）・[tech-debt/KNOWN_DEVIATIONS.md](./tech-debt/KNOWN_DEVIATIONS.md)（已知偏差） |
| 📖 **怎么使用** | 部署运行 [guide/GETTING_STARTED.md](./guide/GETTING_STARTED.md)・Fork 二开 [guide/USE_AS_SCAFFOLD.md](./guide/USE_AS_SCAFFOLD.md)・贡献 [../CONTRIBUTING.md](../CONTRIBUTING.md) |

> 以上是**重点正本**。下面按角色给更细的分流路径；各阶段实现过程的设计 spec 已归档到 [archive/specs/](./archive/specs/INDEX.md)（溯源用）。

## 🌍 开源使用者 / 把它当脚手架

- 📐 **先搞清标准与原则** → [STANDARDS.md](./STANDARDS.md)（分层 / 命名 / 错误码 / 数据建模 / 安全 总览）
- 🏃 直接部署运行 → [guide/GETTING_STARTED.md](./guide/GETTING_STARTED.md)
- 🛠 Fork 二次开发 → [guide/USE_AS_SCAFFOLD.md](./guide/USE_AS_SCAFFOLD.md)
- 📚 读代码学架构 → [guide/ARCHITECTURE_TOUR.md](./guide/ARCHITECTURE_TOUR.md)
- 🤝 贡献流程 → [../CONTRIBUTING.md](../CONTRIBUTING.md) ・ 安全报告 → [../SECURITY.md](../SECURITY.md)

## 👋 新加入团队 / 第一次用本仓

1. 5 分钟了解仓库 → [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md)
2. 从 0 到本地能跑 → [operations/LOCAL_SETUP.md](./operations/LOCAL_SETUP.md)
3. 写第一个业务模块 → [standards/CODE_GENERATOR.md](./standards/CODE_GENERATOR.md)
4. 提 PR 前自检 → [standards/AI_CODING_RULES.md](./standards/AI_CODING_RULES.md)

## 🛠 业务开发者 / 加端点 / 改模型

- **domain 五层骨架（必读）** → [standards/CODE_GENERATOR.md](./standards/CODE_GENERATOR.md)（`make new-module` 生成 schema → service → repository → api → models 五层，即业务开发蓝本）
- 命名约定（错误码 / operation_id / tag）→ [standards/NAMING_CONVENTIONS.md](./standards/NAMING_CONVENTIONS.md)
- 数据建模标准（单租户，沿用模板基线）→ [standards/DATA_MODELING.md](./standards/DATA_MODELING.md)
- 数据模型速览（表/列/约束，从 models 自动生成）→ [architecture/DATA_MODEL.md](./architecture/DATA_MODEL.md)（再生 `make schema-doc`）
- 错误响应 shape + AppError 用法 → [architecture/ERROR_RESPONSE.md](./architecture/ERROR_RESPONSE.md)
- 分页 / Idempotency / Auth → [architecture/REQUEST_LIFECYCLE.md](./architecture/REQUEST_LIFECYCLE.md)
- ~~多租户隔离机制~~ **已废弃**（2026-06-05 单租户回归）→ [architecture/MULTI_TENANCY.md](./architecture/MULTI_TENANCY.md)（历史留痕，不再是现行机制；单租户数据权限走 P1 RBAC 的 dept）
- AI 协作规则（决策树 + 红线 + docstring 中文化规则）→ [standards/AI_CODING_RULES.md](./standards/AI_CODING_RULES.md)

## 🔧 Baseline 维护者 / 改 core / 升级依赖

- 5 层分层契约 → [architecture/LAYERED_DESIGN.md](./architecture/LAYERED_DESIGN.md)
- 请求生命周期 + middleware 链 → [architecture/REQUEST_LIFECYCLE.md](./architecture/REQUEST_LIFECYCLE.md)
- 可观测性（X-Request-ID / trace_id / log）→ [architecture/OBSERVABILITY.md](./architecture/OBSERVABILITY.md)
- 已知偏差（必读）→ [tech-debt/KNOWN_DEVIATIONS.md](./tech-debt/KNOWN_DEVIATIONS.md)
- 跨语言协同契约（错误码 / 链路 / 分页 / 幂等的 HTTP 边界约定）→ [reference/CROSS_LANGUAGE_ADR.md](./reference/CROSS_LANGUAGE_ADR.md)

## 🚀 DevOps / 部署 / 排障

- 本地启动 + Docker compose → [operations/LOCAL_SETUP.md](./operations/LOCAL_SETUP.md)
- 部署 + K8s probe 配置 → [operations/DEPLOYMENT.md](./operations/DEPLOYMENT.md)
- K8s 完整 manifest 模板 → [../examples/k8s/deployment.yaml](../examples/k8s/deployment.yaml)
- 依赖升级 playbook（CVE / 季度 minor / 年度 major）→ [operations/DEPENDENCY_UPGRADE.md](./operations/DEPENDENCY_UPGRADE.md)
- CI 平台说明（业务团队自选）→ [operations/CI_MIGRATION.md](./operations/CI_MIGRATION.md)
- 无人值守 / 异步执行的副作用隔离 → [operations/UNATTENDED_EXECUTION.md](./operations/UNATTENDED_EXECUTION.md)
- 故障排查 runbook → [operations/RUNBOOK.md](./operations/RUNBOOK.md)

## 📚 历史 / 决策追溯

- 版本演进时间线 → [archive/EVOLUTION.md](./archive/EVOLUTION.md)
- 6 轮 review 发现汇总 → [archive/REVIEW_HISTORY.md](./archive/REVIEW_HISTORY.md)
- 各阶段设计决策（spec 导航）→ [archive/specs/INDEX.md](./archive/specs/INDEX.md)
- 跨语言协同契约速查 → [reference/CROSS_LANGUAGE_ADR.md](./reference/CROSS_LANGUAGE_ADR.md)

## 🌐 外部锚点

- 全局规范 → [reference/EXTERNAL_LINKS.md](./reference/EXTERNAL_LINKS.md)
- Glossary（术语表）→ [architecture/GLOSSARY.md](./architecture/GLOSSARY.md)

---

## 文档维护原则

本知识库按 **第一性原理** + **金字塔原理** 组织：

- **结论先行**：每篇文档第一段必须能独立回答"这是讲什么 / 为何要看"
- **按受众分类**，而非按文件类型（不是"所有 md 一锅"）
- **single source of truth**：跨语言协同契约速查在 reference/CROSS_LANGUAGE_ADR.md，Python 实现细节在 architecture/，两者不重复
- **drift 是 bug**：文档与代码不一致比缺文档更糟。修代码时**同步**改对应 doc，否则视为未完成
- 改 doc 结构（增减目录 / 改 INDEX 分支）必须同步改本文件

参见 [archive/EVOLUTION.md](./archive/EVOLUTION.md) 了解本知识库是如何演进过来的（v0.1 散落 4 文件 → v0.4 成熟后端项目式 7 目录）。
