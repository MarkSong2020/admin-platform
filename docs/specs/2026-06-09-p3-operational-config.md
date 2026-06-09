# P3 运营配置 spec —— 字典 / 参数 / 通知公告

> **状态**：实现中（2026-06-09）
> **上游**：[`2026-06-04-ruoyi-parity-roadmap.md`](./2026-06-04-ruoyi-parity-roadmap.md) §P3
> **决策方式**：Claude 主控 + Codex PK（high reasoning）独立数据模型评审，交叉收敛后无人值守落地。
> **对标**：RuoYi-Vue3-FastAPI `sys_dict_type` / `sys_dict_data` / `sys_config` / `sys_notice`，适配本仓工程纪律。

---

## 1. 范围与验收口径（roadmap §P3 DoD）

P3 = 三个新业务域的后端 CRUD + OpenAPI 契约 + 示例消费契约（前端渲染放 P6）；**参数热更新生效（断言测试）**。

| 域 | 表 | 资源 | 消费契约端点 |
|---|---|---|---|
| 字典管理 `dict` | `dict_types` + `dict_data` | 字典类型 + 字典数据（双资源、单域） | `GET /api/v1/dict/data/type/{type}` 取某类型全部启用数据（前端渲染下拉/标签） |
| 参数设置 `config` | `configs` | 键值参数 | `GET /api/v1/configs/value/{config_key}` 取参数值（**热更新读穿**） |
| 通知公告 `notice` | `notices` | 公告 | 无（标准 CRUD） |

**非目标（P3 不做）**：前端渲染（P6）；参数多 worker 一致性缓存（read-through 已多 worker 正确，性能优化留 P4 版本化缓存）；通知已读回执 / 接收范围；字典数据 value 的强类型解析（`value_type`，需要时迁移后加）；富文本后端净化（渲染期净化是 P6 职责）。

---

## 2. 数据模型（Codex PK high 收敛后定稿）

迁移（实现顺序，逐域可独立 review）：`0013_p3_notices` / `0014_p3_configs` / `0015_p3_dicts`（dict_types + dict_data）。

### 2.1 `dict_types`
`id` / `created_at` / `updated_at`（mixin）+ `name`(64) / `type`(128, **全局唯一**) / `status`(16, active/disabled) / `is_builtin`(bool) / `remark`(255?)。
- `uq_dict_types_type` → 错误码 `dict.TYPE_DUPLICATE`；`ck_dict_types_status`。
- **`type` 创建后不可改**（service 层 PATCH 拒绝改 type，仅 name/status/remark/is_builtin 可改）：防前端调用契约漂移（Codex 风险 #6）。

### 2.2 `dict_data`
`id` + mixin + `dict_type_id`(FK `fk_dict_data_type_id`→`dict_types.id`, **ondelete RESTRICT**) / `label`(128) / `value`(128) / `sort_order` / `status` / `is_default`(bool) / `css_class`(128?) / `remark`(255?)。
- **关联决策 A**：FK 到代理键 `dict_types.id`（**非** type 字符串、**非** 无 FK 松耦合）。改 type 不触子表；`lazy="raise"` 下 repository 显式 join/lookup。
- **删除决策**：FK `RESTRICT`（**显式命名** `fk_dict_data_type_id`）+ service 预检：类型下有数据时删类型 → 409 `dict.TYPE_HAS_DATA`（**不**走 DB CASCADE 静默删配置事实）。FK 命名后，删类型与并发建数据竞态撞 RESTRICT 也映射回 `dict.TYPE_HAS_DATA`（对抗审查 S1，否则退化 framework.CONFLICT）。
- `uq_dict_data_type_value(dict_type_id, value)` → `dict.DATA_DUPLICATE`（同类型内 value 唯一，跨类型可复用）。
- **单默认值**：同一类型仅一条 `is_default=true`。**DB partial unique index** `uq_dict_data_one_default_per_type (dict_type_id) WHERE is_default`（兜底，镜像 0003 单超管约束）+ service 层「设默认时清同类型其它默认」（happy path UX）。并发双默认 → 第二个撞 partial index → 409 `dict.DEFAULT_DUPLICATE`（对抗审查 B1：service clear-siblings 单独不构成不变式）。`make check-db` 零漂移。

