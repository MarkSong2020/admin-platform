#!/usr/bin/env bash
# scripts/smoke_generator.sh — generator 端到端烟测
#
# 真跑一遍 `make new-module name=smoke_probe with-model=1` → `make check`，
# 复现新人 onboarding 流程，验证 generator 的产出在主干代码下能直接通过
# 质量门（ruff format / ruff check / pyright / pytest）。
#
# 为什么需要：v0.4.13 generator 加 alembic env.py auto-patch 时漏了 isort
# 的 blank-line 要求，v0.4.15 才被发现——生成器是用户跟模板的第一接触点，
# 静默劣化代价高。本脚本作为最后一道结构性防线。
#
# 安全网（pre-mortem 后保留）：
#   1. 工作区脏（生成器目标路径下有未提交改动）→ 拒绝跑；避免把用户
#      在写的代码搞混 / cleanup 时误删。
#   2. 目标路径 smoke_probe 已存在 → 拒绝；避免覆盖真业务模块。
#   3. `trap on_exit EXIT` → 不管成功失败 / 中途 Ctrl-C 都清掉 smoke 产物
#      并把 migrations/env.py 还原。
#
# 退出码：0 成功；2 前置检查失败；其它来自 make check。
#
# 模块名固定 smoke_probe（不是 _smoke，generator 的 NAME_REGEX 要求字母
# 开头）。所有 cleanup 路径都基于这个名字，便于审计。

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

MODULE="smoke_probe"
DOMAINS_INIT="src/admin_platform/domains/__init__.py"
PROBE_DOMAIN="src/admin_platform/domains/${MODULE}"
PROBE_TEST_UNIT="tests/unit/test_${MODULE}_service.py"
PROBE_TEST_API="tests/api/test_${MODULE}_api.py"
ENV_PY="migrations/env.py"
SCHEMA_DOC="docs/architecture/DATA_MODEL.md"

# Generator 在首次跑时会顺手创建 domains/__init__.py（详见 new_module.py
# _target_paths 注释）。记录进入前是否存在，cleanup 时按原状态还原，避免
# 残留一个空 __init__.py 污染下次 dirty check。
DOMAINS_INIT_EXISTED=0
[ -e "$DOMAINS_INIT" ] && DOMAINS_INIT_EXISTED=1

# --- Safety net 1: 工作区在相关路径必须干净 ---
DIRTY="$(git status --porcelain -- \
  "src/admin_platform/domains" \
  "tests/unit" \
  "tests/api" \
  "$ENV_PY" \
  "$SCHEMA_DOC" 2>/dev/null || true)"
if [ -n "$DIRTY" ]; then
  echo "==> smoke: ABORT — 工作区在 generator 相关路径有未提交改动；先 commit/stash：" >&2
  echo "$DIRTY" >&2
  exit 2
fi

# --- Safety net 2: 目标路径必须空（绝不覆盖真业务模块） ---
for p in "$PROBE_DOMAIN" "$PROBE_TEST_UNIT" "$PROBE_TEST_API"; do
  if [ -e "$p" ]; then
    echo "==> smoke: ABORT — ${p} 已存在；手动清理后再跑。" >&2
    exit 2
  fi
done

on_exit() {
  local rc=$?
  echo "==> smoke: cleanup（rc=${rc}）"
  # PROBE_DOMAIN 进 smoke 前已校验不存在 → rm -rf 局限于生成产物。
  rm -rf "$PROBE_DOMAIN"
  rm -f "$PROBE_TEST_UNIT" "$PROBE_TEST_API"
  # 仅当 generator 是本次新建 domains/__init__.py 时才删（保持幂等）。
  if [ "$DOMAINS_INIT_EXISTED" -eq 0 ] && [ -e "$DOMAINS_INIT" ]; then
    rm -f "$DOMAINS_INIT"
  fi
  # 还原 generator 对 migrations/env.py 的 patch（脚本入口已校验 env.py
  # 在脏状态白名单内，所以 checkout 不会丢用户的未提交工作）。
  if [ -f "$ENV_PY" ]; then
    git checkout -- "$ENV_PY" >/dev/null 2>&1 || true
  fi
  # 还原 schema-doc 对 DATA_MODEL.md 的 regenerate（含临时 smoke_probe 表），入口已校验其干净。
  git checkout -- "$SCHEMA_DOC" >/dev/null 2>&1 || true
  exit "$rc"
}
trap on_exit EXIT

echo "==> smoke: make new-module name=${MODULE} with-model=1"
make -s new-module name="$MODULE" with-model=1 >/dev/null

# with-model 生成了 smoke_probe 表 → regenerate DATA_MODEL.md，让 make check 的 dump_schema
# --check（H7 门禁）不因临时模块 drift 误失败（反映「加模块 → schema-doc → check」真实流程）；
# cleanup 时 git checkout 还原（入口已把 DATA_MODEL.md 纳入 dirty check 白名单）。
echo "==> smoke: make schema-doc（含临时 smoke_probe 表，cleanup 还原）"
make -s schema-doc >/dev/null

echo "==> smoke: make check"
make -s check

echo "==> smoke: OK"
