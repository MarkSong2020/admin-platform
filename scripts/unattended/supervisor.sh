#!/usr/bin/env bash
# 无人值守 supervisor v2 —— Codex 审查后按「git 管理为主」轻量重写。
#
# 威胁模型校准（与用户对齐 2026-06-07）：执行的是 Claude 写的 RBAC 业务代码（非不可信
# agent），沙箱逃逸实际风险低；用 git 管理兜住工作区污染，不上容器隔离。修复要点：
#   C1/C4 工作区污染 → clean tree 启动 + 只精确 stage 任务 manifest 声明的路径
#                      （manifest 外改动不进 commit）+ 你 review NIGHT_LOG/commit 兜底
#   C3 真库 DDL      → 本项目是测试环境 + DDL 走 Alembic 版本化（可 downgrade / compose 重建），
#                      不硬卡（与用户对齐 2026-06-07：测试库不怕重建）；仅启动打印 DB 目标供 review
#   C2 eval 注入     → verify 枚举 case 分派固定 argv（不 eval queue.json 字符串）
#   M1 改验证配置    → allowedTools 不放行 .importlinter / pyproject / Makefile / core / db
#   M2 无超时        → gtimeout/timeout 包 claude（无则告警降级）
#   M3 重复处理      → commit 后写 state/<id>.done receipt；重跑跳过
set -euo pipefail

REPO="/Users/songshanshan/PythonProjects/admin-platform"
HARNESS="$REPO/scripts/unattended"
QUEUE="$HARNESS/queue.json"
STATE_DIR="$HARNESS/state"
NIGHT_LOG="$REPO/NIGHT_LOG.md"
MAX_ATTEMPTS=2
CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-900}"   # 单次 claude 超时（秒）
DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

cd "$REPO"
fatal() { echo "FATAL: $*" >&2; exit 1; }

# ── 前置检查 ──────────────────────────────────────────────────
BRANCH=$(git branch --show-current)
[ "$BRANCH" = "p1-rbac" ] || fatal "必须在 p1-rbac 分支跑（当前 ${BRANCH}）。"
command -v jq >/dev/null || fatal "需要 jq 解析 queue.json"
[ -f "$QUEUE" ] || fatal "queue.json 不存在：$QUEUE"
mkdir -p "$STATE_DIR"

# C4：启动要求「代码区」clean（任务只碰 src/tests/migrations）。doc/.github/.claude 等
# 会话前的非代码 dirty 不拦——manifest 精确 stage 不会提交它们，精确 stage 才是 C4 主防御。
if [ "$DRY_RUN" = 0 ]; then
  DIRTY=$(git status --porcelain -- src tests migrations | grep -vE 'scripts/unattended/' || true)
  [ -n "$DIRTY" ] && fatal "代码区(src/tests/migrations)不 clean（C4），先提交/stash 再跑：
$DIRTY"
fi

# M2：超时包装器（优先 gtimeout，brew coreutils）
TIMEOUT_BIN=""
for c in gtimeout timeout; do command -v "$c" >/dev/null && { TIMEOUT_BIN="$c"; break; }; done
[ -z "$TIMEOUT_BIN" ] && echo "⚠️ 未找到 gtimeout/timeout，claude 无超时保护（建议 brew install coreutils）" >&2

# allowedTools（M1：不放行改验证配置 / core / db / git / rm / docker）
ALLOWED_ARR=(
  "Bash(make check)" "Bash(make check-db)" "Bash(make migrate)" "Bash(make test-integration)"
  "Bash(make new-module:*)" "Bash(uv run alembic:*)"
  "Bash(uv run pytest:*)" "Bash(uv run ruff:*)" "Bash(uv run pyright:*)" "Bash(uv run lint-imports:*)"
  "Edit(src/admin_platform/domains/**)" "Write(src/admin_platform/domains/**)"
  "Edit(src/admin_platform/authz/**)"   "Write(src/admin_platform/authz/**)"
  "Edit(migrations/versions/**)" "Write(migrations/versions/**)"
  "Edit(tests/**)" "Write(tests/**)"
  "Read" "Grep" "Glob"
)
# 故意不含（M1 + 既有）：Edit(.importlinter|pyproject.toml|Makefile)、Edit/Write(core|db|main.py)、
#   Bash(git *)、Bash(rm *)、Bash(docker *)。新域的 .importlinter 约束由人值守补。
ALLOWED_CSV=$(IFS=,; echo "${ALLOWED_ARR[*]}")

