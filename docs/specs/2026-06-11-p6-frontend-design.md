# P6 前端技术栈选型与架构设计

> **状态**：设计稿 v2（v1 经 Codex high 对抗 review，采纳 6 项落地强化）
> **日期**：2026-06-11
> **决策来源**：Claude × Codex high 协同 PK —— 第一轮选型收敛「完全自建」，第二轮对抗 review spec 找出落地缺陷 + 用户拍板（总方向 / 分层范式 / 登录态 三项不可逆决策）
> **上游**：[`2026-06-04-ruoyi-parity-roadmap.md`](./2026-06-04-ruoyi-parity-roadmap.md) §6 前端方向、Q5/Q9
> **后端契约依据**：getInfo / getRouters 已按若依格式冻结（`tests/contracts/` 有契约示例 + `tests/unit/test_rbac_frontend_contract.py` 守门；菜单树生成逻辑 `src/admin_platform/domains/menu/routers.py`，seed `src/admin_platform/rbac/seed.py`）

---

## 一句话结论

> P6 **完全自建** Vue3 + TypeScript 前端，**不 fork 若依前端、不以 vben/pure-admin 为代码基座**（仅作 UI/布局/菜单实现参考）。用 `openapi-fetch` 吃后端 OpenAPI 做**类型化 JSON CRUD**、用独立 `api/transport.ts` 兜住 **multipart 上传 / blob 下载 / 错误归一**、用 `dependency-cruiser` 做前端分层机检——把后端那套「强工程纪律」延伸到前端，对齐 D5「团队长期 Python 后台标准样板」定位。代价是起步慢于 fork，换长期可控、最干净、易维护。

---

## 1. 决策记录（locked）

| # | 决策 | 理由 | 来源 |
|---|---|---|---|
| **F1** | **完全自建**，不 fork RuoYi-Vue3，不以现代模板（vben/pure-admin）为基座 | D5 已拍板「长期标准样板、不走 fork 捷径」压倒「后端若依契约零适配」的速度优势；fork 会把「清理上游模板债」变成 P6 主线 | 双 AI 收敛 + 用户拍板 |
| **F2** | **简化分层 + 依赖方向机检**，不上全套 FSD | 对 RuoYi 式 CRUD 后台，全套 FSD 偏重、心智负担高；把严格度花在「依赖方向可机检」而非术语层级 | Claude push back Codex 的 FSD 提议 + 用户拍板 |
| **F3** | **登录态 = access 内存 + refresh sessionStorage + 静默续期** | 刷新页不掉登录；sessionStorage 比 localStorage 的 XSS 面小（不跨标签、关闭即清）；不动后端 | 用户拍板（备选 httpOnly cookie+CSRF 因需后端改造、超 P6 纯前端范围未选） |
| **F4** | **UI 库 = Element Plus** | RuoYi-Vue3 官方栈即 Element Plus，后台表单/表格/树/弹窗生态贴若依域模型；成熟稳定 | 双 AI 收敛 |
| **F5** | **API 对接 = openapi-typescript + openapi-fetch（仅 JSON CRUD）+ 手写 transport（二进制/错误归一）** | 类型直接来自 `/openapi.json`，契约一改前端编译报错；但 openapi-fetch 不覆盖 multipart/blob/RFC9457 errors，需独立 transport 层兜底（v2 修订，见 §3.1） | 双 AI 印证 + Codex review 修正 |
| **F6** | **前端工程纪律对齐后端**：TS strict + dependency-cruiser 分层机检 + OpenAPI 漂移 CI 门 + Vitest/Playwright 测试 + 本地提交门 | 前端版的 import-linter + alembic-drift + 测试三层 + pre-commit | 双 AI 印证 |

> **裁决信号（PK）**：Codex 与 Claude 均判定这是「不可逆技术栈选型，命中仓库红线，必须人拍板，不由 AI 自裁」。F1/F2/F3 已由用户 2026-06-11 明确拍板。

---

## 2. PK 收敛记录（Claude × Codex high，2026-06-11）

**方法**：Claude 喂任务 + 指针（不喂结论，保独立性），Codex high `read-only` 自取仓库独立工作；Claude 交叉评审。

**第一轮（选型）—— 完全一致（两独立来源印证 → 高可信）**：完全自建 / Vue3+TS+Vite+Element Plus+Pinia+Router4 / openapi-fetch 类型化 / dependency-cruiser 分层机检 / import.meta.glob 白名单动态路由 / v-hasPermi 按钮权限。Claude push back Codex 的全套 FSD → 简化分层（用户采纳）。

