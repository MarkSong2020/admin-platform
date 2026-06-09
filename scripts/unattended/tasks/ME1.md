# 任务 ME1：menu 菜单域（目录/菜单/按钮 + perms）+ role_menus + getRouters payload + DbMenuProvider

无人值守实现 agent。**只做本任务，完成后停**。严格遵守 `CLAUDE.md` + `doc/standards/AI_CODING_RULES.md`（五层分层、中文 docstring、type hints、不引新依赖）。先读 spec `docs/specs/2026-06-05-p1.0-rbac-mechanism.md` §6.1（前端契约 getRouters 必冻字段）+ §7（表结构方向）+ §12.4 + §13.2（权限 registry，**仅需了解，本任务不建 registry**）。参考 `domains/dept`（**邻接表树 + 递归/内存建树 + advisory lock + status + 防环 + RESTRICT 删**，菜单树几乎同构）、`domains/role`（关联表 user_roles/role_depts + provider 模式 + 守卫 api）、`tests/integration/test_dept_crud.py`（auth override + data_scope stub 模式）。

## 范围边界（重要 —— 本任务只做菜单域骨架，跨域/核心集成留人值守）

**本任务做**：menu 五层 + role_menus 关联 + DbMenuProvider（getRouters 数据源）+ getRouters payload 纯函数 + menu CRUD API（带 require_permission 守卫）+ 测试。

**本任务不做（headless 无权限改 core/main + 安全关键，列入完成报告「人值守接线」）**：
- §13.2 权限点 registry（core/跨域常量模块 + 三集合机检）。
- `DbPermissionProvider.get_user_permissions` 从 menu.perms 真实派生（在 role 域 provider，安全关键，人值守 + Codex 审后改）。
- `core` 加 `get_menu_provider` 注入点 + `main.py` 挂 menu_router + override MenuProvider。
- getInfo / `/menus/routers` HTTP 端点最终接线（§6 打通阶段）。

但**你要为这些预留接口**：menu repository 提供 `list_perms_for_user` / `list_menu_ids_for_user` / `set_role_menus`；DbMenuProvider 实现 `get_user_menu_tree`。

## models.py（menus + role_menus 关联）

`menus`（菜单树，邻接表，**镜像 dept 树存储**）：
- `parent_id` int|None，FK `menus.id` `ondelete=RESTRICT`（有子菜单禁删父，service 友好 409 `menu.HAS_CHILDREN`）。
- `name` String(64)（菜单/目录/按钮名称）。
- `menu_type` String(8)，CheckConstraint 限 `('M','C','F')`（M=目录 / C=菜单 / F=按钮，对标若依 sys_menu）。
- `path` String(255) default ""（路由地址；按钮类可空串）。
- `component` String(255) nullable（前端组件路径；目录/按钮可 None）。
- `perms` String(128) nullable（权限标识，如 `system:user:list`；目录类 / 纯展示可 None）。
- `icon` String(64) default ""（图标）。
- `sort_order` int default 0（显示顺序，若依 order_num）。
- `visible` bool default True（是否在侧边栏显示；False = getRouters `hidden=true`）。
- `status` String(16) default "active" + CheckConstraint active/disabled（停用菜单不下发）。
- 防自环 CheckConstraint `parent_id IS NULL OR parent_id <> id`；复合索引 `ix_menus_parent_sort(parent_id, sort_order, id)`。
- 全列中文 comment（门禁 `tests/unit/test_column_comments.py`）。
- `code` 若依无、菜单不需要业务唯一编码 —— **不加 code/uq**（与 dept/role 不同，菜单靠 id + 树结构）。

`role_menus`（关联，IdMixin 代理键 + 复合唯一，镜像 role_depts）：
- `role_id` FK roles.id ondelete CASCADE、`menu_id` FK menus.id ondelete CASCADE，复合唯一 `uq_role_menus`，两列各加索引。

## repository.py

- menu 标准 CRUD（参考 dept：select 风格、count、get）。**无 find_by_code**（菜单无 code）。
- 树：`list_descendant_menu_ids(menu_id)` 递归 CTE（删父防有子 + 防环复用，镜像 dept）；`count_children(menu_id)`。
- `acquire_tree_lock()` advisory lock（镜像 dept，**用不同 key**，菜单树写串行化防并发成环）。
- **供人值守集成预留**：
  - `list_menu_ids_for_user(user_id) -> frozenset[int]`（JOIN user_roles→role_menus，该用户经角色可见的菜单 id 集；只取 status=active 角色 —— 复用 role 域 `list_roles_for_user` 的 active 过滤思路，可 JOIN roles 加 `roles.status='active'`）。
  - `list_perms_for_user(user_id) -> frozenset[str]`（同上 JOIN 取 `menus.perms` 非空、menus.status=active 的集合 —— 供 `get_user_permissions` 派生）。
  - `set_role_menus(role_id, menu_ids)`（全量替换，**先取 advisory lock 再先删后插**，镜像 role 域 set_user_roles 的 F3 修复）。
  - `list_all_active() -> list[Menu]` + `list_active_by_ids(ids) -> list[Menu]`（供 DbMenuProvider 建树：超管取全部 active，非超管取可见 id 的 active）。

