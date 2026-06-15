# 把 admin-platform 当脚手架用（Fork 二次开发）

> 受众：Fork 本仓做**自己的后台系统**的人。
>
> **一句话**：改包名/品牌/版本号 → 用 generator 长业务域 → 守住五层红线 → 代码改了同步改 docs。其余照搬本仓既有约定，别另起炉灶。

本仓本身派生自团队脚手架 `python-web-service-template`，技术栈已定型（FastAPI + uv + SQLAlchemy 2.x async + Alembic + Redis + Ruff + Pyright + Pytest）。Fork 后**不要重新评估选型**，直接在既有骨架上长业务。

---

## 1. 派生后改造清单

按顺序做完这几步，再开始写业务。

### 1.1 改包名 / 品牌

源码包在 `src/admin_platform/`，被 `pyproject.toml` 的两处引用：

- `[project].name`（分发名）
- `[tool.hatch.build.targets.wheel].packages = ["src/admin_platform"]`（构建目标）

包名还是**错误码前缀的来源**（generator 从 `[tool.hatch.build.targets.wheel].packages` 推断 service 前缀），所以改包名要一并搜索替换 `admin_platform` 的全部 import 路径。改完跑 [`make check`](../../Makefile) 验证 import 不断。

> 品牌/文案散落在 `README.md`、`docs/`、前端（若启用）等处；用全局搜索逐处替换，不要漏 `[tool.fastapi].entrypoint = "admin_platform.main:app"`。

### 1.2 改版本号 —— ⚠️ 有守门测试

应用版本以 `pyproject.toml [project].version` 为 single source of truth（本仓当前 `0.0.1`）。

**改 version 时必须同步这 3 处文档**，否则 [`tests/unit/test_version_consistency.py`](../../tests/unit/test_version_consistency.py) 会红：

| 守门文件 | 出处 |
|---|---|
| `README.md` | 仓库根 |
| `AGENTS.md` | 仓库根 |
| `docs/PROJECT_OVERVIEW.md` | 一页概览 |

该测试逐个断言「当前 version 字符串出现在文件中」，并校验 version 是合法 `X.Y.Z`。发版即同步，别留 drift。

---

## 2. 加业务域：必走 generator

**第一步永远是跑 generator，不要手抄已有 `domains/<existing>/`。**

```bash
make new-module name=order                   # 最小模块（内存仓储桩）
make new-module name=product with-model=1    # 含 ORM model + DB-backed repository
make new-module name=category plural=categories with-model=1   # 不规则复数
make new-module name=order dry-run=1         # 干跑，只打印将创建的文件清单
make new-module name=order force=1           # 覆盖已存在文件
```

CLI 参数：`name`（必填，snake_case 单数）/ `with-model=1`（加 `models.py` + DB repository）/ `plural=xxx`（URL/表名复数）/ `dry-run=1` / `force=1`。

### 它是「确定性护栏」，不是可选项

Generator 一次产出**直接通过 `make check`** 的最小桩模块：

- **自动生成五层结构**：`schemas.py` / `repository.py` / `service.py` / `api.py`（`--with-model` 再加 `models.py`），外加 `tests/unit/` 5 项 + `tests/api/` 4 项守门
- **自动纳入 import-linter 契约**（C1–C10，见 [`.importlinter`](../../.importlinter)）—— 跨层 import 会让 CI 红
- **schema-doc / 列注释自动注册**：`--with-model` 时自动 patch `migrations/env.py` 加 model import（漏加会让 `alembic check` 静默通过、autogenerate 出空 revision）

手抄已有 domain 会偏离命名、丢类型、漏 tests、漏契约登记。完整 CLI / 模板细节见 [CODE_GENERATOR.md](../standards/CODE_GENERATOR.md)。

### 生成后必做（generator 末尾会打印 Next steps）

1. **注册路由**到 `src/<package>/main.py` 的 `create_app()`
2. **（仅 `--with-model`）建迁移**：`uv run alembic revision --autogenerate -m 'add orders table'` → **人工 review** migration 文件 → `uv run alembic upgrade head`
3. **POST 端点默认带 `@idempotent`**：天然幂等的端点（如 content-addressed upload）才显式删除装饰器，并在 commit message 注明原因
4. 跑 `make check`（首次改 generator 模板时再跑 `make smoke-generator`）

---

## 3. 五层硬约束红线

违反层级边界是 hard rule，结构边界由 `make check` 的 import-linter 机检，语义边界由 code review 兜。完整职责表见 [LAYERED_DESIGN.md](../architecture/LAYERED_DESIGN.md)。

| 层 | 红线（**禁止**） |
|---|---|
| `api.py` | 写业务逻辑（if/else 业务分支）；直接 import `models.py` / `repository.py`（只能从 service 拿）；返回 ORM 对象 |
| `service.py` | 抛 `HTTPException`（用 `AppError`）；引入 `fastapi.Request` / `fastapi.Response`；写 SQL |
| `repository.py` | 抛业务异常（`HTTPException` / `AppError`）；只返 `None`/`False` 表示未找到，让 service 翻译 |
| `schemas.py` | 混入 SQLAlchemy session / 引用 `models.py`（纯 Pydantic） |
| `models.py` | 放序列化逻辑（`to_dict()` / `__json__()`，那是 schemas 的事） |

**异常约定**：业务异常一律 `AppError(code, title, *, detail=None, status_code=400, errors=None)`，错误码格式 `{service}.{ERROR_CODE}`。

碰基础设施（`src/<package>/{core,db,main.py}`）是另一类红线 —— 先停下来评估能不能在 domain 层解决。详见 [AI_CODING_RULES.md](../standards/AI_CODING_RULES.md) §4。

---

## 4. 改代码必须同步改 docs（drift 视为 bug）

代码与文档不一致是**未完成**，不是「待办」。常见同步对照：

| 改了什么代码 | 同步改 |
|---|---|
| `core/*.py` | `docs/architecture/<对应主题>.md` |
| `scripts/new_module.py` 模板 | `docs/standards/CODE_GENERATOR.md` |
| 加表 / 改列（`domains/*/models.py`） | 跑 `make schema-doc` 重生 `docs/architecture/DATA_MODEL.md`（生成物，勿手改） |
| 加新 Make target | `docs/PROJECT_OVERVIEW.md` 快速命令段 |

完整对照表与 AI 协作工作流见 [AI_CODING_RULES.md](../standards/AI_CODING_RULES.md) §8。

---

## 下一步

- 本地从 0 跑通 → [GETTING_STARTED.md](./GETTING_STARTED.md)
- 架构导览 → [ARCHITECTURE_TOUR.md](./ARCHITECTURE_TOUR.md)
- 规范总览 → [../STANDARDS.md](../STANDARDS.md)
- 贡献流程 → [../../CONTRIBUTING.md](../../CONTRIBUTING.md)
