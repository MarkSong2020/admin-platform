# P6 前端技术栈选型与架构设计

> **状态**：设计稿 v5 **对抗收敛**（v1→v2 采纳 6 项；v2→v3 采纳 4 项；v3→v4 采纳 3 项；v4→v5 采纳 2 项；**第六轮 review v5 → 0 项，Codex 判定「无新实质问题，可进入实现」**。5 轮对抗趋势 6→4→3→2→0）
> **日期**：2026-06-11
> **决策来源**：Claude × Codex high 协同 PK + 多轮对抗审查（loop）—— 第一轮选型收敛「完全自建」，后续轮次对抗 review 逐层钉死落地口径 + 用户拍板（总方向 / 分层范式 / 登录态 三项不可逆决策）
> **上游**：[`2026-06-04-ruoyi-parity-roadmap.md`](./2026-06-04-ruoyi-parity-roadmap.md) §6、Q5/Q9
> **后端契约依据**：getInfo / getRouters 已按若依格式冻结（`tests/contracts/`、`tests/unit/test_rbac_frontend_contract.py`；菜单树生成 `domains/menu/routers.py`，seed `rbac/seed.py` 的 `MENU_TREE`；登录 `domains/auth/`；OpenAPI 由 `main.py` 内 `create_app().openapi()` DB-free 生成）

---

## 一句话结论

> P6 **完全自建** Vue3 + TypeScript 前端，**不 fork 若依、不以 vben/pure-admin 为代码基座**。`api/session.ts` 作**唯一**认证/刷新协调器（只管 token，失效抛 typed error），`openapi-fetch` 吃后端 OpenAPI 做**类型化 JSON CRUD**、`api/transport.ts` 兜 **multipart/blob/错误归一**、`dependency-cruiser` 做前端分层机检——把后端「强工程纪律」延伸到前端，对齐 D5「团队长期 Python 后台标准样板」。代价是起步慢于 fork，换长期可控、最干净、易维护。

---

## 1. 决策记录（locked）

| # | 决策 | 理由 | 来源 |
|---|---|---|---|
| **F1** | **完全自建**，不 fork RuoYi-Vue3，不以现代模板为基座 | D5「长期标准样板、不走 fork 捷径」压倒「零适配」速度 | 双 AI 收敛 + 用户拍板 |
| **F2** | **简化分层 + 依赖方向机检**，不上全套 FSD | 对 CRUD 后台 FSD 偏重；严格度花在可机检的依赖方向 | Claude push back + 用户拍板 |
| **F3** | **登录态 = access 内存 + refresh sessionStorage + 静默续期** | 刷新不掉登录；sessionStorage XSS 面小于 localStorage | 用户拍板 |
| **F4** | **UI = Element Plus** | 贴若依生态，后台组件成熟 | 双 AI 收敛 |
| **F5** | **API = openapi-typescript + openapi-fetch（JSON）+ transport（二进制/错误）+ session（认证协调，只管 token）** | 契约一改即编译报错；二进制/错误归一/single-flight refresh 集中；**认证失效经 typed error 交上层，不让 api 层越界依赖 stores/router** | 双 AI + 三轮 Codex review |
| **F6** | **前端工程纪律对齐后端**：TS strict + depcruise + OpenAPI 漂移门 + Vitest/Playwright + 本地提交门 | 前端版 import-linter + alembic-drift + 测试三层 | 双 AI 印证 |

> **裁决信号**：不可逆技术栈选型，命中红线，F1/F2/F3 已由用户 2026-06-11 拍板。

---

## 2. PK 收敛记录（Claude × Codex high，多轮对抗，2026-06-11）

- **第一轮（选型）**：两独立来源一致 → 完全自建 + 全栈。Claude push back FSD → 简化分层。
- **第二轮（review v1）**：6 项 → v2（transport 拆分 / router composition root / seed contract test / 多标签语义 / bootstrap 时序 / P6.0 必测+提交门）。
- **第三轮（review v2）**：4 项 → v3（session.ts 唯一协调器 / layouts 层 / seed 跨语言真值源 / refresh 必有 fail fast）。
- **第四轮（review v3）**：3 项落地口径 → v4：
  1. **session 职责矛盾** → 只 `clearTokens()`+抛 `SessionExpiredError`，redirect/清 Pinia/reset 路由归 router·auth store（§3.1/§4/§6）
  2. **seed fixture 语义**（页面组件≠路由组件）→ `seed_page_components.json` 只取 `menu_type=="C"`，壳组件另 allowlist（§5）
  3. **openapi-drift CI 真值源** → `scripts/dump_openapi.py` DB-free 生成、纳入 git（§7/§9）
