# Admin Platform → RuoYi 对标能力地图与路线图

> **状态**：规划稿 v1，待 review（你选的"先做能力地图"起点的产物）
> **日期**：2026-06-04
> **定位决策（2026-06-04 与用户敲定）**：
> 1. **单租户**——回归 RuoYi 本体（不做 SaaS 多租户）
> 2. **参考 RuoYi-Vue3-FastAPI** 的表结构/API 设计，适配本仓工程纪律（IdMixin / 命名规范 / AppError / 分层硬约束 / 中文 docstring）
> 3. **后端 + Vue3 前端**，端到端对标 RuoYi-Vue
> **上游**：[`2026-06-02-p0-multitenant-auth-foundation.md`](./2026-06-02-p0-multitenant-auth-foundation.md)
> ⚠️ **重大方向变更**：上游 P0 spec 是**多租户**假设下写的；本路线图基于"单租户回归"决策，**P0 的多租户机制转为待重构项**（见 §3）。这是有意识推翻 P0 部分工作，沉没成本见 §3 影响评估。

---

## 一句话结论

> admin-platform 有**扎实的工程地基**（认证 / RFC9457 错误 / 分页 / 幂等 / 代码生成 / CI / 85% 覆盖门），但**对标 RuoYi 的业务功能几乎全缺**——目前只有 `user` 一个业务域的 CRUD。
>
> 回归单租户后，按 **单租户回归重构（前置）→ RBAC → 审计日志 → 字典/参数/通知 → 监控/任务 → 工具 → 前端** 分阶段补齐，每阶段独立可验证。**首要前置 = 单租户回归重构**：不先拆掉 P0 的多租户机制，RBAC 的角色/菜单/部门建模会被 `tenant_id` 语义持续拖累。

---

## 1. 决策记录（locked）

| # | 决策 | 理由 | 影响 |
|---|---|---|---|
| D1 | **单租户**，不做 SaaS 多租户 | RuoYi 本体即单租户；用户确认服务对象是"一个组织内部"，非"卖给 N 家客户" | P0 多租户机制（tenant 隔离）作废，回退为 RuoYi 式 dept 数据权限 |
| D2 | 先做**能力地图**再写码 | 范围巨大（RuoYi 后端 ~15 模块 + 前端），先定全貌避免跑偏 | 本文档 = 该地图；review 通过后才进 P0.9 |
| D3 | 参考 **RuoYi-Vue3-FastAPI** + 适配 | 成熟 Python 移植，少踩坑；但其工程纪律与本仓不同，需适配 | 表结构/API 借鉴其设计，落地走本仓 `make new-module` + 分层红线 + 中文 docstring |
| D4 | 后端 + **Vue3 前端** | 真正端到端对标 RuoYi-Vue | 引入前端工程栈（Vue3 + Element Plus + Vite），P6 独立阶段 |

> **未定、留各阶段拍板的不可逆决策**：RBAC 具体表结构（P1 设计时拉 Codex PK）；数据权限实现机制（拦截器 vs 查询注入）；定时任务选型（APScheduler vs Celery beat）；前端模板（直接 fork RuoYi-Vue3-FastAPI 前端 vs 自建）。

---

## 2. RuoYi 功能矩阵 × admin-platform 现状

> 对标基准 = RuoYi-Vue3-FastAPI 的标准模块集。状态：✅ 已有 / 🟡 部分 / ❌ 无。
> **表结构/字段为模块级对标，具体 schema 在各阶段实现时核对 RuoYi-Vue3-FastAPI 源码**（避免凭印象编字段）。

### 2.1 系统管理（system）