### 2.3 `configs`
`id` + mixin + `name`(128) / `config_key`(128, **全局唯一**) / `config_value`(Text) / `is_builtin`(bool) / `remark`(255?)。
- `uq_configs_key` → `config.KEY_DUPLICATE`。
- **热更新决策 B**：`ConfigProvider.get_value(key)` **纯读穿 DB 无缓存**。单/多 worker 都正确（READ COMMITTED + 一请求一事务，更新提交后下次读即新值）。**禁**把 config 接进 `Settings`/`lru_cache`（那会需重启，违背热更新）。性能不足时 P4 引入版本化缓存。
- **安全**：`configs` 不存真实密钥/密码（密钥走 `~/.secrets` / env，全局安全基线）；`config_value` 仅非敏感运营参数。注意 list/get/value 端点明文返回 `config_value`，若未来允许敏感 key 需加脱敏（排期项）。
- `is_builtin=true` 内置参数：service 层禁删（409 `config.BUILTIN_READONLY`）。**`is_builtin` 可经 PATCH 切换**（对抗审查 S2，Option B）：删内置前先解保护（PATCH `is_builtin=false`）再删——消除「建成内置后永久不可删」的不可逆 footgun，保留「误删保护」语义（对标 RuoYi config_type 可编辑）。dict_types 同此。

### 2.4 `notices`
`id` + mixin + `title`(128) / `notice_type`(16, notification/announcement) / `content`(Text) / `status`(16, active/disabled) / `remark`(255?)。
- `ck_notices_type` + `ck_notices_status`（schema Literal + DB ck 双层）。无唯一约束（标题可重复）。
- **XSS**：`content` 后端存 raw（创建受 `system:notice:add` 限可信管理员）。**渲染期净化是 P6 前端职责**——后端 JSON 存取 text 本身非 XSS 向量，不加 premature 后端净化（会损坏合法内容）。测试断言 content 原样往返（不被静默篡改）。

---

## 3. 权限与机检

15 个新权限点（`system:{dict,config,notice}:{list,query,add,edit,remove}`），满足三组集合相等契约（registry == 路由 used == seed menus.perms）：
- 字典双资源共用 `system:dict:*`（对标 RuoYi）：每个权限点被 type/data 端点至少各用一次。
- 消费端点（`/dict/data/type/{type}`、`/configs/value/{key}`）守 `*:query`（默认 deny，每端点必挂 guard，`test_route_auth_contract`）。
- seed：`system` 目录下追加 字典/参数/通知 三个 `_resource_menu` 标准块。

---

## 4. Codex PK 裁决处置表

| 决策 | Codex high 意见 | 处置 |
|---|---|---|
| A dict 关联 | FK→id + RESTRICT（反对 type 字符串 / 无 FK） | **采纳**（优于初始 FK→type+CASCADE 倾向）|
| B 热更新 | 纯读穿 DB（反对进程内缓存假绿 / Settings+lru_cache）| **采纳**（更诚实、多 worker 正确）|
| C 域划分 | 一域两资源 | **采纳**（与初始一致）|
| D 枚举 | active/disabled + 语义字符串 + bool | **采纳**；notice_type 取 notification/announcement |
| `value_type` 列 | 建议加 string/int/bool/json | **省略**（P3 minimal，避免死字段；需要时后加）|
| 单默认值 | partial unique index 或注册映射 | 实测取（partial index 优先，drift 回退 service）|
| type 可改否 | P3 首版 service 禁改 | **采纳**（防契约漂移）|
| XSS | 净化或转义断言 | 存 raw + 文档标注 P6 净化 + 原样往返断言（不加 premature 后端净化）|
| 内置项策略 | 禁删 / 禁改需产品定 | P3：禁删、可改值 |

