/**
 * 主动登出统一出口（与 stores/session-expiry 同注入模式：stores 持回调，main.ts 装配）。
 * 主动登出 ≠ session 失效：不走 emitSessionExpired，由 Layout 显式调 performLogout()。
 * router 职责（reset 动态路由 / 跳登录）经 main.ts 注入，layouts/stores 不 import src/router。
 */
import { logout as apiLogout } from '@/api/auth'
import { useMenuStore } from './menu'
import { usePermissionStore } from './permission'
import { useUserInfoStore } from './user-info'

export interface LogoutDeps {
  /** 动态路由重置（main.ts 注入 router 的 resetDynamicRoutes）。 */
  resetDynamicRoutes: () => void
  /** 跳登录（main.ts 注入 router.replace）。 */
  redirectToLogin: () => void
}

let deps: LogoutDeps | null = null

export function registerLogoutDeps(injected: LogoutDeps): void {
  deps = injected
}

/** 登出：后端撤销（best-effort，api 层已容错并 clearTokens）→ 清三 store → reset 动态路由 → 跳登录。 */
export async function performLogout(): Promise<void> {
  // 未注册视为装配缺陷，fail fast（与 post-login 一致）：否则清完 store/token
  // 却不跳转，用户停在需鉴权页面陷入不一致状态且无任何反馈。
  if (!deps) {
    throw new Error('logout deps 未注册：main.ts 应先 registerLogoutDeps()')
  }
  await apiLogout()
  useUserInfoStore().reset()
  useMenuStore().reset()
  usePermissionStore().reset()
  deps.resetDynamicRoutes()
  deps.redirectToLogin()
}

/** 仅供单测重置注入。 */
export function __resetLogoutForTest(): void {
  deps = null
}
