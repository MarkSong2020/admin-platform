# admin-platform · 前端

对标 RuoYi 的单租户后台管理前端。配套后端为 `../`（FastAPI + SQLAlchemy 2.x）。

## 技术栈

Vue 3.5（`<script setup>`）· TypeScript（strict + `noUncheckedIndexedAccess`）· Vite 8 · Pinia 3 · vue-router 5 · Element Plus 2.14 · openapi-fetch（类型化 client）· Vitest 4（jsdom）· dependency-cruiser（分层机检）· pnpm 10。

## 快速开始

```sh
pnpm install
cp .env.example .env.local   # 配置 VITE_API_BASE 指向后端，如 http://127.0.0.1:8000
pnpm dev
```

## 脚本

| 命令 | 作用 |
|---|---|
| `pnpm dev` | 本地开发（Vite HMR） |
| `pnpm build` | 类型检查 + 生产构建 |
| `pnpm type-check` | `vue-tsc` 全量类型检查 |
| `pnpm test:unit` | Vitest 单测（watch） |
| `pnpm test:unit run` | Vitest 单测（单次，CI 用） |
| `pnpm lint` | oxlint + eslint（带 `--fix`） |
| `pnpm format` | Prettier 格式化 |
| `pnpm depcruise` | dependency-cruiser 分层契约校验 |
| `pnpm openapi:generate` | 从后端 OpenAPI 重新生成 `src/api/generated/types.ts` |
| `pnpm openapi-drift` | 重新 dump 后端 schema → 生成 → diff（检测前后端契约漂移） |

## CI 6 门

`.github/workflows/frontend.yml`：**lint · type-check · unit-test · build · depcruise · openapi-drift**。提交前本地走根 `pre-commit`（lint + commitlint）。

## 分层约束（dependency-cruiser 机检）

```
views ─┐
       ├─→ composables ─┐
       ├─→ api ──────────┼─→ utils（叶子，禁依赖任何业务层）
stores ─┤                │
       └─→ api ──────────┘
layouts/views ──(navigation only via vue-router; 禁 import 本地 router singleton)
```

- `api`（含 `session`）禁 import `stores`/`router`（会话失效经 emitter + typed error 上抛）
- `views`/`layouts` 禁 import 本地 router singleton（导航只用 `useRouter()`）
- `directives` 仅依赖 `stores`/`utils`；`utils` 为叶子层；全仓禁循环依赖与孤儿模块

## 目录

```
src/
├── api/            # 域 API 封装 + client/transport/session/download；generated/ 为生成类型
├── stores/         # Pinia：auth / menu / permission / user-info / session-expiry / logout / post-login
├── composables/    # useCrudTable / useTree / usePermission
├── components/     # 通用组件（TablePagination 等）
├── directives/     # v-hasPermi 按钮权限指令
├── layouts/        # Layout 壳（Sidebar / Breadcrumb / ParentView）
├── router/         # composition root：静态 + 动态路由装配/重置 + bootstrap 时序 + 全局守卫
├── views/          # 页面（system/ · monitor/ · login · home · error）
└── utils/          # 叶子工具（format 等）
```

## API 类型契约

后端 OpenAPI → `openapi-typescript` 生成 `src/api/generated/types.ts`，各域 API 复用其 `components['schemas']` / `operations`，经 openapi-fetch 端到端类型安全。后端 schema 变更由 `openapi-drift` CI 门拦截。
