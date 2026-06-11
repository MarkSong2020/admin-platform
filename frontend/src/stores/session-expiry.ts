/**
 * session 失效统一出口（spec §6）：bootstrap 首次 refresh 之前注册唯一订阅者。
 * stores 层，允许依赖 stores；redirect 由调用方（main.ts/router）注入，避免 stores 直依赖 router。
 *
 * ⚠️ P6.0 范围边界（对 spec §6 全集的「子集」，因依赖项尚未落地，非静默降级）：
 *   spec §6 完整失效语义 = 清 auth/permission/menu store + reset 动态路由 + redirect。
 *   P6.0 尚未引入 menu store、尚未 addRoute 动态路由（均在 P6.1），故 P6.0 handler 仅
 *   清 permission + redirect。P6.1 落地动态路由/menu 时，在本同一 handler 内追加
 *   menuStore.reset() 与 resetDynamicRoutes()，结构不变。
 */
import { onSessionExpired } from '@/api/session'
import { usePermissionStore } from './permission'

export interface SessionExpiryDeps {
  redirectToLogin: () => void
}

let registered = false

export function registerSessionExpiryHandler(deps: SessionExpiryDeps): void {
  if (registered) return // 唯一订阅者
  registered = true
  onSessionExpired(() => {
    usePermissionStore().reset()
    deps.redirectToLogin()
  })
}

/** 仅供单测重置注册标志。 */
export function __resetSessionExpiryForTest(): void {
  registered = false
}
