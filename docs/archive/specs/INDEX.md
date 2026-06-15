# Spec 导航

> 各阶段设计决策的 spec 索引。每份 spec 是「为何这样设计」的决策留痕，**按 P0 → P6 阶段递进**组织。
> 核心流向：P0 单租户回归 → P1 RBAC → P2 审计 → P3 运营配置 → P4 监控/任务 → P5 工具 → P6 前端，对标 RuoYi 逐档补齐。
> 状态：✓ 已落地 ｜ 🚧 进行中 ｜ 🗺 路线图 ｜ ⛔ 历史/已废弃方向。

| 阶段 | Spec | 一句话主题 | 状态 |
|---|---|---|---|
| 全景 | [`2026-06-04-ruoyi-parity-roadmap.md`](./2026-06-04-ruoyi-parity-roadmap.md) | 按 RuoYi 对标补齐后台业务功能的全景能力地图与路线图（含「单租户回归」重构）| 🗺 路线图 |
| **P0** | [`2026-06-02-p0-multitenant-auth-foundation.md`](./2026-06-02-p0-multitenant-auth-foundation.md) | 多租户隔离 + 认证地基的实施计划 | ⛔ **历史/已废弃**（2026-06-05 单租户回归，多租户机制已于 P0.9 完整拆除；仅作历史决策留痕，不反映现行设计）|
| **P1.0** | [`2026-06-05-p1.0-rbac-mechanism.md`](./2026-06-05-p1.0-rbac-mechanism.md) | RBAC 声明式横切机制 + 前端契约（机制先于建表，含 `getInfo`/`getRouters`、数据权限）| ✓ |
| **P1.4** | [`2026-06-09-p1.4-login-enhancement.md`](./2026-06-09-p1.4-login-enhancement.md) | 登录增强：refresh token 轮换 + reuse detection + 算术验证码 + 登录限流 | ✓ |
| **P1.5** | [`2026-06-09-p1.5-rbac-binding-audit.md`](./2026-06-09-p1.5-rbac-binding-audit.md) | RBAC 角色/菜单/部门绑定管理 API + `rbac_write` 审计织入 | ✓ |
| **P2** | [`2026-06-09-p2-audit-persistence.md`](./2026-06-09-p2-audit-persistence.md) | 审计事件 + 登录日志数据库持久化 + IP/UA 上下文中间件 + 监控查询 API | ✓ |
| **P3** | [`2026-06-09-p3-operational-config.md`](./2026-06-09-p3-operational-config.md) | 运营配置三件套：字典（类型+数据）/ 参数（热更新读穿）/ 通知公告 | ✓ |
| **P4** | [`2026-06-10-p4-monitoring-tasks.md`](./2026-06-10-p4-monitoring-tasks.md) | 服务/缓存监控（psutil + Redis INFO 降级）· 在线用户（强制下线）· APScheduler 定时任务（leader election + handler 白名单防 RCE）| ✓ |
| **P5** | [`2026-06-11-p5-file-management.md`](./2026-06-11-p5-file-management.md) | 文件管理（对标 RuoYi sys_oss：StorageBackend 抽象 + 本地存储 + 安全模型）+ 砍除在线 codegen | ✓ |
| **P5** | [`2026-06-11-p5-excel-import-export.md`](./2026-06-11-p5-excel-import-export.md) | 通用 Excel 导入（一步全有全无）/ 导出无状态叶子机制 + post 绑定 | ✓ |
| **P6** | [`2026-06-11-p6-frontend-design.md`](./2026-06-11-p6-frontend-design.md) | 前端技术栈选型与架构：完全自建 Vue3 + TS（不 fork RuoYi），对标后端工程纪律 | 🚧 进行中 |

---

## 阅读建议

- **理解项目现状** → 先读 [`2026-06-04-ruoyi-parity-roadmap.md`](./2026-06-04-ruoyi-parity-roadmap.md)（全景），再按阶段下钻。
- **⛔ 注意废弃方向**：[`2026-06-02-p0-multitenant-auth-foundation.md`](./2026-06-02-p0-multitenant-auth-foundation.md) 描述的多租户方向**已于 2026-06-05 回归单租户**而废弃，文中引用的 `tenant_filter` / `TenantMixin` / `tenants` 表等源文件大多已不存在。废弃背景见 [`../architecture/MULTI_TENANCY.md`](../../architecture/MULTI_TENANCY.md)。
- **标准/原则**（非阶段决策）→ [`../STANDARDS.md`](../../STANDARDS.md)。
- **文档总导航** → [`../INDEX.md`](../../INDEX.md)。