log_night() { printf '%s\n' "$*" >> "$NIGHT_LOG"; }

# ── DB 目标（信息性）：测试环境 + DDL 走 Alembic 版本化（可 downgrade / compose 重建），
#    不硬卡。仅启动时打印跑在哪个库，便于 review（与用户对齐 2026-06-07）。──
db_target() {
  python3 - "${APP_DATABASE_URL:-}" <<'PY'
import sys, urllib.parse as u
p = u.urlparse(sys.argv[1] or "")
print(f"{p.hostname or '(unset)'}/{(p.path or '').lstrip('/') or '(none)'}")
PY
}

# ── C2：verify 枚举（固定 argv，不 eval queue.json 字符串）──
run_verify() {
  case "$1" in
    check)
      make check ;;
    check_db)
      make migrate && make check-db && make check && make test-integration ;;
    *)
      echo "未知 verify 类型: $1（仅允许 check / check_db）" >&2; return 2 ;;
  esac
}

# ── NIGHT_LOG 头 ──────────────────────────────────────────────
if [ "$DRY_RUN" = 0 ] && [ ! -f "$NIGHT_LOG" ]; then
  cat > "$NIGHT_LOG" <<'EOF'
# NIGHT_LOG — P1 RBAC 无人值守

> 早上 review 重点看「⚠️ 安全项」「⏸️ 升级」。改动在 p1-rbac 分支、未 push、可丢弃。
> 安全模型：git 管理兜底（clean tree + manifest 精确提交 + 你 review）+ 一次性 DB 校验。

## ⚠️ 需重点 review 的安全项
## ⏸️ 升级给你的决策
## ✅ 已完成（附验证证据）
## ❌ 卡点（blocked）
## 📊 资源

EOF
fi