| RuoYi 模块 | RuoYi 表（参考） | admin 现状 | gap | 阶段 |
|---|---|---|---|---|
| 用户管理 | `sys_user` | 🟡 `users` 表 + 五层 CRUD（带 tenant_id/is_platform_admin，单租户回归要清理） | 缺 dept_id/post 关联、头像、状态细分、密码策略 | P0.9 + P1 |
| 角色管理 | `sys_role` | ❌ | 全缺：角色表 + data_scope 字段 | **P1** |
| 菜单/权限 | `sys_menu` | ❌（仅预留 `FORBIDDEN_BY_ROLE/SCOPE` 错误码） | 全缺：菜单树（目录/菜单/按钮）+ 权限标识 `perms` | **P1** |
| 部门管理 | `sys_dept` | ❌（P0 ADR-B 明确不预留 dept） | 全缺：部门树 + 数据权限载体 | **P1** |
| 岗位管理 | `sys_post` | ❌ | 全缺 | **P1** |
| 用户-角色 | `sys_user_role` | ❌ | 全缺关联表 | **P1** |
| 角色-菜单 | `sys_role_menu` | ❌ | 全缺关联表 | **P1** |
| 角色-部门 | `sys_role_dept` | ❌ | 全缺（自定义数据权限范围） | **P1** |
| 字典管理 | `sys_dict_type` / `sys_dict_data` | ❌ | 全缺 | **P3** |
| 参数设置 | `sys_config` | ❌ | 全缺 | **P3** |
| 通知公告 | `sys_notice` | ❌ | 全缺 | **P3** |
| 操作日志 | `sys_oper_log` | ❌ | 全缺（需 AOP/中间件织入） | **P2** |
| 登录日志 | `sys_logininfor` | ❌ | 全缺 | **P2** |

### 2.2 系统监控（monitor）

| RuoYi 模块 | admin 现状 | gap | 阶段 |
|---|---|---|---|
| 在线用户 | ❌ | 依赖 token/session 落库（与 P1 refresh token 联动） | P4 |
| 定时任务 | ❌ | APScheduler + 任务管理 API（RuoYi 用 Quartz） | **P4** |
| 服务监控（CPU/内存/磁盘） | ❌ | psutil 采集 + API | P4 |
| 缓存监控（Redis） | 🟡 有 Redis 接入（幂等用），无监控面板 | Redis info/keys 查询 API | P4 |
| 数据监控（Druid SQL 监控）| ❌ | RuoYi 特有（Java Druid），Python 侧用别的或省略 | 省略/替代 |

### 2.3 系统工具（tool）

| RuoYi 模块 | admin 现状 | gap | 阶段 |
|---|---|---|---|
| 代码生成 | 🟡 `make new-module`（CLI 生成五层 domain） | RuoYi 是"读库表 → 生成 CRUD"的在线 codegen；admin 是模板驱动 CLI。**定位不同**，对标策略见 §7 | P5 |
| 系统接口（API 文档）| ✅ OpenAPI `/openapi.json` + Swagger UI | 基本对齐 | — |
| 表单构建 | ❌ | 前端可视化拖拽（低优先，可省） | P6+ / 省略 |

### 2.4 横切基础设施（admin 强于 RuoYi 的部分）

| 能力 | admin 现状 | 说明 |
|---|---|---|
| 错误响应 | ✅ RFC 9457 ProblemDetail 8 字段 | 比 RuoYi 的 `{code,msg,data}` 更标准 |
| Request ID / W3C trace | ✅ | RuoYi 无 |
| 健康检查三轨 | ✅ /healthz /readyz /startupz | RuoYi 无 |
| 幂等性 | ✅ @idempotent + Redis 两阶段 | RuoYi 无 |
| OTel 可观测性 | ✅（默认关闭） | RuoYi loguru + Redis Stream 日志聚合 |
| 分层硬约束 + import-linter | ✅ C1-C7 机检 | RuoYi 约定，无机检 |
| 后端测试 | ✅ unit+api+integration | RuoYi 后端零单测，仅 Playwright E2E |
| 迁移治理 | ✅ Alembic 版本链 + drift 检测 | RuoYi create_all 自动建表 |
| 类型检查 | ✅ pyright（standard）| RuoYi 无 type checker |

> **结论（v2，2026-06-05 工程质量对标 + Codex PK 修订；原"已超过 RuoYi、缺纯业务功能"为自我拔高，已纠正）**：admin 在**动态质量保障**（测试 / 版本化迁移 / 类型检查 / 分层机检 / 错误标准化 / 可观测 / 生成器守门）上强于 RuoYi；但 RuoYi 在**功能广度、声明式 AOP 横切能力（数据权限/审计/限流/缓存）、安全闭环、前后端一体**上强于 admin——其中 **AOP 横切是真工程质量、不是业务功能**。**"工程质量更高"不会因底座强而自然成立，取决于纪律能否扩展到 10+ 模块不降级 + AOP 横切是否做好。** 完整对标见 §9。

