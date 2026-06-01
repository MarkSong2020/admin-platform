# Review 历史

> 6 轮 review 的发现汇总。每轮列：日期 / 范围 / 关键 finding / 落地版本。**值得留档**——展示决策来源 + 防止重蹈覆辙。

## 第 1 轮 — 2026-05-13 — Codex 原方案 errata（7 项）

由 Codex 提供 `python-web-service-template` 原始方案的 review。修正 7 项 P1/P2，固化在 `Makefile` / `pyproject.toml` / `compose.yaml` / `src/.../db/base.py` 等：

1. `uv pip audit` → `uvx pip-audit`
2. `pyright` 必须 dev 依赖
3. `alembic check` 漂移检测
4. Pydantic Settings 优先级官方默认
5. Redis 标可选 profile
6. 集成测试选 docker compose（不 testcontainers）
7. async ORM `lazy='raise'` 默认

**落地**：`05f9e26` initial commit（v0.0.1）。

## 第 2 轮 — 2026-05-14 — fellow agent 9 项 P0/P1/P2

跨语言 ADR 0001 第二轮 review，9 项 finding：

- §1 instance 字段重复 request_id
- §3 `{service}.{DOMAIN}_{REASON}` 切分过严
- §4 X-Request-ID UUID4 vs hex 跨阶段跳变
- §7.5 cursor 分页"独立约定"违背强制
- §9 WARN vs WARNING 字符长度
- §11 重试条件未限定
- AppError API breaking change（含 detail 字段）
- Java 迁移窗口 Q3→Q4
- Q11 服务前缀治理

**落地**：`989922b` v0.3。

## 第 3 轮 — 2026-05-14 — Independent agent 5 项

第三轮独立 agent fact-check：

- ADR Revision history v0.3 段 AppError 签名语法非法（`detail=None, status_code` 在 keyword-only 之前）
- middleware 缺 OTel TODO 锚点
- generator-design.md 缺 §7.5 偏差提示
- test_access_log.py X-Request-ID hex 格式无断言
- JsonFormatter `level=WARN` 无 mutation 守门

**落地**：`ae65680` v0.3.1（+2 测试守门）。

## 第 4 轮 — 2026-05-14 — 2 个并行 agent，12 项 finding

代码层 + 跨语言契约盲点：

- §9 `logging.py` timestamp 违反 ADR（微秒+offset，应毫秒+Z）
- §3 `framework.HTTP_<n>` 违反 ADR 自禁规则
- `health.py` `str(e)` 泄露 DSN 密码
- middleware finally 异常路径 access log 静默丢失
- `_exit` 类型注解 `NoReturn` 缺失
- X-Request-ID **入站校验**（breaking）
- §1 transport-level 错误说明（CORS preflight）
- §5 `aud` 锁定 = `Settings.service_id`
- §11 timeout 默认值陷阱（httpx 5s vs Java 无超时）
- JSON 字段顺序非强制

**落地**：`f700886` v0.3.2（5 代码 fix + breaking change + ADR 治理）。

**v0.3 → v0.3.2 期间**：`5e7175a` 修订 ADR Python follow-up #5 漂移（基于过期前提，删除）。

## 第 5 轮 — 2026-05-14 — 4 角度抽样

依赖审计 / OpenAPI 契约 / CI 平台 / Migration 端到端：

- ✅ A 依赖审计：`make audit` 56 包 0 CVE
- ⚠ B OpenAPI 422 schema 漂移（FastAPI 默认 vs 运行时 ProblemDetail）
- 🔴 C `.github/workflows/ci.yml` dead code（实际用阿里云效 + Jenkins）
- ⏳ D Migration 端到端 — 等 Docker

**落地**：
- `f73d803` v0.3.3：B-1 ProblemDetail 注入 + 3 测试守门；B-2 §8 基础设施 endpoint 豁免；C `.github/workflows/ci.yml` 标 dead code + 新建 `doc/operations/CI_MIGRATION.md`
- `20a5658` v0.4.2：D Migration 端到端发现 **真 bug** — `migrations/script.py.mako` 缺 `import sa / op`，阻塞 `alembic upgrade head`

## 第 6 轮 — 2026-05-15 — 2 个并行 agent，完整深度

ADR 对账 + 生产准备度 + 整合盲点 + 测试覆盖：

**Agent 1 (ADR vs 实现对账)**：
- ✅ ADR §1-§11 实现层基本全对齐
- ⚠ §5 `Settings.service_id` 文字承诺未实现
- 🔴 文档严重 drift（5 份文件落后于代码 — generator-design / ai-coding-rules / README / CLAUDE.md / AGENTS.md）
- ⚠ ADR Adoption status 历史口径"9 字段"应为 8

**Agent 2 (生产准备 + 跨 feature 盲点)**：
- 🔴 P0: generator POST 端点缺 `@idempotent` 默认
- 🔴 P0: `Settings.service_id` 缺（与 Agent 1 重复）
- ⚠ P1: generated 4xx routes OpenAPI 没声明 → ProblemDetail injection 失效
- ⚠ P1: `test_access_log` 没断言 `trace_id` 字段
- ⚠ P2: 无 eager startup gate

**落地**：本次知识库重组（v0.4.5）：
- 仿 java-reference-service doc/ 七目录骨架
- 6 项 finding 全部进 [../tech-debt/KNOWN_DEVIATIONS.md](../tech-debt/KNOWN_DEVIATIONS.md)
- 修 5 份文档 drift
- 修 ADR Adoption status（用户在 IDE 中已同步到 v0.4.4 Implemented）

## 经验教训（pattern recognition）

每轮 review 都暴露**前一轮没看到的角度**。Pattern：

1. **第 1 轮**：原方案 bug —— 直接审 input
2. **第 2-3 轮**：ADR 文字内部一致性 —— 自我对账
3. **第 4 轮**：代码层 + 跨语言整合 —— 跨视角
4. **第 5 轮**：生产准备 + 真跑 E2E —— **真实生产环境角度**才能抓到 mako import bug
5. **第 6 轮**：完整 ADR vs 代码 + 文档 drift + 测试 mutation —— 深度对账

**结论**：
- 单一 agent review 容易 miss 跨视角问题 → 后续大变更建议**派 2-3 agent 并行**不同角度
- **真跑 E2E** 比单测能抓更多 bug（mako import / `_custom_openapi` 不改未声明 response 等）
- 文档 drift 永远存在 → 每次 commit 必跑 drift 检查（PR template 加 checkbox）

## 下次 review 触发条件

- 加新 Python follow-up（按 ADR Open Q 决议）
- 升级 FastAPI / SQLAlchemy major 版本
- 接入 OTel SDK
- 接入 JWT 鉴权
- 加第二个 Python 服务用本模板 → 真实使用反馈
