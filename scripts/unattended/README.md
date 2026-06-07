# 无人值守 supervisor v2 — P1 RBAC

落地 [`doc/operations/UNATTENDED_EXECUTION.md`](../../doc/operations/UNATTENDED_EXECUTION.md)。在 **p1-rbac 分支**跑，产出可 review、可丢弃（未 push）。

**v2（2026-06-07）**：Codex 审查后按「git 管理为主」轻量重写。威胁模型校准 = 执行的是 **Claude 写的 RBAC 业务代码**（非不可信 agent），用 git 管理兜工作区污染，不上容器隔离、不过度工程。

## 快速开始

```bash
git switch p1-rbac
# 需要 DB 的任务（needs_db）前：起本地一次性库 + 指向它（测试环境，DDL 走 Alembic 可重建）
make compose-up
export APP_DATABASE_URL='postgresql+asyncpg://app:app@localhost:5432/admin_platform_test'
./scripts/unattended/supervisor.sh --dry-run   # 看会跑什么
./scripts/unattended/supervisor.sh             # 真跑
```

建议 `brew install coreutils` 启用 claude 超时保护（gtimeout）；没有则降级为无超时（告警）。

## Codex 8 issue → v2 修法

| issue | v2 修法 |
|---|---|
| 🔴 C1 沙箱逃逸 | **不上容器**。git 管理兜底：feature 分支 + clean tree 启动 + 精确 stage manifest + 你 review commit。威胁模型是「Claude 写代码」，逃逸风险低、工作区污染可还原 |
| 🔴 C2 eval 注入 | verify **枚举 case 分派固定 argv**（`check` / `check_db`），不 eval queue.json 字符串 |
| 🔴 C3 真库 DDL | **测试环境 + DDL 走 Alembic 版本化**（可 downgrade / compose 重建），不硬卡；仅启动打印 DB 目标供 review |
| 🔴 C4 dirty 污染 | 只 **精确 stage** 任务 manifest 声明的路径前缀；manifest 外改动不进 commit、留工作区待 review |
| 🟡 M1 改配置 | allowedTools 不放行 `.importlinter` / `pyproject` / `Makefile` / core / db（新域 importlinter 约束人值守补） |
| 🟡 M2 无超时 | gtimeout/timeout 包 claude（无则告警降级） |
| 🟡 M3 重复处理 | commit 后写 `state/<id>.done` receipt；重跑跳过 |

## queue.json 字段

- `verify`：`check`（`make check`）/ `check_db`（`make migrate + check-db + check + test-integration`）
- `manifest`：产出路径前缀数组，supervisor 只精确 stage 这些（C4）
- A1–M2 机制层已**人值守完成**（标 `done`）；D1–P1T 域 CRUD `pending`

## 下一步

D1（dept 域）的 `tasks/D1.md` **待写** —— 前置 **O1 dept 树存储须先拉 Codex PK + 人拍板**（不可逆 schema：邻接表 / 路径枚举 / 闭包表）。O1 定后写 D1 prompt，supervisor 即可跑 D1（make new-module + 树 CRUD + migration + integration，全在一次性 DB）。

## 安全模型小结

git 管理（feature 分支 + clean tree + 精确 stage + 你 review commit）兜工作区污染；测试环境 + Alembic 版本化兜 DB；allowedTools 物理禁 core/db/git/push/rm。对「Claude 写代码」场景足够 —— 不依赖 agent 善意的极端隔离（容器/临时用户）留作进阶，本项目阶段不需要。
