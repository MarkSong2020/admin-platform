/**
 * 主动登出出口测试：注入回调装配、清三 store + reset 路由 + 跳登录、未注册 fail fast。
 * mock api/auth.logout（best-effort 撤销），store 用真实 Pinia 实例。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { performLogout, registerLogoutDeps, __resetLogoutForTest } from './logout'
import { logout as apiLogout } from '@/api/auth'
import { usePermissionStore } from './permission'
import { useUserInfoStore } from './user-info'
import { useMenuStore } from './menu'

vi.mock('@/api/auth', () => ({ logout: vi.fn() }))

beforeEach(() => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  __resetLogoutForTest()
  vi.mocked(apiLogout).mockResolvedValue(undefined)
})

describe('performLogout', () => {
  it('撤销后端 → 清三 store → reset 动态路由 → 跳登录', async () => {
    const deps = { resetDynamicRoutes: vi.fn(), redirectToLogin: vi.fn() }
    registerLogoutDeps(deps)
    usePermissionStore().setPermissions(['system:user:list'])
    useUserInfoStore().$patch({ roles: ['admin'] })
    useMenuStore().$patch({ loaded: true })

    await performLogout()

    expect(apiLogout).toHaveBeenCalledTimes(1)
    expect(usePermissionStore().has('system:user:list')).toBe(false)
    expect(useUserInfoStore().roles).toEqual([])
    expect(useMenuStore().loaded).toBe(false)
    expect(deps.resetDynamicRoutes).toHaveBeenCalledTimes(1)
    expect(deps.redirectToLogin).toHaveBeenCalledTimes(1)
  })

  it('未注册 deps → fail fast 抛错（不静默清完 store 却不跳转）', async () => {
    await expect(performLogout()).rejects.toThrow(/logout deps 未注册/)
  })
})
