# 数据建模标准 —— admin-platform

> **基线继承模板** `python-web-service-template doc/standards/DATA_MODELING.md`：id / created_at / updated_at / 列级 comment / 枚举 / FK / comment 门禁规则**全部沿用**。
>
> **2026-06-05 单租户回归**：原「多租户追加」（`tenant_id` / `TenantMixin` / 软删除×租户联动）已随 P0.9 拆除（见 [`../architecture/MULTI_TENANCY.md`](../architecture/MULTI_TENANCY.md) 废弃说明）。本仓数据建模现**全部沿用模板基线，无追加**。
>
> 区分：本文是**建模标准**（怎么设计）；当前 schema 速览（生成物，从 models 自省）见 [../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md)。

## 现状

- ✅ `IdMixin` / `TimestampMixin` 落地（`db/base.py`，与模板同款）
- ✅ `users` 采用 mixin：BIGINT `id` + `created_at` / `updated_at`（timestamptz、均带中文 comment）；迁移 `0002_users`
- ✅ 全列中文 comment 回填；迁移同步（`make check-db` 比对 comment 零漂移）
- ✅ comment 门禁 `tests/unit/test_column_comments.py`（自动发现 domain），与模板同款
- ✅ schema 速览 `scripts/dump_schema.py` 渲染列 comment

## 后续（P1 RBAC 数据建模）

角色 / 菜单 / 部门 / 岗位 + 数据权限的表设计见 [RuoYi 对标路线图](../specs/2026-06-04-ruoyi-parity-roadmap.md) §5；具体表结构 P1 实现时拉 Codex PK 设计，仍走本基线（IdMixin / 命名规范 / comment 门禁）。

## 引用

- 基线标准 → 模板 `doc/standards/DATA_MODELING.md`
- 当前 schema 速览（生成物）→ [../architecture/DATA_MODEL.md](../architecture/DATA_MODEL.md)