- **第五轮（review v4）**：2 项认证闭环/CI 确定性 → v5：
  1. **session 失效统一出口闭环** → session 自带 emitter 发 `sessionExpired` 事件（不依赖 router/stores）+ 抛 typed error；router 注册唯一 `handleSessionExpired()` 订阅者覆盖 4 路径；`normalizeApiError` 透传不降级（§3.1/§4/§6）
  2. **dump_openapi.py 确定性** → 确定性 contract profile（不读本地 `.env`、固定影响 OpenAPI 的 `APP_*`）+ 污染 env 不影响输出单测（§7/§9）

- **第六轮（review v5）**：**0 项**——Codex 判定「v5 无新实质问题，可进入实现」，反对路径=无、建议自动执行=是；列出的 5 个失效模式均已是 spec 内明确边界/必测项 → **对抗审查收敛**。

> 趋势 6→4→3→2→**0**，问题层级从「架构方向」→「实现口径」→「闭环细节」→ 收敛，逐层钉死可执行约束。

---

## 3. 技术栈

| 维度 | 选择 | 备注 |
|---|---|---|
| 框架 | Vue 3 + TypeScript（`strict`）+ Vite | — |
| UI | Element Plus | F4 |
| 状态 | Pinia | auth/permission/menu/userInfo（auth store 读 session token） |
| 服务端状态 | 首版 composable；后续视情引 `@tanstack/vue-query` | §11 |
| 路由 | Vue Router 4 | 动态路由由菜单树转换 |
| API 层 | `openapi-fetch`（JSON）+ `transport.ts`（二进制/错误）+ `session.ts`（认证协调器） | §3.1 |
| 包管理/运行时 | pnpm 10 + corepack + Node 22 LTS | 锁版本 |

### 3.1 API 层分工（核心）

**`api/session.ts` = 唯一认证/刷新协调器（token 真值源，只管 token）**：
- 持有 **access（内存）+ refresh（sessionStorage）**；`auth` store 只读它供 UI
- 接口：`attachAuthHeaders(req)` / `refreshOnce()`（**single-flight**：并发只发一次 `POST /api/v1/auth/refresh`，其余挂起复用）/ `setTokens()` / `clearTokens()` / `hasRefresh()`
- **失效处理（v5 闭环）**：refresh 失败 → session **`clearTokens()` + 通过自带轻量 emitter（不 import router/stores）emit `sessionExpired` 事件 + 抛 `SessionExpiredError`**（typed error）。两通道分工：**事件**保证清理副作用必达（无论哪条路径触发）；**typed error** 让原调用方 promise reject、停止后续逻辑。`main.ts`/router composition root 启动时注册**唯一 `handleSessionExpired()` 订阅者**（清 Pinia auth/permission/menu + reset 动态路由 + redirect），覆盖 **bootstrap / router guard / 运行期 openapi-fetch / 运行期 transport 四类失败路径**。订阅方向 router→api（合规），api 层仍零依赖 router/stores。`normalizeApiError()` 必须**透传 `SessionExpiredError`，不降级成普通业务错误**（否则 router/store 识别不出失效语义）
- `refreshOnce()` 用**不挂自身拦截的裸 fetch** 调 `/auth/refresh`，**显式排除** `/auth/login|refresh|logout|captcha` 自动 refresh（防递归 401 风暴）
- **openapi-fetch middleware 与 `transport.ts` 都只调用它**——JSON 与 blob/multipart 共享同一 single-flight，并发 401 只触发一次 refresh / 一次 invalidation

**两条数据通道经 session**：

| 场景 | 通道 | 说明 |
|---|---|---|
| JSON CRUD | `openapi-fetch`（middleware→session） | 类型来自 `generated/`，漂移编译报错 |
| 上传/导入 | `transport.ts`→`FormData`（→session） | 显式 multipart |
| 下载/导出 | `transport.ts`→`blob`（→session） | 后端 `StreamingResponse`/binary（`file/api.py:138`、`post/api.py:153`），不按 JSON 解析 |
| 错误归一 | `transport.normalizeApiError()` | HTTP error / RFC9457 `ProblemDetail`（`errors` 弱类型运行时归一）/ 超时 / `AbortError` / blob 接口 JSON 错误 fallback |

