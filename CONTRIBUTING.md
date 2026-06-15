# 贡献指南

> 一句话：装好环境 → 改代码守住五层红线 → 提交前 `make check` 全绿 → 同步改 docs → 按 Conventional Commits 开 PR。

技术栈已定型（FastAPI + uv + SQLAlchemy 2.x async + Alembic + Redis + Ruff + Pyright + Pytest），**不要重新评估选型**。AI agent 在本仓做开发的完整工作流约束见 [docs/standards/AI_CODING_RULES.md](docs/standards/AI_CODING_RULES.md)。

---

## 1. 开发环境

```bash
make init                  # uv sync --all-extras --dev（装 baseline + dev 依赖）
uv run pre-commit install  # ⚠️ 必须：装 git hook，漏装首次 commit 会被 ruff-format 改文件而失败
```

`pre-commit` 已在 dev deps 里（`make init` 会装），但 `.pre-commit-config.yaml` 描述的 git hook 必须显式 `install` 才生效。

从 0 跑通的完整步骤见 [docs/guide/GETTING_STARTED.md](docs/guide/GETTING_STARTED.md)。

---

## 2. 提交前门禁：`make check` 必须全绿

`make check` 是 CI fast lane 的镜像，按顺序跑以下 6 步，**任一红都不能提交**：

| 步骤 | 命令 | 把关什么 |
|---|---|---|
| 1 | `ruff format --check .` | 格式（不改文件，只检查） |
| 2 | `ruff check .` | lint（含安全规则 S/bandit、async 阻塞 I/O、禁 `print`） |
| 3 | `pyright` | 静态类型 |
| 4 | `pytest -m "not integration"` | unit + api 测试（排除集成） |
| 5 | `lint-imports` | import-linter 分层契约 C1–C10（见 [`.importlinter`](.importlinter)） |
| 6 | `python scripts/dump_schema.py --check` | ORM model 与 `docs/architecture/DATA_MODEL.md` 无漂移 |

改了 DB / migration / models 时还要补集成验证：

```bash
make compose-up && make migrate && make test-integration && make check-db
make coverage   # 覆盖率门槛 85%（CI 强制，提交前先自己过）
```

**不要** `--no-verify` skip pre-commit hook，**不要**静默忽略 ruff / pyright 报错（要么修，要么在 PR 描述写明原因）。声称「测试通过」前自己跑过。

---

## 3. 提交规范

本仓用 **Conventional Commits**（看 `git log --oneline` 即是此风格）：`type(scope): 描述`。

- 常见 type：`feat` / `fix` / `chore` / `docs` / `test` / `ci`
- scope 可选，标模块或层（如 `feat(auth):`、`fix(security):`、`chore(frontend):`）
- 描述用简体中文（code identifier / 错误码 / 框架名保留英文）
- **第一行长度**：英文 ≤ 72 字符，中文 ≤ 36 字

实际风格示例（取自历史提交）：

```
feat(auth): 用户自助改密 POST /auth/change-password
fix(security): 收紧 RBAC 授权根字段写权限 + provider 快照一致性
chore(frontend): 同步 openapi 快照与生成类型（backend hardening schema 变更）
ci: fast lane 跳过前端 lint/commitlint hook（无 pnpm 致 exit 127）
```

---

## 4. PR 流程

1. 从最新 main 切分支（`feat/...` / `fix/...`），**不直接推 main**
2. 本地 `make check` 全绿；动了 DB/Dockerfile/CI 的按 §2 补对应验证
3. 同步改 docs（见 §6）
4. 开 PR：描述说清**做了什么 + 为什么**；动了构建/发布层（`Makefile` / `pyproject.toml` / `Dockerfile` / CI）要显式说明改了哪条已固化决策（7 条 Errata，见 [docs/standards/AI_CODING_RULES.md](docs/standards/AI_CODING_RULES.md) §5）
5. CI 必须绿才能合

---

## 5. 分层红线速查

违反层级边界是 hard rule。结构边界由 `make check` 的 import-linter 机检，语义边界由 code review 兜。完整职责表见 [docs/architecture/LAYERED_DESIGN.md](docs/architecture/LAYERED_DESIGN.md)。

| 层 | 禁止 |
|---|---|
| `api.py` | 写业务逻辑；直接 import `models.py` / `repository.py`；返回 ORM 对象 |
| `service.py` | 抛 `HTTPException`（用 `AppError`）；引入 `fastapi.Request` / `Response`；写 SQL |
| `repository.py` | 抛业务异常（只返 `None`/`False`，让 service 翻译） |
| `schemas.py` | 混入 SQLAlchemy session / 引用 `models.py` |
| `models.py` | 放序列化逻辑（`to_dict()` / `__json__()`） |

新增业务域**必走** `make new-module name=xxx [with-model=1]`，不要手抄已有 domain。

---

## 6. 约定

- **AI 指引唯一正本是 `AGENTS.md`**：`CLAUDE.md` 通过 `@AGENTS.md` 导入其全文，改工作约定只改 `AGENTS.md` 一处（Codex / Cursor / Claude Code 等读到同一份，无需手工同步两份）。
- **文档 drift 视为 bug**：代码改动必须同步改对应 `docs/`，不一致即未完成。同步对照表见 [docs/standards/AI_CODING_RULES.md](docs/standards/AI_CODING_RULES.md) §8。
- **版本号守门**：改 `pyproject.toml [project].version` 要同步 `README.md` / `AGENTS.md` / `docs/PROJECT_OVERVIEW.md`，否则 `tests/unit/test_version_consistency.py` 会红。

---

## 许可

贡献即表示同意你的代码以本仓 [MIT License](LICENSE) 发布。
