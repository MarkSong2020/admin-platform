# 数据建模标准 —— admin-platform 多租户追加

> **基线继承模板** `python-web-service-template doc/standards/DATA_MODELING.md`：id / created_at / updated_at / 列级 comment / 枚举 / FK / comment 门禁规则**全部沿用**，本文只追加**多租户专属**部分。
>
> 区分：本文是**建模标准**（怎么设计）；当前 schema 速览（生成物，从 models 自省）见 [../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md)。

## 多租户基线（本仓所有业务表）

- **`tenant_id`**：`BigInteger`，由 [`TenantMixin`](../../src/admin_platform/db/base.py) 提供（`index=True, nullable=False`）
  - 复合索引 / 唯一约束**以 `tenant_id` 打头**（如 `uq(tenant_id, username)`）
  - 隔离由 `db/tenant_filter.py` 的 ORM 事件 **fail-closed** 自动注入：无上下文抛 `TenantContextMissing`，有上下文只见本租户行，`system` / 平台超管显式 bypass。业务代码**不手写** `WHERE tenant_id =`
  - **平台级表**（如 `tenants` 注册表）**不**继承 `TenantMixin`、不带 `tenant_id`（它是隔离边界的另一侧）
  - 未来 RLS（Task 12）在 DB 侧再加一层纵深
- **`tenant_id` 类型 = `tenants.id` 类型**（都 `BIGINT`）；FK `tenant_id → tenants` 用 `ON DELETE RESTRICT`（删租户前先清子表）

## 软删除 × 租户隔离联动（opt-in）

- 用模板 `SoftDeleteMixin` 时，**部分唯一索引必须含 `tenant_id`**：`uq(...) WHERE deleted_at IS NULL`（同租户内唯一、跨租户可重、软删后可复用）
- 软删除过滤可复用 `tenant_filter` 同款 `do_orm_execute` 事件（同一 fail-closed 机制，别每查询手写）

## 现状（vs 模板目标）

- ✅ `TenantMixin` 已落地（`db/base.py:35`）
- ✅ 现有 `tenants` / `users` 用 `created_at`（符合模板裁决）
- ⏳ `IdMixin` / `TimestampMixin` 同模板待建；`updated_at` 待补（随模板 mixin 落地，migration 0003，下一阶段）
- ⏳ 列级 / 表级 `comment` 待回填；comment pytest 门禁待加

## 引用

- 基线标准 → 模板 `doc/standards/DATA_MODELING.md`
- 隔离机制 → [`db/tenant_filter.py`](../../src/admin_platform/db/tenant_filter.py) + [ADR-A/E](../specs/2026-06-02-p0-multitenant-auth-foundation.md)
- 当前 schema 速览（生成物）→ [../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md)