**超时分场景**：JSON 短超时（~15s）；blob 下载/multipart 上传更长或可配（防 Excel 导出/大文件被主动 abort）。

> `Hey API`/`Orval` 备选：P6.0 spike 后若手写 transport 过多再评估。

---

## 4. 目录与分层（简化分层 + 机检）

```
frontend/src/
  api/
    generated/    # openapi-typescript 生成类型（CI drift 守门，勿手改）
    session.ts    # ★ 唯一认证/刷新协调器（只管 token，失效抛 SessionExpiredError）
    client.ts     # openapi-fetch 实例（JSON，middleware→session）
    transport.ts  # multipart/blob/超时/Abort/normalizeApiError（→session）
    <domain>.ts
  stores/         # pinia: auth(读 session), permission, menu, userInfo
  composables/    # usePermission, useTable…
  components/     # 通用 UI 组件
  layouts/        # ★ 路由壳：Layout / ParentView / Sidebar / Breadcrumb
  views/          # 路由页面
  router/         # ★ composition root：装配路由 + 动态路由转换 + 全局守卫 + 监听 SessionExpiredError
  directives/     # v-hasPermi
  utils/ config/
  main.ts
```

**依赖方向硬约束**（`dependency-cruiser`，CI 跑）：

| 层 | 允许 import | 禁止 |
|---|---|---|
| `utils`/`config` | 仅第三方 | 任何业务层 |
| `api`（session/client/transport） | utils, config | **stores, router**, views, components, layouts |
| `stores` | api, utils, config | views, components, layouts, router |
| `composables` | stores, api, utils | views, layouts, router |
| `components` | composables, stores, utils | views, layouts, router |
| `layouts` | components, composables, stores, utils | views, router |
| `views` | components, composables, stores, api, utils | layouts, router |
| `router` ★ | layouts, stores, api, views（懒加载）, utils, config | —（仅 `main.ts` 装配） |

**核心不变式**：
- `session.ts` 在 `api` 层、**严格不依赖 stores/router**：失效经**自带 emitter 发 `sessionExpired` 事件 + 抛 `SessionExpiredError`**，由 router composition root 启动时注册的**唯一订阅者 `handleSessionExpired()`** 处理 redirect+清 Pinia+reset 路由（订阅方向 router→api，合规——是 router 订阅 api 的 emitter，非 api 依赖 router）。**负向机检**：depcruise 断言 `api/** → stores/**`、`api/** → router/**` 被拦
- `router` 是 **composition root**：唯一组装 `layouts`+`views`+`stores`，唯一持有「动态路由 reset」职责；**其他层禁 import `src/router`**，页面导航只用 `vue-router` 的 `useRouter()/useRoute()`
- `layouts` 与通用 `components` 分离：解决「router 装配 Layout 壳但不该 import 通用 components」矛盾
- 工具分工：**depcruise 管静态分层方向**；**路由白名单完整性靠 §5 seed contract**

---

## 5. 动态路由 + 按钮权限

**动态路由**：登录后 `GET /api/v1/menus/routers` 拿若依菜单树 → `component` 字符串作 key 经 `import.meta.glob` **白名单映射**（`Layout`/`ParentView`→`layouts/`；`system/user/index`→`views/system/user/index.vue`）；不拼接任意 import，缺页 **fail fast**。

**seed 页面组件跨语言契约（v4 精化真值源）**：
- 后端 `build_routers` 把目录 `M`→`Layout/ParentView` 壳、按钮 `F` 过滤、**只有菜单 `C` 是真页面组件**（`routers.py:53/93`、`seed.py:81/203/333`）。故区分两类：
  - **页面组件 fixture** `tests/contracts/seed_page_components.json`：**后端测试**从 `MENU_TREE` 递归派生 **`menu_type=="C" && component`** 的集合并断言相等（后端改 seed 不同步 → 后端 CI 红，防漂移）
  - **壳组件 allowlist**：`Layout`/`ParentView` 固定列表，单独断言映射到 `src/layouts/*`，不混入页面 glob
