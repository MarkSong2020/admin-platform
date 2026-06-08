# 数据模型速览（DATA_MODEL）

> ⚠️ **生成物，请勿手改。** 本文件由 `scripts/dump_schema.py` 从 ORM models 自省生成。
> **真相源 = `src/admin_platform/domains/*/models.py` + `db/base.py`（公共列/mixin）**；
> 物化 DDL 见 `migrations/versions/`。改表结构 → 改 models + 迁移 → `make schema-doc` 重生本文件。
>
> - 再生：`make schema-doc`（= `uv run python scripts/dump_schema.py`）
> - 校验是否最新：`uv run python scripts/dump_schema.py --check`（差异即非零退出）
> - 类型以 PostgreSQL 方言渲染；models↔迁移↔活库的漂移由 `make check-db` 守门。

## 表清单

- [`depts`](#depts)（11 列）
- [`menus`](#menus)（13 列）
- [`posts`](#posts)（7 列）
- [`roles`](#roles)（8 列）
- [`role_depts`](#role_depts)（5 列）
- [`role_menus`](#role_menus)（5 列）
- [`users`](#users)（9 列）
- [`user_posts`](#user_posts)（5 列）
- [`user_roles`](#user_roles)（5 列）

## 表结构

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
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_depts_code`：(code)
- FK `None`：(parent_id) → depts.id
- INDEX `ix_depts_parent_sort`：(parent_id, sort_order, id)

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
| `visible` | BOOLEAN | NOT NULL | `True` | 是否显示(False=侧边栏隐藏) |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- FK `None`：(parent_id) → menus.id
- INDEX `ix_menus_parent_sort`：(parent_id, sort_order, id)

### `posts`

> 来源 model：`admin_platform.domains.post.models.Post`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `name` | VARCHAR(64) | NOT NULL | — | 岗位名称 |  |
| `code` | VARCHAR(64) | NOT NULL | — | 岗位编码 |  |
| `sort_order` | INTEGER | NOT NULL | `0` | 显示顺序 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态(active/disabled) |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

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
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_roles_code`：(code)

### `role_depts`

> 来源 model：`admin_platform.domains.role.models.RoleDept`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `role_id` | BIGINT | NOT NULL | — | 角色ID |  |
| `dept_id` | BIGINT | NOT NULL | — | 部门ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_role_depts`：(role_id, dept_id)
- FK `None`：(role_id) → roles.id
- FK `None`：(dept_id) → depts.id
- INDEX `ix_role_depts_dept`：(dept_id)
- INDEX `ix_role_depts_role`：(role_id)

### `role_menus`

> 来源 model：`admin_platform.domains.menu.models.RoleMenu`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `role_id` | BIGINT | NOT NULL | — | 角色ID |  |
| `menu_id` | BIGINT | NOT NULL | — | 菜单ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_role_menus`：(role_id, menu_id)
- FK `None`：(role_id) → roles.id
- FK `None`：(menu_id) → menus.id
- INDEX `ix_role_menus_menu`：(menu_id)
- INDEX `ix_role_menus_role`：(role_id)

### `users`

> 来源 model：`admin_platform.domains.user.models.User`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `username` | VARCHAR(64) | NOT NULL | — | 用户名 |  |
| `password_hash` | VARCHAR(255) | NOT NULL | — | 密码哈希 |  |
| `nickname` | VARCHAR(64) | NOT NULL | `''` | 昵称 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态 |  |
| `is_super_admin` | BOOLEAN | NOT NULL | `False` | 是否超级管理员 |  |
| `dept_id` | BIGINT | NULL | — | 所属部门ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_users_username`：(username)
- FK `None`：(dept_id) → depts.id
- INDEX `ix_users_dept_id`：(dept_id)
- INDEX UNIQUE `uq_users_one_super_admin`：(is_super_admin)

### `user_posts`

> 来源 model：`admin_platform.domains.post.models.UserPost`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `user_id` | BIGINT | NOT NULL | — | 用户ID |  |
| `post_id` | BIGINT | NOT NULL | — | 岗位ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_user_posts`：(user_id, post_id)
- FK `None`：(user_id) → users.id
- FK `None`：(post_id) → posts.id
- INDEX `ix_user_posts_post`：(post_id)
- INDEX `ix_user_posts_user`：(user_id)

### `user_roles`

> 来源 model：`admin_platform.domains.role.models.UserRole`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `user_id` | BIGINT | NOT NULL | — | 用户ID |  |
| `role_id` | BIGINT | NOT NULL | — | 角色ID |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_user_roles`：(user_id, role_id)
- FK `None`：(user_id) → users.id
- FK `None`：(role_id) → roles.id
- INDEX `ix_user_roles_role`：(role_id)
- INDEX `ix_user_roles_user`：(user_id)
