#!/usr/bin/env bash
# 无人值守 supervisor —— 在 p1-rbac 分支自动推进 P1 RBAC 的 auto 任务。
#
# 设计依据 doc/operations/UNATTENDED_EXECUTION.md（三层防御 + NIGHT_LOG + 可丢弃）。
# 安全实测（2026-06-05，claude 2.1.163）：
#   - --permission-mode default + --allowedTools 在 headless 下 fail-closed
#     （未授权工具进 permission_denials 被拒，子 agent 不绕过）；
#   - Edit/Write 路径 specifier 精确生效（Write(docs/**) 放行、core/ 被拒）；
#   - cwd 沙箱自动禁工作目录外操作。
#
# 职责分离：子 claude 只写码 + 自测（不碰 git）；supervisor 验证通过后统一 commit。
set -euo pipefail

REPO="/Users/songshanshan/PythonProjects/admin-platform"
HARNESS="$REPO/scripts/unattended"
QUEUE="$HARNESS/queue.json"
STATE_DIR="$HARNESS/state"
NIGHT_LOG="$REPO/NIGHT_LOG.md"
MAX_ATTEMPTS=2
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

cd "$REPO"
fatal() { echo "FATAL: $*" >&2; exit 1; }

# ── L3 物理隔离前置检查 ───────────────────────────────────────
BRANCH=$(git branch --show-current)
[ "$BRANCH" = "p1-rbac" ] || fatal "必须在 p1-rbac 分支跑（当前 ${BRANCH}）。无人值守不在 main 上工作。"
command -v jq >/dev/null || fatal "需要 jq 解析 queue.json"
[ -f "$QUEUE" ] || fatal "queue.json 不存在：$QUEUE"
mkdir -p "$STATE_DIR"

# ── allowedTools 白名单（物理禁改 core/db/main，禁 push/git，禁 rm）──
# 子 claude 只能：质量门 + 新增 domains/authz + 编辑 tests/docs + 读。
ALLOWED_ARR=(
  "Bash(make check)" "Bash(make coverage)" "Bash(make test-integration)"
  "Bash(make new-module:*)" "Bash(make migrate)" "Bash(make check-db)"
  "Bash(uv run pytest:*)" "Bash(uv run ruff:*)" "Bash(uv run pyright:*)"
  "Bash(uv run lint-imports:*)" "Bash(lint-imports:*)"
  "Edit(src/admin_platform/domains/**)" "Write(src/admin_platform/domains/**)"
  "Edit(src/admin_platform/authz/**)"   "Write(src/admin_platform/authz/**)"
  "Edit(tests/**)" "Write(tests/**)" "Edit(docs/**)" "Write(docs/**)"
  "Edit(.importlinter)"
  "Read" "Grep" "Glob"
)
# 故意不含：Edit/Write(core|db|main.py)、Bash(git *)、Bash(rm *)、外部写 MCP。
ALLOWED_CSV=$(IFS=,; echo "${ALLOWED_ARR[*]}")

log_night() { printf '%s\n' "$*" >> "$NIGHT_LOG"; }

# ── NIGHT_LOG 头（首次创建）──────────────────────────────────
if [ "$DRY_RUN" = 0 ] && [ ! -f "$NIGHT_LOG" ]; then
  cat > "$NIGHT_LOG" <<'EOF'
# NIGHT_LOG — P1 RBAC 无人值守

> 早上 review 重点看「⚠️ 安全项」与「⏸️ 升级」段。所有改动在 p1-rbac 分支、未 push、可丢弃。

## ⚠️ 需重点 review 的安全项
## ⏸️ 升级给你的决策（harness 没拍板）
## ✅ 已完成（附验证证据）
## ❌ 卡点（blocked）
## 📊 资源

EOF
fi

