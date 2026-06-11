import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePermissionStore } from './permission'
import { registerSessionExpiryHandler, __resetSessionExpiryForTest } from './session-expiry'
import { emitSessionExpired, __resetSessionForTest } from '@/api/session'

beforeEach(() => {
  setActivePinia(createPinia())
  __resetSessionForTest()
  __resetSessionExpiryForTest()
})

describe('session 失效统一出口', () => {
  it('emit sessionExpired → 清 permission store 权限 + 跳登录', () => {
    const perm = usePermissionStore()
    perm.setPermissions(['system:user:list'])
    expect(perm.has('system:user:list')).toBe(true)

    const redirect = vi.fn()
    registerSessionExpiryHandler({ redirectToLogin: redirect })
    emitSessionExpired()

    expect(perm.has('system:user:list')).toBe(false)
    expect(redirect).toHaveBeenCalledTimes(1)
  })

  it('重复 register 只注册一次订阅者（唯一出口）', () => {
    const r1 = vi.fn()
    registerSessionExpiryHandler({ redirectToLogin: r1 })
    registerSessionExpiryHandler({ redirectToLogin: vi.fn() }) // 第二次应被忽略
    emitSessionExpired()
    expect(r1).toHaveBeenCalledTimes(1)
  })
})
