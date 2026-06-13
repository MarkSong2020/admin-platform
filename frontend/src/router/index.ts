/**
 * 路由 composition root（spec §4/§6）：唯一组装 layouts + views + stores 的模块。
 * 职责：静态路由 + 动态路由装配/重置（唯一所有者）+ bootstrap 时序 + 全局守卫。
 * 其他层禁 import 本模块（depcruise 拦），页面导航只用 vue-router 的 useRouter()/useRoute()。
 */
import {
  createMemoryHistory,
  createRouter,
  createWebHistory,
  type RouteRecordRaw,
} from 'vue-router'
import Layout from '@/layouts/Layout.vue'
import { clearTokens, emitSessionExpired, hasRefresh, refreshOnce } from '@/api/session'
import type { RouterVO } from '@/api/auth'
import { useMenuStore } from '@/stores/menu'
import { useUserInfoStore } from '@/stores/user-info'
import { toRoutes } from './dynamic-routes'

const LOGIN_ROUTE_NAME = 'login'
const NOT_FOUND_ROUTE_NAME = 'not-found'

/** 静态路由：登录页（公开）+ Layout 壳（默认 child 首页）+ 404 catchAll（公开兜底）。 */
const staticRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: LOGIN_ROUTE_NAME,
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    name: 'root',
    component: Layout,
    redirect: '/home',
    children: [
      {
        path: 'home',
        name: 'home',
        component: () => import('@/views/home/index.vue'),
        meta: { title: '首页' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: NOT_FOUND_ROUTE_NAME,
    component: () => import('@/views/error/404.vue'),
    meta: { title: '404', public: true },
  },
]

const router = createRouter({
  // vitest（jsdom）下用 memory history，避免依赖 jsdom 的 history 实现；生产用 web history
  history:
    import.meta.env.MODE === 'test'
      ? createMemoryHistory()
      : createWebHistory(import.meta.env.BASE_URL),
  routes: staticRoutes,
})

// ---------------------------------------------------------------------------
// 动态路由装配/重置（reset 职责唯一归本模块；session 失效出口经 main.ts 注入回调调用）
// ---------------------------------------------------------------------------

/** 已装配的顶层动态路由 name（removeRoute 顶层即可级联移除 children）。 */
let installedRouteNames: string[] = []

/** getRouters 菜单树 → addRoute 装配；记录 name 供 reset。 */
export function installDynamicRoutes(routers: RouterVO[]): void {
  for (const route of toRoutes(routers)) {
    router.addRoute(route)
    if (route.name != null) installedRouteNames.push(String(route.name))
  }
}

/** 移除全部已装配的动态路由（登出/session 失效时调用，幂等）。 */
export function resetDynamicRoutes(): void {
  for (const name of installedRouteNames) {
    if (router.hasRoute(name)) router.removeRoute(name)
  }
  installedRouteNames = []
}

// ---------------------------------------------------------------------------
// bootstrap（spec §6 时序写死，single-run）
// ---------------------------------------------------------------------------

/**
 * 登录态装配：getInfo → getRouters → 装配动态路由。
 * bootstrap 恢复会话与登录成功后（T3 登录页）复用同一时序。
 */
export async function setupAfterLogin(): Promise<void> {
  const menuStore = useMenuStore()
  await useUserInfoStore().loadUserInfo()
  await menuStore.loadRouters()
  installDynamicRoutes(menuStore.routers)
}

let bootstrapDone = false
let bootstrapInflight: Promise<void> | null = null

/**
 * 应用启动装配（守卫首次导航时 await）：
 * hasRefresh ? refreshOnce → getInfo → getRouters → addRoute : 直接完成（守卫跳登录）。
 * single-run：并发调用复用同一 promise；失败也标记完成（不无限重试）。
 */
export function bootstrap(): Promise<void> {
  if (bootstrapDone) return Promise.resolve()
  if (bootstrapInflight) return bootstrapInflight
  bootstrapInflight = (async () => {
    try {
      if (!hasRefresh()) return // 无登录态：直接完成，守卫负责跳登录
      await refreshOnce()
      await setupAfterLogin()
    } catch {
      // refresh 失败：session 层已 clearTokens + emit sessionExpired（此时 hasRefresh()=false），
      // 唯一订阅者（stores/session-expiry）清 Pinia + reset 动态路由 + 跳登录。
      // setup（getInfo/getRouters）失败：token 仍在（hasRefresh()=true）→ 主动走失效出口，
      // 避免用户带有效 token 却进入无 user/无动态路由的空应用（守卫只看 hasRefresh 会误放行）。
      if (hasRefresh()) {
        clearTokens()
        emitSessionExpired()
      }
    } finally {
      bootstrapDone = true
      bootstrapInflight = null
    }
  })()
  return bootstrapInflight
}

/** 仅供单测重置 bootstrap 状态。 */
export function __resetBootstrapForTest(): void {
  bootstrapDone = false
  bootstrapInflight = null
}

// ---------------------------------------------------------------------------
// 全局守卫（防 bootstrap 竞态：完成前业务路由一律挂起）
// ---------------------------------------------------------------------------

router.beforeEach(async (to) => {
  // 登录页公开：直接放行（404 也公开，但需先经 bootstrap 重解析，见下）
  if (to.name === LOGIN_ROUTE_NAME) return true
  // 守卫等 bootstrap 完成再放行；完成后立即 resolve，不重复执行
  await bootstrap()
  // 无登录态 → 跳登录并携带原目标（含匹配落在 catchAll 的深链，登录装配后回跳重解析）
  if (!hasRefresh()) {
    return { name: LOGIN_ROUTE_NAME, query: { redirect: to.fullPath } }
  }
  // 深链刷新：本次匹配发生在 addRoute 之前 → 落在 catchAll；装配后重解析一次继续（replace）
  if (to.name === NOT_FOUND_ROUTE_NAME) {
    const resolved = router.resolve(to.fullPath)
    if (resolved.name !== NOT_FOUND_ROUTE_NAME) {
      return { path: to.fullPath, replace: true }
    }
    // 真 404：公开放行兜底页
  }
  return true
})

export default router
