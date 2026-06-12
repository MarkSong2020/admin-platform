import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUserInfoStore } from './user-info'
import { usePermissionStore } from './permission'
import { fetchUserInfo } from '@/api/auth'

vi.mock('@/api/auth', () => ({
  fetchUserInfo: vi.fn(async () => ({
    user: {
      id: 1,
      username: 'admin',
      nickname: '管理员',
      dept_id: null,
      status: 'active',
      is_super_admin: false,
    },
    roles: ['admin'],
    permissions: ['system:user:list', 'system:user:query'],
  })),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(fetchUserInfo).mockClear()
})

describe('user-info store', () => {
  it('loadUserInfo → user/roles 入本 store，permissions 写入 permission store', async () => {
    const store = useUserInfoStore()
    const perm = usePermissionStore()
    await store.loadUserInfo()
    expect(fetchUserInfo).toHaveBeenCalledTimes(1)
    expect(store.user?.username).toBe('admin')
    expect(store.roles).toEqual(['admin'])
    expect(perm.has('system:user:list')).toBe(true)
    expect(perm.has('system:user:remove')).toBe(false)
  })

  it('reset → 清空 user/roles', async () => {
    const store = useUserInfoStore()
    await store.loadUserInfo()
    store.reset()
    expect(store.user).toBeNull()
    expect(store.roles).toEqual([])
  })
})
