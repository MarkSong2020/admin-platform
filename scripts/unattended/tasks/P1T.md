# 任务 P1T：post 岗位域 + user_posts 关联

无人值守实现 agent。**只做本任务，完成后停**。严格遵守 `CLAUDE.md` + `doc/standards/AI_CODING_RULES.md`（五层分层、中文 docstring、type hints、不引新依赖）。先读 spec `docs/specs/2026-06-05-p1.0-rbac-mechanism.md` §7（表结构方向）+ §12.5。参考 `domains/role`（**关联表 user_roles + set_user_roles advisory lock 全量替换 + 守卫 api + code 唯一 + service AppError**，post 与 role 几乎同构但**无 data_scope / 无 provider**，更简单）、`tests/integration/test_role_crud.py`（auth override + 超管/非超管 stub 模式）。

## 范围（post 是最简单的扁平域：CRUD + 一个关联表，无树、无 data_scope、无 provider）

**本任务做**：post 五层 + user_posts 关联 + post CRUD API（带 require_permission 守卫）+ 测试。
**本任务不做（headless 无权限，列完成报告「人值守接线」）**：`.importlinter` C1 纳 menu... 纳 post；`main.py` 挂 post_router。

## models.py（posts + user_posts 关联）

`posts`（岗位，扁平，无树）：
- `name` String(64)（岗位名称）。
- `code` String(64) uq（岗位编码，全局唯一；注册 `register_unique_constraint("uq_posts_code","post.CODE_DUPLICATE","Post code already exists")`，镜像 role/models.py）。
- `sort_order` int default 0（显示顺序）。
- `status` String(16) default "active" + CheckConstraint active/disabled（与 schemas Literal 对齐）。
- 全列中文 comment（门禁 `tests/unit/test_column_comments.py`）。

`user_posts`（关联，IdMixin 代理键 + 复合唯一，**镜像 role 域 user_roles**）：
- `user_id` FK users.id ondelete CASCADE、`post_id` FK posts.id ondelete CASCADE，复合唯一 `uq_user_posts`，两列各加索引。

## repository.py

- post 标准 CRUD（参考 role：list_paginated、count、get、find_by_code、create、update（Errata #7 refresh）、delete）。
- `list_posts_for_user(user_id) -> list[Post]`（JOIN user_posts）。
- `set_user_posts(user_id, post_ids)`（全量替换，**先取 advisory lock 再先删后插**，镜像 role 域 set_user_roles 的 F3 修复 —— 用不同 advisory key）。

## schemas / api

- `PostCreate/Update/Read/Page`（name/code/sort_order/status；status 用 `Literal`，**镜像 RoleCreate/Update/Read/Page**）。
- api：post CRUD + `require_permission("system:post:list/query/add/edit/remove")` 守卫（`Annotated[..,Depends]` 守 B008）+ 错误响应 `responses=` 声明（401/403/404 NOT_FOUND/409 CODE_DUPLICATE）。**镜像 role/api.py**。

## service.py

- post CRUD（抛 AppError，错误码 `post.*`：NOT_FOUND / CODE_DUPLICATE）。code 全局唯一预检（create + update 改 code 时），镜像 role service。**无树、无 data_scope**。

## migration

- `make new-module name=post with-model=1`（五层骨架 + patch env.py）。
- `uv run alembic revision --autogenerate -m "p1_posts"`，**人工 review**：posts 表 + user_posts + 索引 + uq + CheckConstraint 齐全；清掉 autogenerate 残留（沿用 0005/0006 经验：手写干净 migration，文件名 `0007_p1_posts.py`，down_revision=`0006`）。
  - ⚠️ 若运行时 head 不是 0006（ME1 未落），用 `uv run alembic heads` 确认当前 head 作 down_revision。

## 测试

- 单元（stub repo）：post CRUD、code 重复 409、user_posts 绑定 set/list。
- 集成（真 DB，auth override 参考 test_role_crud）：post CRUD 端到端 + code 重复 409 + NOT_FOUND 404 + 权限矩阵 5 端点 403（非超管默认 deny）+ 超管短路放行 + set_user_posts/list_posts_for_user 绑定正确 + 并发 set_user_posts last-writer-wins（advisory lock，镜像 role F3 测试）。

## ⚠️ 人值守接线（你没权限改，完成报告里列出）

1. `.importlinter` C1 containers 纳 `admin_platform.domains.post`。
2. `main.py` 挂 post_router。

## 完成判据

- `make check` + `make migrate` + `make check-db`（零漂移）+ `make test-integration` 全绿。
- 完成报告列出「人值守接线」清单。

完成后停。