- **前端 Vitest 只读 fixture**：把每项规范化为 `/src/views/${component}.vue`（**路径分隔统一 `/`、大小写精确匹配**，防 macOS 不敏感 → Linux CI 红），断言 ⊆ `import.meta.glob` key 集合
- 仅覆盖**内置 seed 菜单**；用户 DB 自建菜单缺页 → 运行时 fail fast（不在 CI 范围）
- 现有 `getrouters_system.json`（单样例）仅供转换器单测覆盖 `Layout/ParentView/外链/hidden/alwaysShow` 分支

**按钮权限**：`getInfo.permissions` 入 Pinia **Set**，超管 `*:*:*`；`v-hasPermi` + `usePermission()`。**前端权限仅 UX 层**，后端 RBAC 是唯一安全边界。

---

## 6. 认证、登录态与 bootstrap 时序（F3）

| token | 存放（`session.ts` 持有） | 理由 |
|---|---|---|
| access | **纯内存** | 不落盘 |
| refresh | **sessionStorage** | 跨刷新、同标签、关闭即清 |

**登录 refresh 必有**：后端 `APP_AUTH_REFRESH_TOKEN_PEPPER` 未配时登录成功但 `refresh_token=null`（`auth/service.py:170`、`schemas.py:27`、`.env.example:72`）。前端把**「登录响应缺 refresh_token」视为环境配置错误 → fail fast**（提示配 pepper），与「验证码失败/限流 429/账号停用 403」等**正常登录错误分支区分**（后者走常规错误提示，不 fail fast）。

**bootstrap 时序（写死，防守卫竞态）**：
```
main.ts 挂载前 bootstrap():
  登录页/公开路由 → 静态注册，addRoute 前即可达
  session.hasRefresh()?
    是 → session.refreshOnce() → getInfo → getRouters → router.addRoute(转换) → 进入目标(replace)
    否 → 跳登录
  bootstrap 完成前业务请求挂起；守卫等完成再放行
  refresh 失败 → session.clearTokens() + emit sessionExpired + 抛 SessionExpiredError → 唯一订阅者 handleSessionExpired() 清 Pinia(auth/permission/menu) + reset 动态路由 + 跳登录；原调用方拿 typed error reject
```
**失效通知机制（v5 定调）**：session **emit `sessionExpired` 事件（经自带 emitter，不依赖 router/stores）+ 抛 typed `SessionExpiredError`**——事件保证清理副作用必达（`main.ts`/router 注册的唯一 `handleSessionExpired()` 订阅者覆盖 bootstrap / router guard / 运行期 openapi-fetch / 运行期 transport 四路径），typed error 让调用方 reject。动态路由 reset 归 router（唯一职责所有者）。api 层不依赖 router/stores（router 订阅 api 的 emitter，方向合规）。**订阅时序**：`handleSessionExpired()` 必须在 `bootstrap()` 首次 `refreshOnce()` **之前**注册，否则首轮 refresh 失败漏清理。

**single-flight refresh**：并发多 401 只发一次 refresh、只触发一次 invalidation（JSON+blob 共享）——否则击中后端 refresh-reuse → family 撤销。

**多标签语义（首版最简）**：sessionStorage 不跨标签，复制标签可能共享初始 refresh → 冲突触发 family 撤销。**首版承诺：不跨标签协调；refresh 被判 reuse/失败 → 该标签 emit `sessionExpired` → `handleSessionExpired()` 清 Pinia + 跳登录**。跨标签共享续期列 §12 排期。

---

## 7. 工程纪律工具链 + CI 门

| 维度 | 工具 | 对齐后端 |
|---|---|---|
| 类型 | TypeScript `strict` + `vue-tsc` | pyright |
| Lint/format | ESLint flat + typescript-eslint + Prettier | ruff |
| 分层机检 | `dependency-cruiser`（含 `api→stores/router` 负向规则） | import-linter |
| 契约漂移 | **DB-free + 确定性 profile**：`scripts/dump_openapi.py`（**不读本地 `.env`**、固定影响 OpenAPI 的 `APP_*`）生成 `frontend/openapi/admin-platform.json`（纳入 git）→ `openapi-typescript` → `git diff --exit-code -- frontend/src/api/generated` | alembic drift |
| 单测/组件测 | Vitest + @vue/test-utils | pytest unit |
| E2E | Playwright | integration |
| 本地提交门 | husky + lint-staged + commitlint | `.pre-commit-config.yaml` |