---

## 3. 前置：单租户回归重构（P0.9，破坏性，需单独确认）

> D1 决策的直接后果。**这是破坏性重构（删机制 + 改迁移 + 改测试），按破坏性操作纪律单独走流程、单独 review，不和 RBAC 混在一个 commit。**

### 3.1 拆除清单（多租户机制 → 移除/简化）

| 项 | 文件 | 处理 |
|---|---|---|
| 租户过滤事件 | `db/tenant_filter.py`（`do_orm_execute` + `before_flush`） | 移除 |
| TenantMixin | `db/`（mixin 定义） | 移除 |
| tenant 上下文传播 | `get_session` 注入 `session.info["tenant_ctx"]` | 移除注入逻辑 |
| tenants 表 | `domains/tenant/` + migration `0002` | 移除（或降级为可选；单租户无需） |
| user.tenant_id / is_platform_admin | `domains/user/models.py` + migration | 移除 tenant_id；`is_platform_admin` → 改 RuoYi 式 `是否超管` 标志或并入角色 |
| 多租户隔离测试 | `tests/.../test_tenant_isolation.py` | 移除/改写 |
| system_session bypass | 登录/CLI 的显式 bypass | 简化（单租户无隔离，无需 bypass） |
| 多租户文档 | `doc/architecture/MULTI_TENANCY.md` + ADR-A/B/E | 归档为"已废弃方向"，记决策原因 |

### 3.2 保留（与多租户无关的地基）

✅ `core/auth.py`（JWT 校验）· `core/security.py`（Argon2 + token 签发）· `domains/auth`（登录，去掉 tenant_code 维度）· `domains/user` 五层骨架（去 tenant 字段）· 所有横切基础设施（错误/分页/幂等/健康检查/OTel/CI）。

### 3.3 影响评估（沉没成本）

- **作废**：P0 的 Task 3（fail-closed 隔离）/ Task 7（上下文传播）/ Task 10（隔离验收）+ MULTI_TENANCY.md + ADR-A/B/E + RLS spike（Task 12）。约占 P0 工作量的 40-50%。
- **保留有效**：认证签发、密码安全、user CRUD 骨架、CLI、全部横切设施。
- **风险**：迁移重写（drop tenant_id 是破坏性 schema 变更——但仓库尚无生产数据，dev 库重建即可）。
- **⚠️ 二次确认点**：单租户回归会丢弃可观的 P0 隔离工作。如果你对"将来不会变成多租户"没有把握，现在是重新考虑 (B) 多租户方案的最后窗口。否则我按单租户推进。

### 3.4 验收

`make check` 全绿（移除隔离测试后测试数下降是预期）· `make test-integration` 绿 · 登录/user CRUD 在无 tenant 维度下跑通 · MULTI_TENANCY 决策归档可追溯。

---

## 4. 分阶段路线图（单租户版，重画）

```
P0   多租户认证地基            ✅ 已完成（但含待回退的多租户部分）
P0.9 单租户回归重构            ← 前置，拆多租户（§3）
P1   RBAC（核心，对标灵魂）     角色/菜单/部门/岗位 + user↔role↔menu↔dept + 数据权限 5 范围
                              + 登录增强（refresh token 落库可撤销 + 验证码）
P2   审计日志                 操作日志（中间件织入）+ 登录日志 + 在线用户雏形
P3   运营配置                 字典管理 + 参数设置 + 通知公告
P4   监控/任务                定时任务（APScheduler）+ 服务/缓存监控
P5   工具                    代码生成对标（§7）+ Excel 导入导出 + 文件上传
P6   前端                    Vue3 + Element Plus：登录 → 用户/角色/菜单/部门/字典 管理界面 + 动态菜单/按钮权限
```

**每阶段可验证目标**：

