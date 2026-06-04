# 数据模型速览（DATA_MODEL）

> ⚠️ **生成物，请勿手改。** 本文件由 `scripts/dump_schema.py` 从 ORM models 自省生成。
> **真相源 = `src/admin_platform/domains/*/models.py` + `db/base.py`（公共列/mixin）**；
> 物化 DDL 见 `migrations/versions/`。改表结构 → 改 models + 迁移 → `make schema-doc` 重生本文件。
>
> - 再生：`make schema-doc`（= `uv run python scripts/dump_schema.py`）
> - 校验是否最新：`uv run python scripts/dump_schema.py --check`（差异即非零退出）
> - 类型以 PostgreSQL 方言渲染；models↔迁移↔活库的漂移由 `make check-db` 守门。

## 表清单

- [`users`](#users)（8 列）

## 表结构

### `users`

> 来源 model：`admin_platform.domains.user.models.User`

| 列 | 类型 | 空 | 默认 | 描述 | 备注 |
|---|---|---|---|---|---|
| `username` | VARCHAR(64) | NOT NULL | — | 用户名 |  |
| `password_hash` | VARCHAR(255) | NOT NULL | — | 密码哈希 |  |
| `nickname` | VARCHAR(64) | NOT NULL | `''` | 昵称 |  |
| `status` | VARCHAR(16) | NOT NULL | `'active'` | 状态 |  |
| `is_super_admin` | BOOLEAN | NOT NULL | `False` | 是否超级管理员 |  |
| `id` | BIGINT | NOT NULL | — | 主键 | PK |
| `created_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 创建时间(UTC) |  |
| `updated_at` | TIMESTAMP WITH TIME ZONE | NOT NULL | `now()` (DB) | 更新时间(UTC, ORM flush 触发) |  |

约束 / 索引：

- UNIQUE `uq_users_username`：(username)