**第二轮（对抗 review spec v1）—— Codex 找出 6 项落地缺陷，Claude 全采纳（未推翻 F1/F2/F3）**：
1. `openapi-fetch` 覆盖不了 multipart/blob/RFC9457 errors（实测 OpenAPI 把下载/导出 200 暴露成 `application/json` 空 schema，后端真为 `StreamingResponse`/Excel binary）→ 拆出 `api/transport.ts`（§3.1）
2. §4 `router` 依赖方向存在 `views→router→views` 循环 → `router` 改 composition root（§4）
3. 动态路由白名单须覆盖**全** seed component，否则 fail fast 只在点菜单时爆 → P6.0 加 contract test（§5）
4. 多标签 refresh 共享 sessionStorage 触发 family 撤销 → 首版定最简多标签语义（§6）
5. 路由守卫竞态（刷新后 access 丢失）→ 写死 bootstrap 时序（§6）
6. P6.0 漏 transport spike → P6.0 补 4 必测 + 本地提交门（§8）

---

## 3. 技术栈

| 维度 | 选择 | 备注 |
|---|---|---|
| 框架 | Vue 3 + TypeScript（`strict`）+ Vite | Vue 官方推荐新项目用 Vite |
| UI | Element Plus | 贴若依生态（F4） |
| 状态 | Pinia | auth / permission / menu / userInfo |
| 服务端状态 | 首版 composable；重复明显再引 `@tanstack/vue-query` | 延后决策，见 §11 |
| 路由 | Vue Router 4 | 动态路由由后端菜单树转换 |
| API 层 | `openapi-typescript` + `openapi-fetch`（**JSON CRUD**）+ `api/transport.ts`（二进制/错误归一） | 见 §3.1 |
| 包管理/运行时 | pnpm 10 + corepack + Node 22 LTS | 锁 `.node-version` / `package.json#packageManager` |

### 3.1 API 层分工（v2 修订核心）

`openapi-fetch` **不作为全 API 唯一抽象**——它默认 JSON 解析，且后端 OpenAPI 对二进制端点 schema 不精确：

| 场景 | 走哪条 | 说明 |
|---|---|---|
| JSON CRUD（list/get/create/update/delete） | `openapi-fetch` typed client | 类型来自 `openapi-typescript` 生成的 `generated/`，契约漂移编译报错 |
| 文件上传（`files_upload`）、Excel 导入（`posts_import`） | `api/transport.ts` → `FormData` | 显式 multipart，不走 JSON |
| 文件下载（`files_download`）、Excel 导出（`posts_export`） | `api/transport.ts` → `blob`/`arrayBuffer` | 后端是 `StreamingResponse`/binary（`file/api.py:138`、`post/api.py:153`），不能按 JSON 解析 |
| 错误归一 | `api/transport.ts` → `normalizeApiError()` | 统一处理 HTTP error / RFC9457 `ProblemDetail`（`errors` 字段在 OpenAPI 为弱类型，需运行时归一）/ 网络超时 / `AbortError` / blob 接口的 JSON 错误 fallback。**不在各页面散写** |

> `Hey API` / `Orval` 作为备选：若 P6.0 spike 证明手写 transport 过多，再正式评估替换；不在 spec 里默认 openapi-fetch 覆盖所有场景。

---

## 4. 目录与分层（简化分层 + 机检）

```
frontend/
  src/
    api/
      generated/    # openapi-typescript 生成的类型（CI drift 守门，勿手改）
      transport.ts  # multipart / blob / 超时 / Abort / normalizeApiError
      client.ts     # openapi-fetch 实例（JSON CRUD）
      <domain>.ts   # 各域 api 封装
    stores/         # pinia: auth, permission, menu, userInfo
    composables/    # usePermission, useTable, useDialog…
    components/     # 通用组件: layout/sidebar/breadcrumb/crud-shell/表格表单封装
    views/          # 路由页面（按域: system/user, monitor/operlog…）
    router/         # ★ composition root：装配路由 + 动态路由转换 + 全局守卫
    directives/     # v-hasPermi
    utils/          # 纯函数工具
    config/         # 运行时配置（API base、env）
    app（main.ts）  # 应用 bootstrap
```

**依赖方向硬约束**（`dependency-cruiser`，CI 跑，等价后端 import-linter）：

| 层 | 允许 import | 禁止 |
|---|---|---|
| `utils` / `config` | （仅第三方） | 任何业务层 |
| `api` | utils, config | stores, views, components, router |
| `stores` | api, utils, config | views, components, router |
| `composables` | stores, api, utils | views, router |
| `components` | composables, stores, utils | views, router |
| `views` | components, composables, stores, api, utils | **router（禁 import 本地 router singleton）** |
| `router` ★ | stores, api, views（懒加载）, utils, config | —（仅 `main.ts` 装配它） |