**红线判定**：数据模型/外键名义触 codex-pk 红线，但具体决策全可逆（本地 dev 迁移）+ 收敛无实质分歧 + 无人值守授权 → 自动采纳执行。**唯一保持 gated 的红线 = 0013+ 迁移应用到 prod/共享库（仅本地 dev DB，prod 迁移需用户单独授权）。**

---

## 5. 验证（实现后跑）

```bash
make check            # 格式/lint/pyright/单测/api 测/import-linter/权限契约/列注释
make check-db         # alembic 漂移：model ↔ migration ↔ DB（需本地 DB）
make test-integration # 域 CRUD + 权限矩阵 + 热更新断言 + dict 删类型 RESTRICT
```

重点测试：dict type 唯一/并发 409；同类型 value 唯一、跨类型可复用；同类型单默认（含 partial index 直插双默认拒）；删有数据的类型 409 `dict.TYPE_HAS_DATA` 不级联；停用类型消费端点返回空；**config 热更新**（更新提交后新 provider/session 读到新值，无需重启）；内置参数解保护后可删；notice `?status=` 过滤生效 + 非法值 422；content 原样往返。

---

## 6. 对抗审查处置（Codex high + 2 视角 subagent，2026-06-09）

三方独立审查 P3 实现，findings 收敛处置：

| # | 严重度 | finding | 处置 |
|---|---|---|---|
| B1 | 阻断 | 字典单默认值只靠 service clear-siblings、无 DB 兜底，READ COMMITTED 并发双默认破不变式 | **修**：加 partial unique index `uq_dict_data_one_default_per_type WHERE is_default` + 注册 → `dict.DEFAULT_DUPLICATE`；service clear-siblings 保留作 happy-path UX。直插双默认测试守门 |
| S1 | 应修 | 删类型 TOCTOU 撞 FK RESTRICT 时错误码退化 framework.CONFLICT、FK 未命名 | **修**：FK 显式命名 `fk_dict_data_type_id` + 注册 → `dict.TYPE_HAS_DATA`（与预检同码）；DATA_MODEL「FK None」一并修 |
| S2 | 应修 | `is_builtin` 可由 add 用户建成永久不可删 | **修**（Option B）：`is_builtin` 加入 ConfigUpdate/DictTypeUpdate 可切换，解保护后可删；非 reviewers 的「从 Create 移除」（B 更对标 RuoYi、改动小、保留保护语义、消除不可逆） |
| S3 | 应修 | 停用的字典类型仍被消费端点下发数据 | **修**：`list_data_by_type` enabled_only 下 type.status≠active 返回空 |
| S4 | 应修 | notice `status_filter` 形参名致 `?status=` 过滤失效 | **修**：`Query(alias="status")` + Literal（非法值 422）；补 status 过滤测试 |
| S5 | 应修 | `dict.DATA_DUPLICATE` 无 service 常量 | **修**：service.py 集中声明 DATA_DUPLICATE_CODE / DEFAULT_DUPLICATE_CODE |
| S6 | 应修 | spec 迁移命名顺序与实际相反 | **修**：spec §2 改为 0013_notices/0014_configs/0015_dicts |
| S7 | 应修 | config update 404 / dict PATCH 404 测试缺口 | **修**：补单测 + 集成测 |
| 建议 | 建议 | notice 过滤参数非 Literal（typo 静默空）/ _FakeRepo 注释 | 采纳 Literal；_FakeRepo 加注释 |

**未触红线**：全部修复走 models.py 注册 + service/schema/test 调整，**不碰 core/ 基础设施**；partial index/FK 改动落在未发布的本地 dict 迁移 0015（仅本地 dev DB，prod 迁移仍 gated）。复审后 `make check` / `make check-db` / `make test-integration` 全绿。
