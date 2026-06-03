# 数据模型速览（DATA_MODEL）

> ⚠️ **生成物，请勿手改。** 本文件由 `scripts/dump_schema.py` 从 ORM models 自省生成。
> **真相源 = `src/admin_platform/domains/*/models.py` + `db/base.py`（公共列/mixin）**；
> 物化 DDL 见 `migrations/versions/`。改表结构 → 改 models + 迁移 → `make schema-doc` 重生本文件。
>
> - 再生：`make schema-doc`（= `uv run python scripts/dump_schema.py`）
> - 校验是否最新：`uv run python scripts/dump_schema.py --check`（差异即非零退出）
> - 类型以 PostgreSQL 方言渲染；models↔迁移↔活库的漂移由 `make check-db` 守门。

## 表清单

- [`tenants`](#tenants)（平台级，5 列）
- [`users`](#users)（租户隔离，8 列）

## 表结构

### `tenants`

> 来源 model：`admin_platform.domains.tenant.models.Tenant` —— 平台级表（不继承 `TenantMixin`）

| 列 | 类型 | 空 | 默认 | 备注 |
|---|---|---|---|---|
| `id` | BIGINT | NOT NULL | — | PK |
| `code` | VARCHAR(64) | NOT NULL | — |  |
| `name` | VARCHAR(128) | NOT NULL | — |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) |  |

约束 / 索引：

- UNIQUE （列级 `unique=True`，DDL 由 PG 自动命名）：(code)

### `users`

> 来源 model：`admin_platform.domains.user.models.User` —— 多租户业务表（继承 `TenantMixin`，受租户隔离过滤）

| 列 | 类型 | 空 | 默认 | 备注 |
|---|---|---|---|---|
| `id` | BIGINT | NOT NULL | — | PK |
| `username` | VARCHAR(64) | NOT NULL | — |  |
| `password_hash` | VARCHAR(255) | NOT NULL | — |  |
| `nickname` | VARCHAR(64) | NOT NULL | `''` |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` |  |
| `is_platform_admin` | BOOLEAN | NOT NULL | `False` |  |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) |  |
| `tenant_id` | BIGINT | NOT NULL | — |  |

约束 / 索引：

- UNIQUE `uq_users_tenant_username`：(tenant_id, username)
- FK `fk_users_tenant_id`：(tenant_id) → tenants.id
- INDEX `ix_users_tenant_id`：(tenant_id)