| 阶段 | 可验证目标（命令式 → 可验证） |
|---|---|
| P0.9 | 移除 tenant 机制后 `make check` 绿；单租户登录+user CRUD 端到端通；多租户决策归档 |
| P1 | 建超管→建角色→配菜单/数据权限→建用户绑角色→该用户登录只能访问授权菜单/数据（端到端测试通过）；refresh token 可签发+可撤销测试通过 |
| P2 | 任意写操作落 1 条操作日志（含操作人/IP/耗时/结果）；登录成功/失败各落 1 条登录日志（断言测试） |
| P3 | 字典 CRUD + 前端按字典渲染下拉；参数热更新生效；通知发布可见 |
| P4 | 定时任务可增删改查+手动触发+执行日志；/monitor 返回真实 CPU/内存/Redis 指标 |
| P5 | 给一张表生成可用 CRUD 代码（对标 RuoYi gen）；Excel 导入导出往返一致 |
| P6 | 前端跑通登录→动态菜单→各管理页 CRUD；按钮级权限隐藏；与后端 OpenAPI 对齐 |

**各阶段工程红线**（2026-06-05 Codex PK 收敛，吸收 §9 对标）：
- **P1.0（P1 前置 spec，机制先于建表）**：先定权限装饰器/依赖（`@requires_permission` / `@data_scope`）、data_scope 查询注入策略、超管模型、权限缓存失效策略，并**冻结前端接口契约**（动态菜单 / 路由 meta / 按钮权限 / 当前用户权限列表 API）——否则 RBAC 沦为 CRUD 表、前端 P6 返工。
- **每模块 DoD 红线**：五层 + Alembic 迁移 + service/api/integration 测试 + **权限矩阵测试**（超管 / 无权限 / 菜单权限 / 按钮权限 / 数据范围 5 类）+ pyright + import-linter 全绿。
- **P2 红线**：审计走**声明式注解**（非纯 middleware）；登录失败 / 权限拒绝 / 写异常都有审计断言。
- **P4 红线**：定时任务先定多 worker 安全策略（leader election / DB lock / 单 worker 约束）——APScheduler 多 worker 会重复执行。
- **P5 红线**：codegen 输出自带 tests / migration / doc / schema-doc 挂钩，不只生成代码。

---

## 5. RBAC 数据模型方向（P1，单租户）

> 单租户下，角色/菜单/部门/岗位**全部全局**（无 tenant_id）。这是回归 RuoYi 本体后最自然的模型。

**核心表（参考 RuoYi-Vue3-FastAPI，具体字段 P1 设计时核对源码 + 拉 Codex PK）**：
- `roles`（角色 + `data_scope` 数据权限范围字段）
- `menus`（菜单树：目录/菜单/按钮三类 + `perms` 权限标识 + 路由/组件元数据供前端动态路由）
- `depts`（部门树，数据权限载体）
- `posts`（岗位）
- 关联：`user_roles` · `role_menus` · `role_depts`（自定义数据权限）· `user_posts`

**数据权限 5 范围**（RuoYi 标准）：全部 / 自定义部门 / 本部门 / 本部门及以下 / 仅本人。实现机制（查询注入 vs 拦截器）P1 设计时定，拉 Codex PK。

**适配本仓纪律**：
- 走 `make new-module` 生成五层骨架（不手抄）
- 主键用 `IdMixin`（BIGINT），时间用 `TimestampMixin`
- 命名遵循 `NAMING_CONVENTIONS`（表复数、列 snake_case、列必带 comment）
- 权限校验中间件/依赖：扩展 `core/auth.py`，落地预留的 `require_role` / `require_scope` 语义
- 异常走 `AppError`，错误码 `auth.FORBIDDEN_BY_ROLE` / `FORBIDDEN_BY_SCOPE`（常量已存在）

---

## 6. 前端方向（P6，Vue3 + Element Plus）

- **栈**：Vue3 + TypeScript + Vite + Element Plus + Pinia（对标 RuoYi-Vue3 前端栈）
- **起步选择（待 P6 定）**：(a) 直接 fork RuoYi-Vue3-FastAPI 前端改 API 对接 vs (b) 用本仓 OpenAPI 生成 SDK + 自建。建议 (a) 起步快、(b) 更可控——P6 时权衡。
- **核心页面**：登录 → 动态菜单（按后端菜单树渲染路由）→ 用户/角色/菜单/部门/字典 管理 → 按钮级权限指令（`v-hasPermi`）
- **依赖后端**：菜单树 API（动态路由）+ 用户权限标识列表（按钮权限）——P1 RBAC 要预留这两个接口形态

