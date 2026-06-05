# 无人值守 supervisor — P1 RBAC

落地 [`doc/operations/UNATTENDED_EXECUTION.md`](../../doc/operations/UNATTENDED_EXECUTION.md) 的设计。在 **p1-rbac 分支**跑，产出可 review、可丢弃（未 push、未 merge）。

## 快速开始

```bash
cd /Users/songshanshan/PythonProjects/admin-platform
git switch p1-rbac
./scripts/unattended/supervisor.sh --dry-run   # 先看会跑哪些任务、用什么 allowedTools
./scripts/unattended/supervisor.sh             # 真跑
```

产物：`NIGHT_LOG.md`（早上 review，安全项顶到最前）、`scripts/unattended/state/*.json`（每任务 claude 原始输出 + permission_denials）。

## 安全边界（2026-06-05 实测确认，非假设）

| 机制 | 实现 | 实测结论 |
|---|---|---|
| 物理禁改 core/db/main | allowedTools 只放行 `Edit/Write(domains\|authz\|tests\|docs)` | `Write(core/**)` 进 permission_denials 被拒、文件不落地 ✅ |
| fail-closed | `--permission-mode default`（headless 无法交互确认 → 拒绝） | 未授权命令被拒、子 agent 不绕过 ✅ |
| 禁 push/git/rm | allowedTools 不含 `Bash(git *)` / `Bash(rm *)`；子 claude 不碰 git | supervisor 验证通过后**统一 commit** |
| cwd 沙箱 | Claude Code 内建 | `ls /tmp` 被拒（cwd 外）✅ |
| feature 分支 | supervisor 启动即检查 `git branch == p1-rbac` | 在 main 上直接 FATAL 退出 |

## 任务分类（`queue.json`）

- `auto:true` + 依赖全 `done` → supervisor 自动跑
- `requires_human` → 碰 **core 红线**的机制层（**M1** CurrentUser 扩展 / **M2** require_permission），**人值守做 + review**，harness 跳过
- 域任务（D1/R1/ME1/P1T）`depends_on` 机制层 → 机制层就绪前被标 `blocked-deps`

## 第一夜跑什么

`A1 → A2 → A3`：authz **纯逻辑层**（DataScope 类型 / apply_data_scope helper / Provider 接口 + stub + 单测），不碰 core、纯单测可验证。跑完后域任务因依赖 human 机制层被跳过，supervisor 停。

> **为什么机制层不无人跑**：M1/M2 改 `core/auth.py`（CLAUDE.md「碰基础设施红线先停下评估」）+ 权限安全语义（spec §5「副作用隔离不保证语义正确」）。这部分人做、harness 跑机制层之后的纯新增域 CRUD。

## 验证门

每任务 supervisor **独立**跑 `verify`（默认 `make check`），通过才 commit（不信子 claude 自测）。失败重试 2 次 → 标 `blocked`，不阻塞队列。

## 尚未实现（阶段 2，需要时再加）

- token 限流自恢复（检测 api_error_status → sleep 到 5h 窗口恢复 → 断点续跑）
- 一次性 DB 自动切换：域任务 `needs_db:true` 目前需**手工** `export APP_DATABASE_URL=<本地 throwaway compose>` 再跑；绝不连真库
- worktree 物理隔离（进阶：移除 worktree 的 push 凭证）