**核心不变式**：
- `router` 是 **app composition root**——只有它能组装 stores + 懒加载 views；**其他所有层禁止 import `src/router`**。页面内导航只用 `vue-router` 包的 `useRouter()/useRoute()`，不碰本地 router singleton → 消除 `views→router→views` 循环，规则可被 depcruise 单向表达。
- 工具分工：**depcruise 管静态分层依赖方向**；**路由白名单完整性靠 §5 的 seed contract test**（depcruise 不证明 `import.meta.glob` 白名单完整）。

---

## 5. 动态路由 + 按钮权限

**动态路由**：
- 登录后调 `GET /api/v1/menus/routers` 拿若依菜单树（`name/path/component/redirect/hidden/alwaysShow/meta/children` 已冻结）
- 转换器把 `component` 字符串作为 **key**，经 `import.meta.glob` 建立**白名单映射**：`Layout`/`ParentView` → 壳组件；`system/user/index` → `views/system/user/index.vue`
- **不拼接任意 import**；缺对应页面 → **fail fast**
- **seed contract test（v2 新增，P6.0 必做）**：从后端 `rbac/seed.py` 抽全部内置 `component`（`system/user`、`system/file`、`monitor/operlog`、`monitor/logininfor`、`monitor/server`、`monitor/cache`、`monitor/online`、`monitor/job` …），断言 **「seed component 集合 ⊆ 前端 `import.meta.glob` key 集合」**——否则缺页只在用户点菜单时才爆。转换器纯函数化，单测消费 `tests/contracts/getrouters_*.json` 同形 fixture，并覆盖 `Layout/ParentView/外链/hidden/alwaysShow` 各分支。

**按钮权限**：
- `getInfo.permissions` 入 Pinia **Set**，超管 `*:*:*`；`v-hasPermi="['system:user:add']"` 指令 + `usePermission()`
- **前端权限仅 UX 层**，后端 RBAC 才是唯一安全边界

---

## 6. 认证、登录态与 bootstrap 时序（F3）

| token | 存放 | 理由 |
|---|---|---|
| access token | **纯内存**（Pinia state） | 不落盘，XSS 拿不到持久副本 |
| refresh token | **sessionStorage** | 跨刷新存活、同标签、关闭即清；XSS 面小于 localStorage |

**应用启动 / 页面刷新 bootstrap 时序（写死，防守卫竞态）**：
```
main.ts 挂载前 →
  sessionStorage 有 refresh?
    是 → refresh 换 access → getInfo → getRouters → router.addRoute(转换结果) → 进入目标路由(replace)
    否 → 跳登录页
首次进入受保护深链 → 守卫等待 bootstrap 完成再放行（避免首进 404 / 重复 addRoute / refresh 失败仍挂起请求）
```

**single-flight refresh**：并发多个 401 只发**一次** `POST /api/v1/auth/refresh`，其余挂起复用结果——否则并发刷新被后端判为 refresh-token-reuse → 整个 family 撤销（P1.4 机制）。

**多标签语义（v2 明确，首版最简）**：sessionStorage 不跨标签，但复制标签 / `window.open` 可能复制初始 sessionStorage → 两标签持同一 refresh，一标签轮换后另一标签用旧 refresh 会触发 family 撤销。**首版承诺：不跨标签协调续期；refresh 被判 reuse/失败时，该标签清状态跳登录**（诚实、最简）。跨标签共享续期（Web Locks + BroadcastChannel）列 §12 排期。

---

## 7. 工程纪律工具链 + CI 门

| 维度 | 工具 | 对齐后端 |
|---|---|---|
| 类型 | TypeScript `strict` + `vue-tsc` | pyright |
| Lint/format | ESLint flat config + typescript-eslint + Prettier | ruff |
| 分层机检 | `dependency-cruiser` | import-linter |
| 契约漂移 | `openapi:generate && git diff --exit-code -- frontend/src/api/generated` | alembic drift |
| 单测/组件测 | Vitest + @vue/test-utils | pytest unit |
| E2E | Playwright | integration |
| **本地提交门（v2 新增）** | husky + lint-staged + commitlint | 后端 `.pre-commit-config.yaml` |

**CI 门（全绿才过）**：`lint` + `typecheck` + `test:unit` + `build` + `depcruise` + `openapi-drift`。

**关键路径必测**（对齐后端 D8 关键路径门）：动态路由转换器 + 全 seed component 覆盖、`v-hasPermi`/`usePermission` 超管与拒绝分支、single-flight refresh 并发竞态、`transport` 的 blob 下载 / multipart 上传 / `normalizeApiError`。

**排期（非首版）**：bundle 体积门（size-limit）、`pnpm audit` 依赖安全扫描、依赖许可证扫描——见 §12。