---

## 7. 待核对 / 开放问题

| # | 问题 | 何时定 |
|---|---|---|
| Q1 | RuoYi-Vue3-FastAPI 的具体表结构/字段/API 契约 | P1 实现前核对其源码（GitHub） |
| Q2 | 代码生成器对标：admin 的 `make new-module`（模板驱动 CLI）vs RuoYi 的"读库表在线生成"——是改造 generator 支持读表，还是保持 CLI 不强对标？ | P5 |
| Q3 | 数据监控（RuoYi Druid SQL 监控）Python 侧做不做、用什么替代 | P4 |
| Q4 | 定时任务选型：APScheduler（轻）vs Celery beat（重，需 broker） | P4 |
| Q5 | 前端 fork RuoYi 前端 vs 自建 | P6 |
| Q6 | 超管模型：`is_super_admin` 布尔短路 / 内置超级管理员角色 / 二者组合？（不能靠魔法 `role_id=1`）| **P1 拍板** |
| Q7 | data_scope 实现机制：repository 查询注入 / service 显式 scope / SQLAlchemy 事件 / 装饰器传 scope context？ | **P1 拍板** |
| Q8 | 权限缓存：依赖 Redis？失效由角色/菜单修改同步触发，还是短 TTL？ | **P1 拍板** |
| Q9 | 前端：fork RuoYi-Vue3 前端（快、但倒逼后端适配其 API）vs 自建（慢、契约更干净）| **接口契约 P1 冻结 / 实现 P6** |
| Q10 | 定时任务部署模型：单实例约束 / DB advisory lock / Redis lock / Celery beat | **P4 拍板** |

> **Q6–Q10 是不可逆架构决策**（Codex PK 标记升级）——实现前必须由人拍板，不由 AI 自裁。Q9 的接口契约部分要 **P1 就冻结**（不能拖到 P6）。

---

## 8. 下一步

1. ✅ **P0.9 单租户回归已完成**（2026-06-05，3 commit + 全链路验证：`make check` 202 / migrate / `check-db` 零漂移 / integration 19 passed）。
2. **进 P1**：先做 **P1.0 RBAC/AOP 机制 spec**（拍板 §7 Q6–Q9 + 冻结前端接口契约），再铺角色/菜单/部门/岗位表——**机制先于建表**（§4 工程红线）。表结构设计拉 Codex PK。
3. 实现前先解 §7 的 Q6–Q10 不可逆决策（人拍板，不由 AI 自裁）。

> 本路线图是**活文档**：每阶段实现时回灌真实反馈（如 RuoYi-Vue3-FastAPI 源码核对结果、Codex PK 结论）。

---

## 9. 工程质量对标 RuoYi（2026-06-05，调研 + Codex PK 收敛）

> 对标基准：`insistence/RuoYi-Vue3-FastAPI` v1.9.0 后端（实读源码调研）。本节把对标洞察固化进迭代计划——**既不自我拔高，也不忽视 RuoYi 真正的工程长板**（原 §2.4 "已超过 RuoYi" 经 Codex PK 纠正）。

### 9.1 客观对比（逐维度）

