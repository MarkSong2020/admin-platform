# 数据模型速览（DATA_MODEL）

> ⚠️ **生成物，请勿手改。** 本文件由 `scripts/dump_schema.py` 从 ORM models 自省生成。
> **真相源 = `src/admin_platform/domains/*/models.py` + `db/base.py`（公共列/mixin）**；
> 物化 DDL 见 `migrations/versions/`。改表结构 → 改 models + 迁移 → `make schema-doc` 重生本文件。
>
> - 再生：`make schema-doc`（= `uv run python scripts/dump_schema.py`）
> - 校验是否最新：`uv run python scripts/dump_schema.py --check`（差异即非零退出）
> - 类型以 MySQL 方言渲染；models↔迁移↔活库的漂移由 `make check-db` 守门。

## 表清单

- [`app_locks`](#app_locks)（1 列）
- [`audit_events`](#audit_events)（29 列）
- [`configs`](#configs)（8 列）
- [`depts`](#depts)（11 列）
- [`dict_types`](#dict_types)（8 列）
- [`login_logs`](#login_logs)（11 列）
- [`menus`](#menus)（14 列）
- [`notices`](#notices)（8 列）
- [`posts`](#posts)（7 列）
- [`roles`](#roles)（8 列）
- [`scheduled_tasks`](#scheduled_tasks)（15 列）
- [`dict_data`](#dict_data)（12 列）
- [`role_depts`](#role_depts)（5 列）
- [`role_menus`](#role_menus)（5 列）
- [`scheduled_task_logs`](#scheduled_task_logs)（19 列）
- [`users`](#users)（10 列）
- [`auth_refresh_tokens`](#auth_refresh_tokens)（14 列）
- [`files`](#files)（12 列）
- [`user_posts`](#user_posts)（5 列）
- [`user_roles`](#user_roles)（5 列）

## 表结构

### `app_locks`

> 来源 model：`admin_platform.db.locks.AppLock`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `name` | VARCHAR(191) | NOT NULL | — | 锁名 | PK |

### `audit_events`

> 来源 model：`admin_platform.audit.models.AuditEventLog`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `event_id` | VARCHAR(64) | NOT NULL | — | 事件UUID(幂等键) |  |
| `schema_version` | VARCHAR(32) | NOT NULL | — | envelope schema版本 |  |
| `event_type` | VARCHAR(32) | NOT NULL | — | 事件类型(枚举) |  |
| `action` | VARCHAR(128) | NOT NULL | — | 权限点/操作标识 |  |
| `title` | VARCHAR(256) | NOT NULL | — | 人读操作标题 |  |
| `occurred_at` | DATETIME | NOT NULL | — | 事件发生时刻(UTC,来自envelope) |  |
| `actor_user_id` | BIGINT | NULL | — | 操作者用户ID(快照,无FK) |  |
| `actor_username` | VARCHAR(64) | NULL | — | 操作者用户名(快照) |  |
| `actor_is_super_admin` | BOOL | NOT NULL | — | 操作者是否超管 |  |
| `target_type` | VARCHAR(64) | NULL | — | 作用对象类型 |  |
| `target_id` | VARCHAR(128) | NULL | — | 作用对象ID |  |
| `target_display` | VARCHAR(255) | NULL | — | 作用对象显示名 |  |
| `request_id` | VARCHAR(64) | NULL | — | 请求ID(关联键) |  |
| `trace_id` | VARCHAR(64) | NULL | — | trace ID |  |
| `method` | VARCHAR(16) | NULL | — | HTTP方法 |  |
| `path` | VARCHAR(512) | NULL | — | 请求路径 |  |
| `ip` | VARCHAR(64) | NULL | — | 客户端IP |  |
| `user_agent` | VARCHAR(512) | NULL | — | User-Agent |  |
| `result_status` | VARCHAR(16) | NOT NULL | — | 结果(success/failure/denied) |  |
| `result_http_status` | INTEGER | NULL | — | HTTP状态码 |  |
| `result_error_code` | VARCHAR(128) | NULL | — | 错误码 |  |
| `duration_ms` | INTEGER | NULL | — | 耗时(毫秒) |  |
| `risk_level` | VARCHAR(16) | NOT NULL | — | 风险等级(low/medium/high) |  |
| `metadata` | JSON | NOT NULL | — | 脱敏后业务负载(JSON) |  |
| `redaction_applied` | BOOL | NOT NULL | — | 是否发生过脱敏 |  |
| `payload` | JSON | NOT NULL | — | 完整envelope(无损取证) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE （列级 `unique=True`，DDL 由数据库自动命名）：(event_id)
- INDEX `ix_audit_events_actor_time`：(actor_user_id, occurred_at)
- INDEX `ix_audit_events_occurred_at`：(occurred_at)
- INDEX `ix_audit_events_request_id`：(request_id)
- INDEX `ix_audit_events_result_status`：(result_status)
- INDEX `ix_audit_events_status_time`：(result_status, occurred_at, id)
- INDEX `ix_audit_events_type_time`：(event_type, occurred_at)

### `configs`

> 来源 model：`admin_platform.domains.config.models.Config`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `name` | VARCHAR(128) | NOT NULL | — | 参数名称 |  |
| `config_key` | VARCHAR(128) | NOT NULL | — | 参数键名(全局唯一) |  |
| `config_value` | TEXT | NOT NULL | — | 参数键值(非敏感运营参数) |  |
| `is_builtin` | BOOL | NOT NULL | `False` | 是否系统内置(内置禁删) |  |
| `remark` | VARCHAR(255) | NULL | — | 备注 |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_configs_key`：(config_key)

### `depts`

> 来源 model：`admin_platform.domains.dept.models.Dept`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `parent_id` | BIGINT | NULL | — | 父部门ID(NULL=根) |  |
| `name` | VARCHAR(64) | NOT NULL | — | 部门名称 |  |
| `code` | VARCHAR(64) | NOT NULL | — | 部门编码 |  |
| `sort_order` | INTEGER | NOT NULL | `0` | 显示顺序 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `leader` | VARCHAR(64) | NULL | — | 负责人 |  |
| `phone` | VARCHAR(32) | NULL | — | 联系电话 |  |
| `email` | VARCHAR(128) | NULL | — | 邮箱 |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_depts_code`：(code)
- FK `None`：(parent_id) → depts.id
- INDEX `ix_depts_parent_sort`：(parent_id, sort_order, id)

### `dict_types`

> 来源 model：`admin_platform.domains.dict.models.DictType`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `name` | VARCHAR(64) | NOT NULL | — | 字典名称 |  |
| `type` | VARCHAR(128) | NOT NULL | — | 字典类型(全局唯一标识，如 sys_user_sex) |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `is_builtin` | BOOL | NOT NULL | `False` | 是否系统内置(内置禁删) |  |
| `remark` | VARCHAR(255) | NULL | — | 备注 |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_dict_types_type`：(type)

### `login_logs`

> 来源 model：`admin_platform.domains.auth.models.LoginLog`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `username` | VARCHAR(64) | NOT NULL | — | 尝试登录的用户名 |  |
| `user_id` | BIGINT | NULL | — | 用户ID(失败/不存在时可空,无FK) |  |
| `status` | VARCHAR(16) | NOT NULL | — | success/failure/locked/rate_limited/captcha_required |  |
| `reason_code` | VARCHAR(64) | NULL | — | 失败原因码(error_code) |  |
| `ip` | VARCHAR(64) | NULL | — | 客户端IP |  |
| `user_agent` | VARCHAR(512) | NULL | — | User-Agent |  |
| `request_id` | VARCHAR(64) | NULL | — | 请求ID(关联audit_events) |  |
| `login_at_utc` | DATETIME | NOT NULL | — | 登录尝试时刻(UTC) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- INDEX `ix_login_logs_login_at`：(login_at_utc)
- INDEX `ix_login_logs_status`：(status)
- INDEX `ix_login_logs_status_time`：(status, login_at_utc, id)
- INDEX `ix_login_logs_user_time`：(user_id, login_at_utc)
- INDEX `ix_login_logs_username_time`：(username, login_at_utc)

### `menus`

> 来源 model：`admin_platform.domains.menu.models.Menu`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `parent_id` | BIGINT | NULL | — | 父菜单ID(NULL=根) |  |
| `name` | VARCHAR(64) | NOT NULL | — | 菜单名称 |  |
| `menu_type` | VARCHAR(8) | NOT NULL | — | 类型(M目录/C菜单/F按钮) |  |
| `path` | VARCHAR(255) | NOT NULL | `''` | 路由地址(按钮类可空串) |  |
| `component` | VARCHAR(255) | NULL | — | 前端组件路径(目录/按钮可空) |  |
| `perms` | VARCHAR(128) | NULL | — | 权限标识(如system:user:list,目录类可空) |  |
| `icon` | VARCHAR(64) | NOT NULL | `''` | 菜单图标 |  |
| `sort_order` | INTEGER | NOT NULL | `0` | 显示顺序 |  |
| `visible` | BOOL | NOT NULL | `True` | 是否显示(False=侧边栏隐藏) |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `seed_key` | VARCHAR(128) | NULL | — | seed稳定键(非空=内置菜单,NULL=用户自建) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- FK `None`：(parent_id) → menus.id
- INDEX `ix_menus_parent_sort`：(parent_id, sort_order, id)
- INDEX UNIQUE `uq_menus_seed_key`：(seed_key)

### `notices`

> 来源 model：`admin_platform.domains.notice.models.Notice`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `title` | VARCHAR(128) | NOT NULL | — | 公告标题 |  |
| `notice_type` | VARCHAR(16) | NOT NULL | — | 公告类型(notification/announcement) |  |
| `content` | TEXT | NOT NULL | — | 公告内容(富文本，渲染期需净化) |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `remark` | VARCHAR(255) | NULL | — | 备注 |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- INDEX `ix_notices_type_status`：(notice_type, status)

### `posts`

> 来源 model：`admin_platform.domains.post.models.Post`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `name` | VARCHAR(64) | NOT NULL | — | 岗位名称 |  |
| `code` | VARCHAR(64) | NOT NULL | — | 岗位编码 |  |
| `sort_order` | INTEGER | NOT NULL | `0` | 显示顺序 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_posts_code`：(code)

### `roles`

> 来源 model：`admin_platform.domains.role.models.Role`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `name` | VARCHAR(64) | NOT NULL | — | 角色名称 |  |
| `code` | VARCHAR(64) | NOT NULL | — | 角色编码 |  |
| `data_scope` | VARCHAR(32) | NOT NULL | `'self'` | 数据权限范围(ScopeType值) |  |
| `sort_order` | INTEGER | NOT NULL | `0` | 显示顺序 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_roles_code`：(code)

### `scheduled_tasks`

> 来源 model：`admin_platform.domains.scheduled_task.models.ScheduledTask`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `name` | VARCHAR(128) | NOT NULL | — | 任务名称(唯一) |  |
| `handler_key` | VARCHAR(128) | NOT NULL | — | 处理器键(命中代码侧registry,非任意调用目标) |  |
| `params_json` | JSON | NOT NULL | `(JSON_OBJECT())` (DB) | 处理器参数(JSON) |  |
| `cron_expression` | VARCHAR(128) | NOT NULL | — | cron表达式(5字段标准crontab,经校验) |  |
| `cron_timezone` | VARCHAR(64) | NOT NULL | `'Asia/Shanghai'` (DB) | cron解释时区(库时间存UTC) |  |
| `status` | VARCHAR(16) | NOT NULL | `'disabled'` (DB) | 状态(enabled/disabled) |  |
| `allow_concurrent` | BOOL | NOT NULL | `0` (DB) | 是否允许上次未跑完时并发执行 |  |
| `misfire_grace_seconds` | INTEGER | NOT NULL | `300` (DB) | 错过触发的宽限秒数 |  |
| `timeout_seconds` | INTEGER | NULL | — | 单次执行超时秒数(空=不限) |  |
| `last_run_at` | DATETIME | NULL | — | 最近一次执行时刻(UTC) |  |
| `last_status` | VARCHAR(16) | NULL | — | 最近一次执行结果状态 |  |
| `remark` | VARCHAR(255) | NULL | — | 备注 |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_scheduled_tasks_name`：(name)
- INDEX `ix_scheduled_tasks_handler_key`：(handler_key)
- INDEX `ix_scheduled_tasks_status`：(status)

### `dict_data`

> 来源 model：`admin_platform.domains.dict.models.DictData`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `dict_type_id` | BIGINT | NOT NULL | — | 字典类型ID(关联 dict_types.id) |  |
| `label` | VARCHAR(128) | NOT NULL | — | 字典标签(显示文本) |  |
| `value` | VARCHAR(128) | NOT NULL | — | 字典键值 |  |
| `sort_order` | INTEGER | NOT NULL | `0` | 显示顺序 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `is_default` | BOOL | NOT NULL | `False` | 是否默认(同类型仅一条) |  |
| `default_unique_key` | INTEGER | NULL | `GENERATED ALWAYS AS (CASE WHEN is_default = 1 THEN 1 ELSE NULL END) STORED` (DB) | MySQL生成列: is_default=true时为1,否则NULL |  |
| `css_class` | VARCHAR(128) | NULL | — | 前端样式(CSS class) |  |
| `remark` | VARCHAR(255) | NULL | — | 备注 |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_dict_data_type_value`：(dict_type_id, value)
- FK `fk_dict_data_type_id`：(dict_type_id) → dict_types.id
- INDEX `ix_dict_data_type_sort`：(dict_type_id, sort_order, id)
- INDEX UNIQUE `uq_dict_data_one_default_per_type`：(dict_type_id, default_unique_key)

### `role_depts`

> 来源 model：`admin_platform.domains.role.models.RoleDept`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `role_id` | BIGINT | NOT NULL | — | 角色ID |  |
| `dept_id` | BIGINT | NOT NULL | — | 部门ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_role_depts`：(role_id, dept_id)
- FK `None`：(dept_id) → depts.id
- FK `None`：(role_id) → roles.id
- INDEX `ix_role_depts_dept`：(dept_id)
- INDEX `ix_role_depts_role`：(role_id)

### `role_menus`

> 来源 model：`admin_platform.domains.menu.models.RoleMenu`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `role_id` | BIGINT | NOT NULL | — | 角色ID |  |
| `menu_id` | BIGINT | NOT NULL | — | 菜单ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_role_menus`：(role_id, menu_id)
- FK `None`：(menu_id) → menus.id
- FK `None`：(role_id) → roles.id
- INDEX `ix_role_menus_menu`：(menu_id)
- INDEX `ix_role_menus_role`：(role_id)

### `scheduled_task_logs`

> 来源 model：`admin_platform.domains.scheduled_task.models.ScheduledTaskLog`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `task_id` | BIGINT | NULL | — | 所属任务ID(任务删后置空,保留历史) |  |
| `execution_id` | CHAR(32) | NOT NULL | — | 执行唯一标识(UUID) |  |
| `trigger_type` | VARCHAR(16) | NOT NULL | — | 触发方式(schedule自动/manual手动) |  |
| `scheduled_at` | DATETIME | NULL | — | 计划触发时刻(UTC,自动触发用于claim去重) |  |
| `schedule_claim_scheduled_at` | DATETIME | NULL | `GENERATED ALWAYS AS (CASE WHEN trigger_type = 'schedule' THEN scheduled_at ELSE NULL END) STORED` (DB) | MySQL生成列: 自动触发claim计划时间, manual为NULL |  |
| `handler_key` | VARCHAR(128) | NOT NULL | — | 处理器键(快照) |  |
| `params_json` | JSON | NOT NULL | `(JSON_OBJECT())` (DB) | 执行参数快照(JSON) |  |
| `status` | VARCHAR(16) | NOT NULL | — | 执行状态 |  |
| `started_at` | DATETIME | NULL | — | 开始执行时刻(UTC) |  |
| `finished_at` | DATETIME | NULL | — | 结束时刻(UTC) |  |
| `duration_ms` | INTEGER | NULL | — | 执行耗时(毫秒) |  |
| `error_code` | VARCHAR(128) | NULL | — | 失败错误码 |  |
| `error_message` | VARCHAR(1024) | NULL | — | 失败信息(截断,禁写密钥) |  |
| `result_summary` | VARCHAR(1024) | NULL | — | 成功结果摘要 |  |
| `worker_id` | VARCHAR(128) | NULL | — | 执行所在worker标识 |  |
| `actor_user_id` | BIGINT | NULL | — | 手动触发操作者用户ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE （列级 `unique=True`，DDL 由数据库自动命名）：(execution_id)
- FK `None`：(task_id) → scheduled_tasks.id
- INDEX `ix_scheduled_task_logs_status_created`：(status, created_at)
- INDEX `ix_scheduled_task_logs_task_started`：(task_id, started_at)
- INDEX UNIQUE `uq_scheduled_task_logs_schedule_claim`：(task_id, schedule_claim_scheduled_at)

### `users`

> 来源 model：`admin_platform.domains.user.models.User`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `username` | VARCHAR(64) | NOT NULL | — | 用户名 |  |
| `password_hash` | VARCHAR(255) | NOT NULL | — | 密码哈希 |  |
| `nickname` | VARCHAR(64) | NOT NULL | `''` | 昵称 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态 |  |
| `is_super_admin` | BOOL | NOT NULL | `False` | 是否超级管理员 |  |
| `super_admin_unique_key` | INTEGER | NULL | `GENERATED ALWAYS AS (CASE WHEN is_super_admin = 1 THEN 1 ELSE NULL END) STORED` (DB) | MySQL生成列: is_super_admin=true时为1,否则NULL |  |
| `dept_id` | BIGINT | NULL | — | 所属部门ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_users_username`：(username)
- FK `None`：(dept_id) → depts.id
- INDEX `ix_users_dept_id`：(dept_id)
- INDEX UNIQUE `uq_users_one_super_admin`：(super_admin_unique_key)

### `auth_refresh_tokens`

> 来源 model：`admin_platform.domains.auth.models.RefreshToken`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `jti` | CHAR(32) | NOT NULL | — | 当前token标识(UUID) |  |
| `family_id` | CHAR(32) | NOT NULL | — | 轮换链family(一次登录=一family) |  |
| `user_id` | BIGINT | NOT NULL | — | 所属用户ID |  |
| `token_hash` | VARCHAR(64) | NOT NULL | — | HMAC-SHA256(pepper,secret)的hex(不存明文) |  |
| `rotated_to_jti` | CHAR(32) | NULL | — | 轮换后继jti(非空=已被轮换,再用即reuse) |  |
| `revoked_at` | DATETIME | NULL | — | 撤销时间(非空=已撤销) |  |
| `revoked_reason` | VARCHAR(32) | NULL | — | 撤销原因(rotated/logout/reuse_detected/concurrency_limit/expired_cleanup) |  |
| `issued_at` | DATETIME | NOT NULL | — | 签发时间(UTC) |  |
| `expires_at` | DATETIME | NOT NULL | — | 过期时间(UTC,min(idle,family_absolute)) |  |
| `family_absolute_at` | DATETIME | NOT NULL | — | family绝对过期上限(UTC,首登锚定,轮换透传不随清理漂移) |  |
| `last_used_at` | DATETIME | NULL | — | 最后轮换时间(UTC) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE （列级 `unique=True`，DDL 由数据库自动命名）：(jti)
- UNIQUE （列级 `unique=True`，DDL 由数据库自动命名）：(token_hash)
- FK `None`：(user_id) → users.id
- INDEX `ix_auth_refresh_tokens_expires_at`：(expires_at)
- INDEX `ix_auth_refresh_tokens_family`：(family_id)
- INDEX `ix_auth_refresh_tokens_user_active`：(user_id, revoked_at, expires_at)
- INDEX `ix_auth_refresh_tokens_user_family`：(user_id, family_id)

### `files`

> 来源 model：`admin_platform.domains.file.models.File`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `object_key` | VARCHAR(64) | NOT NULL | — | 存储对象键(uuid4 hex，不含原文件名，防穿越/覆盖) |  |
| `storage_backend` | VARCHAR(32) | NOT NULL | — | 存储后端(local/s3) |  |
| `original_filename` | VARCHAR(255) | NOT NULL | — | 原始文件名(仅展示/下载用，不信任) |  |
| `content_type` | VARCHAR(128) | NOT NULL | — | 声明MIME类型(校验后落库) |  |
| `size_bytes` | BIGINT | NOT NULL | — | 文件字节数(实际写入量) |  |
| `sha256` | VARCHAR(64) | NOT NULL | — | 内容SHA256(完整性校验) |  |
| `uploader_id` | BIGINT | NOT NULL | — | 上传者用户ID |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/deleted) |  |
| `deleted_at` | DATETIME | NULL | — | 软删时间(NULL=未删) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_files_object_key`：(object_key)
- FK `fk_files_uploader_id`：(uploader_id) → users.id
- INDEX `ix_files_sha256`：(sha256)
- INDEX `ix_files_status_created`：(status, created_at)
- INDEX `ix_files_uploader_id`：(uploader_id)

### `user_posts`

> 来源 model：`admin_platform.domains.post.models.UserPost`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `user_id` | BIGINT | NOT NULL | — | 用户ID |  |
| `post_id` | BIGINT | NOT NULL | — | 岗位ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_user_posts`：(user_id, post_id)
- FK `None`：(post_id) → posts.id
- FK `None`：(user_id) → users.id
- INDEX `ix_user_posts_post`：(post_id)
- INDEX `ix_user_posts_user`：(user_id)

### `user_roles`

> 来源 model：`admin_platform.domains.role.models.UserRole`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `user_id` | BIGINT | NOT NULL | — | 用户ID |  |
| `role_id` | BIGINT | NOT NULL | — | 角色ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 创建时间(UTC) |  |
| `updated_at` | DATETIME | NOT NULL | `CURRENT_TIMESTAMP` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_user_roles`：(user_id, role_id)
- FK `None`：(role_id) → roles.id
- FK `None`：(user_id) → users.id
- INDEX `ix_user_roles_role`：(role_id)
- INDEX `ix_user_roles_user`：(user_id)