**CI 门（全绿才过）**：`lint` + `typecheck` + `test:unit` + `build` + `depcruise` + `openapi-drift`。**`openapi-drift` 钉死为 DB-free + 确定性**：CI 跑 `dump_openapi.py`（`create_app().openapi()`，不启动服务/不连 DB，**且用确定性 contract profile——不读本地 `.env`、固定 `auth_public_paths` 等影响 schema 的 `APP_*`**）→ 生成类型 → diff，无须后端实例，本地/CI 环境差异不致假漂移。

**关键路径必测**：动态路由转换器 + 全 seed 页面组件覆盖、`v-hasPermi`/超管与拒绝、**session single-flight（JSON+blob 同轮 401 只刷一次 / `/auth/refresh` 不递归 / 失败 emit 事件 + 抛 typed error）**、**失效统一出口（JSON 请求与 blob 请求 refresh 失败都达同一 `handleSessionExpired` 并 reset 动态路由 / `normalizeApiError` 透传 SessionExpiredError 不降级）**、**分层负向（`api/session.ts→stores`、`api/session.ts→router` 被 depcruise 拦）**、transport blob/multipart/`normalizeApiError`、登录缺 refresh fail fast、**`dump_openapi.py` 污染 env 不影响输出**。

**排期**：bundle 体积门、`pnpm audit`、许可证扫描——§12。

---

## 8. 交付切片与可验证目标

| 切片 | 范围 | 可验证目标 |
|---|---|---|
| **P6.0 ✓ 已落地** | 工程基线 **+ 高风险前置 spike** | 脚手架 + 全 CI 门 + 本地提交门 + `dump_openapi.py` + openapi 类型生成 + 登录页壳 + `session.ts` + auth/permission store。**必测**：① 全 seed 页面组件覆盖（前端读 `seed_page_components.json`，规范化大小写精确）② 壳组件 allowlist ③ blob 下载 wrapper ④ multipart 上传 wrapper ⑤ **session single-flight + 失效 typed error + 分层负向** → `lint && typecheck && test:unit && build && depcruise && openapi-drift（DB-free）` 全绿 |
| **P6.1 ✓ 已落地** | 登录闭环 | 登录 + 验证码（文本算术题）+ getInfo/getRouters + bootstrap 时序 + Layout/Sidebar/Breadcrumb + v-hasPermi + session 失效/登出统一出口。Vitest 组件/集成覆盖：刷新深链放行、refresh 失败走失效出口跳登录、setup 失败不进空应用、登录缺 refresh fail fast、验证码服务不可用提示、按钮权限显隐 |
| **P6.2 ✓ 已落地** | RBAC 五页 | 用户（角色/岗位绑定）/角色（菜单·部门数据权限绑定，半选父节点纳入）/菜单（树+类型联动 M/C/F）/部门（树）/岗位 CRUD → 复用 useCrudTable/TablePagination/useTree；按钮级权限隐藏可验证 |
| **P6.3 ✓ 已落地** | 运营/监控 | 字典（类型+数据抽屉）/参数/通知（不渲染 raw HTML）+ 操作/登录日志（payload 纯文本）+ 在线用户（强制下线）/服务/缓存监控（降级）/定时任务（CRUD+手动触发+执行日志+handler 白名单） |
| **P6.4 ✓ 已落地** | 文件/Excel | 文件管理上传（on-change+transport multipart）/下载（blob）/删除 + 岗位 Excel 导入（始终 200+summary 全有全无）/导出 |

每切片独立可验收、独立 PR。**P6.0 把 session/transport/CI 真值源前置钉死**。

