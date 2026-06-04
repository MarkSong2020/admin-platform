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
| OTel 可观测性 | ✅（默认关闭） | RuoYi 无 |
| 分层硬约束 + import-linter | ✅ C1-C7 机检 | RuoYi 无 |
| 测试 + 85% 覆盖门 | ✅ | RuoYi 无强制 |

> **结论**：admin 的"工程质量底座"已超过 RuoYi；缺的纯粹是**业务功能模块**。对标 = 在这个好底座上补 RuoYi 的业务能力，而**不是**降级去模仿 RuoYi 的工程做法。

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
| Q6 | 单租户回归后，`is_platform_admin` 改成 RuoYi 式"超级管理员角色"还是保留布尔标志 | P0.9/P1 |

---

## 8. 下一步

1. **你 review 本地图**——尤其 §3.3 的"单租户回归会丢弃 P0 部分工作"二次确认点，以及 §4 路线图优先级是否符合预期。
2. review 通过 → 进 **P0.9 单租户回归重构**（破坏性，单独 spec + Codex PK 拆除方案 + 谨慎执行）。
3. P0.9 完成 → 进 **P1 RBAC**（对标灵魂，最大价值；表结构设计拉 Codex PK）。

> 本路线图是**活文档**：每阶段实现时回灌真实反馈（如 RuoYi-Vue3-FastAPI 源码核对结果、Codex PK 结论）。