| 维度 | admin（按 roadmap 做完）| RuoYi | 谁强 |
|---|---|---|---|
| 后端测试 | unit+api+integration（覆盖率门见 9.3）| 零后端单测，仅 Playwright E2E 冒烟 | **admin ★** |
| 迁移治理 | Alembic 版本链 + drift 检测 | create_all 自动建表，零版本化迁移 | **admin ★** |
| 类型检查 | pyright standard | 无 type checker（ruff 只查注解有无）| **admin**（但非 strict）|
| 分层治理 | import-linter C1–C7 机检 | 五层一致但纯约定，有泄漏 | **admin** |
| 错误/可观测 | RFC9457 + OTel + W3C trace | code/msg/data + loguru + Redis Stream 日志聚合 | 平（各有强项）|
| 安全默认 | Argon2id + CORS 白名单 + SECRET 必填 | bcrypt + **CORS\*+credentials** + 硬编码默认密钥 | **admin** |
| **声明式 AOP 横切** | roadmap 原只写"中间件织入"，无机制 | **data_scope/鉴权/缓存/限流/日志注解，密集复用** | **RuoYi ★（admin 要补）** |
| 安全闭环 | 无传输加密/防重放/限流体系 | RSA-OAEP+AES-GCM 传输加密 + 防重放 + 限流 | **RuoYi（按威胁模型取舍）** |
| 功能广度 | auth + user CRUD | **19 模块 + Vue3 + uni-app 移动端** | **RuoYi ★碾压** |
| 开发速度 | 高纪律显著变慢 | fork 即用，起步快 | **RuoYi** |

### 9.2 ★ 关键认知修正（Codex PK 戳破的盲点）

**RuoYi 的声明式 AOP 横切能力（`data_scope` 行级数据权限 / 接口鉴权 / 缓存 / 限流 / 日志注解）是真工程质量，不是业务功能。** 它决定"每个业务模块要不要重复造权限/审计轮子"。admin 若 P1/P2 只做 CRUD 表 + 散装 middleware，后续每个域都重复权限/审计逻辑——**这才是 RuoYi 最值得学的，必须在 P1.0 先设计机制、再铺表**（见 §4 工程红线）。

### 9.3 诚实限定（Codex PK 核实，不夸大 admin 优势）

- pyright 是 **standard 非 strict**——复杂 RBAC 查询 / 动态 JSON / 权限缓存仍可能有运行时类型错误。
- 85% 覆盖率 `fail_under` 只在 `make coverage` 生效，**不在 `make check` / CI 阻断路径**——覆盖率是"软门"。**建议 P1 顺手把 coverage 纳入 CI 阻断，否则优势只是文档口径。**
- admin **没有复杂度/文件大小门**（ruff 已有 `ASYNC` ✓ 但无 `C901`/`PERF`）——建议补，否则模块多了同样会长出大文件。

### 9.4 借鉴清单（吸收进各阶段）

- **[P1] data_scope**：参考 RuoYi 5 范围（全部 / 自定义部门 / 本部门 / 本部门及以下 / 仅本人）+ 声明式注入思路，落地用查询注入 + 测试覆盖（机制定夺见 §7 Q7）。
- **[P1 顺手] ruff 补 `PERF` + `C901`**（已有 ASYNC）；评估把 coverage 纳入 CI 阻断。
- **[P2] 声明式审计注解**（非纯 middleware）：操作标题 / 业务类型 / 操作者 / 耗时 / 结果 / 异常 + 脱敏。
- **[P2] Redis Stream 多 worker 日志聚合**评估。
- **[各阶段] RuoYi 19 模块 = 功能蓝本 + 表结构参考**（具体字段 P1 核对其源码，§7 Q1）。

### 9.5 避雷清单（坚持不学，已是工程红线）

| ❌ RuoYi 的做法 | ✅ admin 坚持 |
|---|---|
| create_all 自动建表 | Alembic 版本化 + drift 检测 |
| 后端零测试靠 E2E 兜底 | 每模块 service/api/integration + 权限矩阵测试 |
| CORS `*` + credentials | 白名单（validator 已阻断）|
| 硬编码 JWT/DB 密钥 | SECRET 空 fail-fast（已有）|
| 关复杂度门放任大文件 | 补复杂度/文件预算（9.3）|
| 分层靠约定 | import-linter（新 domain 自动纳入 C1）|
| 魔法超管 id（`role_id=1`）| P1 拍板超管模型（§7 Q6）|

### 9.6 路线选择提醒（防自欺）

**目标决定路线**：要"1–2 个月交付内部后台" → fork RuoYi 改更划算；要"团队长期 Python 后台脚手架 + 工程标准样板" → admin 路线才值。**最大风险 = 纪律可持续性**：模块扩张后最先被偷懒的是 integration test / migration review / doc drift——优势一偷懒就蒸发。