---

## 8. 交付切片与可验证目标

| 切片 | 范围 | 可验证目标 |
|---|---|---|
| **P6.0** | 工程基线 **+ 高风险 transport spike 前置** | 脚手架 + 全 CI 门 + 本地提交门 + openapi 类型生成 + 登录页壳 + auth/permission store。**4 必测**：① 动态路由全 seed component 覆盖 contract test ② blob 下载 wrapper ③ multipart 上传 wrapper ④ single-flight refresh 单测 → `pnpm lint && typecheck && test:unit && build && depcruise && openapi-drift` 全绿 |
| **P6.1** | 登录闭环 | 登录 + 验证码 + single-flight refresh + getInfo/getRouters + bootstrap 时序 + Layout/Sidebar/Breadcrumb + v-hasPermi → E2E：刷新深链路由、401 静默续期、refresh 失败跳登录、按钮按权限显隐 通过 |
| **P6.2** | RBAC 五页 | 用户/角色/菜单/部门/岗位 CRUD → 每页 E2E 通过；按钮级权限隐藏可验证 |
| **P6.3** | 运营/监控 | 字典/参数/通知（通知首版不渲染 raw HTML）+ 操作日志/登录日志 + 在线用户/服务缓存监控/定时任务 |
| **P6.4** | 文件/Excel | 文件管理上传/下载/删除（复用 P6.0 已验证的 transport）+ 岗位 Excel 导入导出 |

每切片独立可验收、独立 PR。**P6.0 把最高风险的 transport 能力前置 spike**，避免拖到 P6.4 才发现 client 抽象撑不住文件流。

---

## 9. 后端配合点（轻、非阻塞）

- 开发期 `APP_CORS_ALLOW_ORIGINS` 加入 `http://localhost:5173`（Vite 默认端口）
- token 走 `Authorization: Bearer` header，后端已支持，**无需后端改造**
- （F3 选 sessionStorage，**不需要**后端下发 httpOnly cookie / CSRF）
- **可选优化（非阻塞）**：后端给二进制下载端点（`posts_export`/`files_download`）补精确 OpenAPI `responses` 媒体类型（`application/octet-stream` / `application/vnd.openxmlformats...`），让生成类型更准；首版前端不依赖此，靠 transport 兜底

---

## 10. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| 1 | 自建过度设计，首版迟迟不能验收 | P6.0 只做壳/路由/权限/API 基线 + transport spike；CRUD 抽象等第 3 个重复页面再提 |
| 2 | binary 下载被当 JSON 解析 | transport 显式 blob/arrayBuffer；P6.0 必测 blob wrapper |
| 3 | OpenAPI 类型漂移 | CI `openapi:generate && git diff --exit-code` 守门 |
| 4 | 动态路由 import 失控 / 缺页晚爆 | 白名单 + seed contract test（seed ⊆ glob）+ fail fast |
| 5 | refresh 并发竞态触发 family 撤销 | 单标签 single-flight；多标签首版最简语义（冲突即登出） |
| 6 | 路由守卫竞态（白屏/无限重定向） | 写死 bootstrap 时序，守卫等 bootstrap 完成再放行 |
| 7 | RFC9457 错误类型变弱（`errors` 为 unknown） | transport `normalizeApiError()` 统一归一，不各页面散写 |
| 8 | 通知公告富文本 XSS | 首版不渲染 raw HTML；sanitizer 留对应页面再开放 |

---

## 11. 未决问题（留各切片定，非阻塞）

- `@tanstack/vue-query` 是否引入：倾向先不引，P6.1 后列表/缓存重复出现再加
- `Hey API` / `Orval` 作为 openapi-fetch 备选：P6.0 spike 后若手写 transport 过多再评估
- 图标体系、表格虚拟滚动：延后到对应页面
- 通知富文本 sanitizer 选型：P6.3 通知页定
- i18n / 主题切换：首版是否纳入（倾向单语言 + 基础亮/暗，P6.1 layout 时定）

---

## 12. 非目标 / 排期

- **不 fork 任何 admin 模板**（F1）
- **不做表单可视化构建器**（roadmap 已标省略/P6+）
- **首版不渲染 raw HTML 富文本**（风险 8）
- **不引入 SSR**（纯 SPA 后台）
- **不做移动端 / uni-app**
- **httpOnly cookie + CSRF 登录态**：本期不做（F3 选 sessionStorage），未来安全升级走后端配合的单独 spec
- **跨标签共享续期**（Web Locks + BroadcastChannel）：首版最简语义，排期
- **bundle 体积门 / `pnpm audit` / 许可证扫描**：基线稳定后补