> **落地补记（2026-06-13，无人值守 + 多 agent 对抗审查 R1-R4 收敛）**：P6.1-P6.4 全部页面落地，前端 6 门全绿（type-check / oxlint / eslint / vitest 262 / depcruise / build）。对抗审查修复要点：R1 登出 fail-fast + bootstrap setup 失败走失效出口 + 验证码服务降级提示；R2 角色菜单半选父节点真覆盖；R3 cache info 空兜底 + operlog 详情按 id 真覆盖；R4 **上传/导入 `before-upload` 在 `auto-upload=false` 下永不触发（实测 el-upload 源码确认）→ 改 `on-change`**，且 `normalizeApiError` 未透传已归一 ApiError 普通对象致提示乱码 `[object Object]` → 根因修复 + 抽 `utils/format` 统一时间戳/字节渲染。后端为前端联调所需的 menu/role 提权防护等改动属并行后端安全工作流，不在本前端提交链内。

---

## 9. 后端配合点（轻、非阻塞）

- 开发期 `APP_CORS_ALLOW_ORIGINS` 加 `http://localhost:5173`
- **P6 开发/测试环境强制配 `APP_AUTH_REFRESH_TOKEN_PEPPER`**（否则不发 refresh → F3 失效）
- **新增 `scripts/dump_openapi.py`**（DB-free + **确定性 contract profile：不读本地 `.env`、清空 `get_settings()` lru_cache 并固定全部影响 OpenAPI 的 `APP_*`（`app_name`/`auth_public_paths`/`APP_ENVIRONMENT` 等）** → `frontend/openapi/admin-platform.json`，纳入 git，前端 codegen 稳定输入；配「污染 env 不影响输出」单测）
- **新增 `tests/contracts/seed_page_components.json` + 后端测试**（从 `MENU_TREE` 派生 `menu_type=="C"` component 集合守门，§5）
- token 走 `Authorization: Bearer`，**核心无需后端改造**
- 可选：后端给二进制下载端点补精确 OpenAPI 媒体类型，首版靠 transport 兜底

---

## 10. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 自建过度设计 | P6.0 只做壳/路由/权限/session/transport spike；CRUD 抽象等第 3 个重复页 |
| 2 | 双路径各自 refresh 击中 reuse | session 唯一 coordinator + single-flight，两通道共享 |
| 3 | session 失效清理不闭环 / 越界依赖 | session emit 事件 + 抛 typed error；唯一订阅者 `handleSessionExpired` 覆盖 4 路径并 reset 动态路由；`normalizeApiError` 透传不降级；depcruise 负向规则守 |
| 4 | binary 下载被当 JSON | transport 显式 blob；P6.0 必测 |
| 5 | OpenAPI 漂移 / 起后端 / env 污染 schema | DB-free + 确定性 profile（不读 `.env`、固定 `APP_*`）`dump_openapi.py` + `git diff` |
| 6 | 动态路由缺页晚爆 | 后端守 `seed_page_components.json`（仅 C）+ 前端 ⊆ glob + fail fast |
| 7 | 路由壳/页面 glob 混淆 | 页面 fixture 仅 `menu_type=="C"`，壳组件单独 allowlist |
| 8 | 大小写/路径分隔漂移（mac 绿 Linux 红） | fixture 规范化 `/` + 大小写精确匹配 |
| 9 | 路由守卫竞态 | 写死 bootstrap 时序，守卫等完成 |
| 10 | 登录缺 refresh 致 bootstrap 异常 | fail fast + 强制配 pepper，与正常登录错误分支区分 |
| 11 | AbortController 误中断下载 | 超时分场景 |
| 12 | RFC9457 errors 弱类型 / 通知富文本 XSS | transport `normalizeApiError()`；通知首版不渲染 raw HTML |

---

## 11. 未决问题（留各切片定，非阻塞）

- `@tanstack/vue-query`：倾向先不引，P6.1 后视重复度
- `Hey API`/`Orval` 备选：P6.0 spike 后评估
- 图标体系、表格虚拟滚动：延后
- 通知富文本 sanitizer 选型：P6.3
- i18n / 主题：P6.1 layout 时定（倾向单语言 + 基础亮/暗）

---

## 12. 非目标 / 排期

- **不 fork 任何 admin 模板**（F1）；**不做表单可视化构建器**
- **首版不渲染 raw HTML 富文本**；**不引入 SSR**；**不做移动端 / uni-app**
- **httpOnly cookie + CSRF 登录态**：本期不做（F3 选 sessionStorage），未来安全升级走后端配合单独 spec
- **跨标签共享续期**（Web Locks + BroadcastChannel）：首版最简语义，排期
- **bundle 体积门 / `pnpm audit` / 许可证扫描**：基线稳定后补