deps_done() {
  local id="$1" pending
  pending=$(jq -r --arg id "$id" '
    (.tasks[]|select(.id==$id)|.depends_on // []) as $deps
    | [ .tasks[] | select(.id as $i | $deps|index($i)) | select(.status!="done") ] | length' "$QUEUE")
  [ "$pending" = "0" ]
}

set_status() {
  local id="$1" st="$2" tmp; tmp=$(mktemp "$STATE_DIR/queue.XXXXXX")
  jq --arg id "$id" --arg st "$st" '(.tasks[]|select(.id==$id)|.status)=$st' "$QUEUE" > "$tmp" && mv "$tmp" "$QUEUE"
}

# C4：列出工作区中落在 manifest 路径前缀外的改动（manifest = 空格分隔的路径前缀）
stray_changes() {
  local manifest="$1" f p in_manifest
  for f in $(git status --porcelain | grep -vE 'scripts/unattended/|NIGHT_LOG\.md' | awk '{print $NF}'); do
    in_manifest=0
    for p in $manifest; do case "$f" in "$p"*) in_manifest=1; break;; esac; done
    [ "$in_manifest" = 0 ] && echo "$f"
  done
}

run_task() {
  local id="$1"
  local prompt_file="$HARNESS/tasks/${id}.md"
  if [ ! -f "$prompt_file" ]; then
    [ "$DRY_RUN" = 1 ] && { echo "[dry-run] ${id}: ⚠️ 缺 prompt 文件（待写）"; return 0; }
    log_night "❌ ${id}：缺 prompt 文件 ${prompt_file}"; return 1
  fi
  [ -f "$STATE_DIR/${id}.done" ] && { echo "↩ ${id} 已完成（receipt），跳过"; return 0; }  # M3

  local verify manifest
  verify=$(jq -r --arg id "$id" '.tasks[]|select(.id==$id)|.verify // "check"' "$QUEUE")
  manifest=$(jq -r --arg id "$id" '.tasks[]|select(.id==$id)|.manifest // [] | join(" ")' "$QUEUE")
  [ -z "$manifest" ] && { log_night "❌ ${id}：缺 manifest（C4 需声明产出路径前缀），跳过"; return 1; }

  if [ "$DRY_RUN" = 1 ]; then
    echo "[dry-run] ${id}: verify=${verify}  manifest=[${manifest}]"
    return 0
  fi

  local attempt=1
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    echo "▶ ${id} 尝试 ${attempt}/${MAX_ATTEMPTS}"
    local runner=(claude -p "$(cat "$prompt_file")" --allowedTools "$ALLOWED_CSV" --permission-mode default --output-format json)
    [ -n "$TIMEOUT_BIN" ] && runner=("$TIMEOUT_BIN" "$CLAUDE_TIMEOUT" "${runner[@]}")
    "${runner[@]}" > "$STATE_DIR/${id}.json" 2>"$STATE_DIR/${id}.stderr" || true

    local denials; denials=$(jq -r '(.permission_denials // [])|length' "$STATE_DIR/${id}.json" 2>/dev/null || echo "?")
    [ "$denials" != "0" ] && log_night "⚠️ ${id}：${denials} 次权限拒绝（state/${id}.json，可能想碰禁区）"

    if run_verify "$verify" > "$STATE_DIR/${id}.verify" 2>&1; then
      # C4：只精确 stage manifest 路径；manifest 外改动不进 commit、留工作区待人 review。
      local stray; stray=$(stray_changes "$manifest")
      [ -n "$stray" ] && log_night "⚠️ ${id}：manifest 外改动（未提交，请 review/清理）：
$stray"
      git add -- $manifest
      if git diff --cached --quiet; then
        log_night "❌ ${id}：verify 过但 manifest 路径无改动 → blocked"; return 1
      fi
      git commit -q -m "feat(p1): ${id} 无人值守自动提交

$(jq -r --arg id "$id" '.tasks[]|select(.id==$id)|.title' "$QUEUE")

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
      touch "$STATE_DIR/${id}.done"   # M3 receipt
      log_night "✅ ${id} | commit $(git rev-parse --short HEAD) | verify=${verify} 通过"
      return 0
    fi
    echo "  verify 未过，attempt=${attempt}"
    attempt=$((attempt+1))
  done
  log_night "❌ ${id}：${MAX_ATTEMPTS} 次后仍未过 verify=${verify} → blocked"
  return 1
}

# ── 主循环 ────────────────────────────────────────────────────
echo "supervisor v2 启动（dry-run=${DRY_RUN}，分支 ${BRANCH}，timeout=${TIMEOUT_BIN:-none}）"
echo "DB target: $(db_target)（测试环境，DDL 走 Alembic 可重建）"

if [ "$DRY_RUN" = 1 ]; then
  echo "=== dry-run：列出 auto 任务（不执行、不改 queue）==="
  for id in $(jq -r '.tasks[]|select(.auto==true and .status=="pending")|.id' "$QUEUE"); do
    if deps_done "$id"; then run_task "$id"
    else echo "[dry-run] ${id}：依赖未完成 → 实跑标 blocked-deps"; fi
  done
  echo "=== dry-run 结束 ==="; exit 0
fi

while true; do
  next=$(jq -r '[ .tasks[] | select(.status=="pending" and .auto==true) ] | .[0].id // empty' "$QUEUE")
  [ -z "$next" ] && { echo "无 pending auto 任务，结束"; break; }
  if ! deps_done "$next"; then
    log_night "⏸️ ${next}：依赖未完成 → 跳过（需先做依赖任务）。"
    set_status "$next" "blocked-deps"; continue
  fi
  if run_task "$next"; then set_status "$next" "done"; else set_status "$next" "blocked"; fi
done

log_night ""
log_night "## 📊 资源（本次运行）"
log_night "- 完成 $(jq '[.tasks[]|select(.status=="done")]|length' "$QUEUE") / 总 $(jq '.tasks|length' "$QUEUE")"
echo "supervisor 结束。详见 $NIGHT_LOG"
