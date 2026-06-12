/**
 * session 失效统一出口（spec §6）：bootstrap 首次 refresh 之前注册唯一订阅者，
 * 覆盖 bootstrap / 路由守卫 / 运行期 openapi-fetch / 运行期 transport 四条触发路径。
 * stores 层，允许依赖 stores/api；redirect 与动态路由 reset 属 router 职责，
 * 由 main.ts 经回调注入（stores 不直接 import router，过 depcruise 分层）。
 */
import { clearTokens, onSessionExpired } from '@/api/session'
import { useMenuStore } from './menu'
import { usePermissionStore } from './permission'
import { useUserInfoStore } from './user-info'

export interface SessionExpiryDeps {
  /** 动态路由重置（main.ts 注入 router 的 resetDynamicRoutes）。 */
  resetDynamicRoutes: () => void
  /** 跳登录（main.ts 注入 router.replace）。 */
  redirectToLogin: () => void
}

let registered = false

export function registerSessionExpiryHandler(deps: SessionExpiryDeps): void {
  if (registered) return // 唯一订阅者
  registered = true
  onSessionExpired(() => {
    clearTokens() // refreshOnce 失败路径已清，其余 emit 路径兜底
    useUserInfoStore().reset()
    useMenuStore().reset()
    usePermissionStore().reset()
    deps.resetDynamicRoutes()
    deps.redirectToLogin()
  })
}

/** 仅供单测重置注册标志。 */
export function __resetSessionExpiryForTest(): void {
  registered = false
}
