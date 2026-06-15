# 无人值守 / 异步执行的副作用隔离

> **结论先行**：无人值守 ≠ 放弃决策。它是「你不在电脑旁（睡觉 / 离开）时让 Claude 继续干活，你回来一定 review」的**异步执行**模式。决策权和验收权都在你手里。
>
> 因此真正要防的不是「agent 拍错板」（你 review 能拦），而是 **「在你 review 之前就已经不可逆的副作用」**——这类 review 拦不住。本文定义如何把这类副作用隔离掉，让**夜里产出的一切都停留在「可 review、可丢弃」的状态**。

---

## 1. 核心原则

> **可逆的随便做，不可逆的挡死，安全语义靠测试 + 你 review。**

| 能等你 review 再说（夜里随便做） | review 前就不可逆（必须挡死） |
|---|---|
| 写代码、改文件、写测试 | `git push`（推远程 / 触发别人的 CI） |
| commit 到 **feature 分支** | `git push --force`、`git reset --hard` |
| 起草 RBAC / ADR 方案 | 删文件（`rm -rf` / `rm -r`） |
| `make check` / `make coverage` | migration apply 到**真库 / 共享库** |
| migration apply 到**本地一次性库** | 调外部写 API、推镜像、发消息 |

---

## 2. 三层防御

防线从「主」到「兜底」排列。**不要只依赖 L1**——黑名单可被绕过（见 §5 诚实边界）。

### L1 — 团队权限基线（`.claude/settings.json`，进版本库）

- `allow`：自动放行的安全操作（`make check`/`coverage`/`test`、`pytest`、`ruff`、`pyright`、`git add src|tests|doc`、`git commit`、`git switch -c`…）——顺带减少日常交互弹框。
- `deny`：绝对红线（`git push --force`、`git add -A`、`git reset --hard`、`git clean -f`、`git stash drop/clear`、`rm -rf`/`rm -r`、`docker push`）——交互开发也不该做。
- ⚠️ **普通 `git push` 故意不在 deny 里**：交互开发要用。无人值守不 push 靠 L2 + L3，不靠这里。

### L2 — 无人值守 supervisor 的严格 allowlist（**主防线**）

无人值守用 headless（`claude -p`）启动，**只放行白名单**，未列入的（push / migration-真库 / 外部写 / 写 MCP）**自动拒绝**。这比 L1 黑名单可靠——**枚举「安全」比枚举「所有危险」可控得多**。

```bash
# supervisor 片段（headless 启动范式）
claude -p "$(cat tasks/next.md)" \
  --allowedTools "\
Bash(make check),Bash(make coverage),Bash(uv run pytest:*),\
Bash(uv run ruff:*),Bash(uv run pyright),Bash(uv run lint-imports),\
Edit(src/**),Edit(tests/**),Edit(docs/**),\
Bash(git switch -c:*),Bash(git add src/*),Bash(git add tests/*),Bash(git commit:*)" \
  --output-format json
```

> **permission-mode 取值待用 `claude doctor` / 官方文档核对后填入**（[permission-modes.md](https://code.claude.com/docs/en/permission-modes.md)）。已确认机制：headless `-p` 下无交互终端，未授权工具拿不到确认 → **直接拒绝、不卡住**；`--allowedTools` 精确放行白名单。**不要用 `--dangerously-skip-permissions`**——它跳过包括 deny 在内的所有层。

### L3 — 物理隔离（兜底，挡间接绕过）

L1/L2 都是命令层，挡不住「脚本内部 subprocess 调 git push」这类间接调用。物理隔离从环境上让不可逆操作**没有通道**：

- **无 push 通道**：在 feature 分支工作；进阶——用专门的 git worktree 跑，移除该 worktree 的 remote 或不提供 push 凭证。即使 agent 绕过命令层跑了 push，没凭证也推不出去。
- **一次性 DB**：supervisor 启动前把 `APP_DATABASE_URL` 指向本地 docker compose 的 throwaway Postgres。migration apply 到它验证，错了 `make compose-down && make compose-up && make migrate` 重置。**绝不连真库 / 共享库**。
- **可丢弃**：所有改动在 feature 分支，没 push 没 merge。你 review 后决定 merge 或 `git branch -D` 丢弃。

---

## 3. 交付物：NIGHT_LOG.md（为 review 优化）

夜里产出越多，你早上 review 越累、越容易漏。NIGHT_LOG 把「你必须重点看的」顶到最前：

```markdown
# NIGHT_LOG — <日期>

## ⚠️ 需你重点 review 的安全项（最高优先级）
- <涉及 auth / RBAC / 权限 / 数据访问的改动，逐条列 file:line>
- <我不确定的判断 + 为什么不确定>
- <我没覆盖的攻击面：哪些越权 / 边界 case 没写负例测试>

## ⏸️ 升级给你的红线决策（我没拍板，等你定）
- <决策点 + 候选方案对比 + 我的倾向>

## ✅ 已完成（每条附验证证据）
- <任务> | commit <hash> | 证据：`make check` 通过 / `make coverage` 88.x% / 新增测试名

## ❌ 卡点（blocked）
- <任务> | 尝试 N 次失败 | 原因 | 已跳过，未阻塞队列

## 资源
- token 用量 / 运行时长 / 撞限流次数
```

---

## 4. token 耗尽 / 异常的自恢复

- **token（Max 5h 窗口）耗尽**：supervisor 检测限流退出码 → sleep 到窗口恢复 → 从断点续跑。断点靠 `tasks.yaml`（队列状态）+ `NIGHT_LOG.md` + 每任务一 commit（checkpoint），不靠 session 内存。
- **异常**：每任务尝试上限（超过标 `blocked` 跳过，不拖垮队列）+ 单命令超时 kill（防死循环）+ 原子 checkpoint（每完成才 commit）。

---

## 5. 诚实边界（别给自己虚假安全感）

- **L1/L2 命令层挡不住**：shell 变量（`U=origin && git push $U`）、别名、Python/脚本内部 subprocess、字符串拼接命令。→ 这就是 **L3 物理隔离**存在的理由：让不可逆操作在环境上没有通道。
- **副作用隔离不保证语义正确**：settings / 隔离管的是「会不会做不可逆的事」，管不了「权限逻辑对不对、有没有越权路径」。后者全绿 ≠ 正确（`make check` / coverage 是机械/结构验证，与安全语义正交）。→ 靠**负向测试**（401/403/默认 deny/越权拒绝）兜一层 + 你 review，见 [AI_CODING_RULES.md](../standards/AI_CODING_RULES.md) §7 与 coverage gate 的盲区说明（[CI_MIGRATION.md](./CI_MIGRATION.md) fast lane 第 7 步）。
- **coverage 的盲区**：total coverage 会被高覆盖模块掩盖低覆盖的 repository / auth service，只防整体退化，不证明安全路径已测。

---

## 6. 验证

改动 `.claude/settings.json` 后：

```bash
claude doctor                              # 健康检查：settings.json 是否被正确加载
python3 -c "import json; json.load(open('.claude/settings.json')); print('JSON OK')"
```

实测几条规则确认行为（不要假设 glob 生效）：被 deny 的命令应被拒、allow 的应放行、未列入的在 headless 下应直接拒绝。