# ── 依赖检查：depends_on 里所有任务 status=done 才放行 ────────
deps_done() {
  local id="$1" pending
  pending=$(jq -r --arg id "$id" '
    (.tasks[]|select(.id==$id)|.depends_on // []) as $deps
    | [ .tasks[] | select(.id as $i | $deps|index($i)) | select(.status!="done") ] | length' "$QUEUE")
  [ "$pending" = "0" ]
}

set_status() {
  local id="$1" st="$2" tmp; tmp=$(mktemp)
  jq --arg id "$id" --arg st "$st" '(.tasks[]|select(.id==$id)|.status)=$st' "$QUEUE" > "$tmp" && mv "$tmp" "$QUEUE"
}

run_task() {
  local id="$1"
  local prompt_file="$HARNESS/tasks/${id}.md"
  [ -f "$prompt_file" ] || { log_night "❌ ${id}：缺 prompt 文件 ${prompt_file}，跳过"; return 1; }
  local verify; verify=$(jq -r --arg id "$id" '.tasks[]|select(.id==$id)|.verify // "make check"' "$QUEUE")

  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] ${id}：claude -p <$prompt_file> --permission-mode default"
    echo "[dry-run]   allowedTools=$ALLOWED_CSV"
    echo "[dry-run]   verify=$verify"
    return 0
  fi

  local attempt=1 out is_err denials
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    echo "▶ $id 尝试 $attempt/$MAX_ATTEMPTS"
    out=$(claude -p "$(cat "$prompt_file")" \
            --allowedTools "$ALLOWED_CSV" \
            --permission-mode default \
            --output-format json 2>"$STATE_DIR/${id}.stderr") || true
    echo "$out" > "$STATE_DIR/${id}.json"

    is_err=$(echo "$out" | jq -r '.is_error // true')
    denials=$(echo "$out" | jq -r '(.permission_denials // []) | length')
    [ "$denials" != "0" ] && log_night "⚠️ ${id}：发生 $denials 次工具权限拒绝（见 state/${id}.json —— 任务可能想碰 core/db/push，被挡）"

    # supervisor 独立验证门（不信子 claude 的自测，自己再跑一次）
    if [ "$is_err" = "false" ] && eval "$verify" >"$STATE_DIR/${id}.verify" 2>&1; then
      git add src/admin_platform/domains src/admin_platform/authz tests docs migrations 2>/dev/null || true
      if git diff --cached --quiet; then
        log_night "❌ ${id}：claude 报成功但无改动落地 → blocked"; return 1
      fi
      git commit -q -m "feat(p1): $id 无人值守自动提交

$(jq -r --arg id "$id" '.tasks[]|select(.id==$id)|.title' "$QUEUE")

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
      log_night "✅ $id | commit $(git rev-parse --short HEAD) | 验证 \`$verify\` 通过"
      return 0
    fi
    echo "  验证未过，attempt=$attempt"
    attempt=$((attempt+1))
  done
  log_night "❌ ${id}：$MAX_ATTEMPTS 次后仍未过 \`$verify\` → blocked（不阻塞队列）"
  return 1
}

# ── 主循环 ────────────────────────────────────────────────────
echo "supervisor 启动（dry-run=${DRY_RUN}，分支 ${BRANCH}）"

if [ "$DRY_RUN" = 1 ]; then
  echo "=== dry-run：列出会处理的 auto 任务（不执行、不改 queue 状态）==="
  for id in $(jq -r '.tasks[]|select(.auto==true and .status=="pending")|.id' "$QUEUE"); do
    if deps_done "$id"; then run_task "$id"
    else echo "[dry-run] ${id}：依赖未完成 → 实跑时会标 blocked-deps 跳过"; fi
  done
  echo "=== dry-run 结束（queue 未改动）==="
  exit 0
fi

while true; do
  next=$(jq -r '[ .tasks[] | select(.status=="pending" and .auto==true) ] | .[0].id // empty' "$QUEUE")
  [ -z "$next" ] && { echo "无 pending auto 任务，结束"; break; }
  if ! deps_done "$next"; then
    log_night "⏸️ ${next}：依赖未完成（多为 requires_human 的机制层 M1/M2）→ 跳过。需先人值守做机制层再续跑。"
    set_status "$next" "blocked-deps"; continue
  fi
  if run_task "$next"; then set_status "$next" "done"; else set_status "$next" "blocked"; fi
done

log_night ""
log_night "## 📊 资源（本次运行结束）"
log_night "- 完成 $(jq '[.tasks[]|select(.status=="done")]|length' "$QUEUE") / 总 $(jq '.tasks|length' "$QUEUE") 个任务"
echo "supervisor 结束。详见 $NIGHT_LOG"