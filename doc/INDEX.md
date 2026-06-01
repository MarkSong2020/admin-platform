# 知识库索引

> 团队 Python Web 服务脚手架模板的全部文档入口。**按角色找最快路径**——先看你是谁，再点链接。

## 🚀 5 分钟新手路径（先跑通，再看文档）

```bash
git clone <repo> && cd python-web-service-template
make init          # uv sync + pre-commit install
make compose-up    # 起本地 Postgres（端口 5432；Redis 是 opt-in，详见 compose.yaml）
make migrate       # 应用 Alembic 迁移（含 example domain 的 todos 表）
make dev           # 起 FastAPI dev server（端口 8000，hot reload）
```

打开 <http://localhost:8000/docs>，**四步验证模板真的能跑**（含 v0.5.1 多 domain 关联）：

1. **`GET /api/v1/todos`** → 返回空 pagination envelope `{items: [], page: 1, ..., tags: []}`
2. **`POST /api/v1/tags`** with `{"name": "urgent"}` → `201 Created` + `{id: 1, name: "urgent"}`
3. **`POST /api/v1/todos`** with `{"title": "buy milk", "tag_ids": [1]}` → `201 Created` + `{..., tags: [{id: 1, name: "urgent"}]}`（**演示多对多关联 + selectinload 预加载**）
4. 改一行 [`src/service_name/domains/todo/service.py`](../src/service_name/domains/todo/service.py)（例如把错误码改成 `TODO_GONE`），刷新浏览器看 hot reload 真生效

写第三个业务模块（5 分钟内）：

```bash
make new-module name=ledger with-model=1
```

对照 [`src/service_name/domains/todo/`](../src/service_name/domains/todo/) 写业务规则；蓝本里**每一行选择的理由**见 [`architecture/EXAMPLE_DOMAIN.md`](./architecture/EXAMPLE_DOMAIN.md)。

> 这条路径覆盖："从零到能看见返回值" + "理解我该照哪个模式写代码"。详细分流如下。

## 👋 新加入团队 / 第一次用本仓

1. 5 分钟了解仓库 → [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md)
2. 从 0 到本地能跑 → [operations/LOCAL_SETUP.md](./operations/LOCAL_SETUP.md)
3. 写第一个业务模块 → [standards/CODE_GENERATOR.md](./standards/CODE_GENERATOR.md)
4. 提 PR 前自检 → [standards/AI_CODING_RULES.md](./standards/AI_CODING_RULES.md)

## 🛠 业务开发者 / 加端点 / 改模型

- **教科书蓝本（必读）** → [architecture/EXAMPLE_DOMAIN.md](./architecture/EXAMPLE_DOMAIN.md)（`todo` 单 domain + `tag` 多对多 + N+1 守门）
- 命名约定（错误码 / operation_id / tag）→ [standards/NAMING_CONVENTIONS.md](./standards/NAMING_CONVENTIONS.md)
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
- 跨语言 ADR 正本 → `~/IdeaProjects/team-engineering-adr/0001-cross-language-conventions.md`（不在本仓，[stub](./reference/CROSS_LANGUAGE_ADR.md)）

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

参见 [archive/EVOLUTION.md](./archive/EVOLUTION.md) 了解本知识库是如何演进过来的（v0.1 散落 4 文件 → v0.4 仿 shopsell-server 7 目录）。
