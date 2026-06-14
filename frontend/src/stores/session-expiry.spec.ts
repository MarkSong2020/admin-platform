import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePermissionStore } from './permission'
import { useUserInfoStore } from './user-info'
import { useMenuStore } from './menu'
import { registerSessionExpiryHandler, __resetSessionExpiryForTest } from './session-expiry'
import { emitSessionExpired, setTokens, hasRefresh, __resetSessionForTest } from '@/api/session'

beforeEach(() => {
  setActivePinia(createPinia())
  sessionStorage.clear()
  __resetSessionForTest()
  __resetSessionExpiryForTest()
})

describe('session 失效统一出口', () => {
  it('emit sessionExpired → 清 token/permission/user-info/menu + reset 动态路由 + 跳登录', () => {
    const perm = usePermissionStore()
    perm.setPermissions(['system:user:list'])
    const userInfo = useUserInfoStore()
    userInfo.user = {
      id: 1,
      username: 'admin',
      nickname: '管理员',
      dept_id: null,
      status: 'active',
      is_super_admin: true,
    }
    const menu = useMenuStore()
    menu.loaded = true
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    expect(hasRefresh()).toBe(true)

    const redirect = vi.fn()
    const resetRoutes = vi.fn()
    registerSessionExpiryHandler({ resetDynamicRoutes: resetRoutes, redirectToLogin: redirect })
    emitSessionExpired()

    expect(perm.has('system:user:list')).toBe(false)
    expect(userInfo.user).toBeNull()
    expect(menu.loaded).toBe(false)
    expect(hasRefresh()).toBe(false)
    expect(resetRoutes).toHaveBeenCalledTimes(1)
    expect(redirect).toHaveBeenCalledTimes(1)
  })

  it('重复 register 只注册一次订阅者（唯一出口）', () => {
    const r1 = vi.fn()
    registerSessionExpiryHandler({ resetDynamicRoutes: vi.fn(), redirectToLogin: r1 })
    registerSessionExpiryHandler({ resetDynamicRoutes: vi.fn(), redirectToLogin: vi.fn() }) // 第二次应被忽略
    emitSessionExpired()
    expect(r1).toHaveBeenCalledTimes(1)
  })
})