## DbMenuProvider（menu 域，实现 authz.MenuProvider）

新文件 `src/admin_platform/domains/menu/provider.py`。`class DbMenuProvider(MenuProvider)`，**同步接口经 `anyio.from_thread.run` 桥到 async 内核**（镜像 role 域 `DbPermissionProvider` 的 sync→async 桥，读其 docstring 照搬模式）：
- `get_user_menu_tree(user_id) -> list[MenuNode]`：超管（查 users.is_super_admin AND status=active，复用 role provider 思路）→ 全部 active 菜单建树；否则 → `list_menu_ids_for_user` 的可见 active 菜单建树。建树 = 把扁平菜单按 parent_id 组装成 `authz.providers.MenuNode`（id/name/path/perms/children），按 sort_order 排序。停用菜单（status!=active）不下发。
- `invalidate_*`：no-op（P1 不缓存）。
- 异步内核 `a_get_user_menu_tree` 可直接 await 单测。

## getRouters payload 纯函数（§6.1 必冻字段）

新文件 `src/admin_platform/domains/menu/routers.py`（或 schemas 内）：纯函数 `build_routers(tree: list[MenuNode]) -> list[dict]`，把 MenuNode 树转成前端动态路由 payload。**必冻字段**（§6.1）：`name / path / component / redirect / hidden / alwaysShow / meta`，`meta` 含 `title / icon / noCache / link`。映射规则参考若依：目录无 component → `Layout`；hidden = not visible；meta.title = 菜单 name；meta.icon = icon。按钮类（menu_type=F）不进路由树（只承载 perms）。**用 typed dataclass 或 TypedDict**，字段名按若依 payload 冻结（前端零适配）。配契约测试快照（参考 `tests/unit/test_openapi_contract.py` 规则表模式）。

## schemas / api

- `MenuCreate/Update/Read/Tree`（parent_id/name/menu_type/path/component/perms/icon/sort_order/visible/status；menu_type 用 `Literal['M','C','F']`，status 用 `Literal`）。
- api：menu CRUD + `require_permission("system:menu:list/query/add/edit/remove")` 守卫（`Annotated[..,Depends]` 守 B008）+ 错误响应 `responses=` 声明（401/403/404/409 HAS_CHILDREN/CYCLE）。**镜像 dept/api.py 的守卫 + responses 写法**。
- **不写** `/routers` 端点（需 core get_menu_provider 注入，人值守接线）—— 但写好 `build_routers` + DbMenuProvider 供其调用。

## service.py

- menu CRUD（抛 AppError，错误码 `menu.*`：NOT_FOUND/HAS_CHILDREN/CYCLE/PARENT_NOT_FOUND）。镜像 dept service 的树写 advisory lock + 防环 + RESTRICT 删预检。**无 code 唯一校验**（菜单无 code）。

## migration

- `make new-module name=menu with-model=1`（五层骨架 + patch env.py）。
- `uv run alembic revision --autogenerate -m "p1_menus"`，**人工 review**：菜单表 + role_menus + 索引 + CheckConstraint 齐全；若 autogenerate 产出残留把它清掉（沿用 0005 经验：手写干净 migration，文件名 `0006_p1_menus.py`，down_revision=`0005`）。

## 测试

- 单元（stub repo）：menu CRUD、树建树逻辑、getRouters payload 映射（目录→Layout / hidden / 按钮不进树 / meta 字段）、防环 409、有子禁删 409。
- 集成（真 DB，auth override 参考 test_dept_crud）：menu CRUD 端到端 + 权限矩阵 5 端点 403 + `DbMenuProvider.a_get_user_menu_tree`（超管见全部、非超管经 role_menus 见子集、停用菜单不下发）+ `list_perms_for_user` / `list_menu_ids_for_user` 经 role_menus 正确（含停用角色不贡献）。

## ⚠️ 人值守接线（你没权限改 / 安全关键，完成报告里逐条列）

1. `core` 加 `get_menu_provider` 注入点（fail-closed，镜像 `get_permission_provider`）+ `main.py` override `DbMenuProvider` + 挂 menu_router。
2. `DbPermissionProvider.get_user_permissions`（role 域）改为调 menu repository `list_perms_for_user` 真实派生（**安全关键，人值守 + Codex 审后改**；R1 目前返回 frozenset()）。
3. `.importlinter` C1 containers 纳 `admin_platform.domains.menu`。
4. §13.2 权限点 registry + 三集合机检（独立后续）。
5. getInfo / `/menus/routers` 端点（§6 打通阶段）。

## 完成判据

- `make check` + `make migrate` + `make check-db`（零漂移）+ `make test-integration` 全绿。
- 完成报告列出「人值守接线」清单 + 关键设计决策（菜单树存储 / sync→async 桥 / getRouters 字段映射）。

完成后停。
