import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useMenuStore } from './menu'
import { fetchRouters } from '@/api/auth'

vi.mock('@/api/auth', () => ({
  fetchRouters: vi.fn(async () => [
    {
      name: 'System',
      path: '/system',
      component: 'Layout',
      redirect: 'noRedirect',
      hidden: false,
      alwaysShow: true,
      meta: { title: '系统管理', icon: 'system', noCache: false, link: null },
      children: [
        {
          name: 'User',
          path: 'user',
          component: 'system/user/index',
          redirect: null,
          hidden: false,
          alwaysShow: false,
          meta: { title: '用户管理', icon: 'user', noCache: false, link: null },
        },
      ],
    },
  ]),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(fetchRouters).mockClear()
})

describe('menu store', () => {
  it('loadRouters → 存菜单树并置 loaded', async () => {
    const store = useMenuStore()
    expect(store.loaded).toBe(false)
    await store.loadRouters()
    expect(fetchRouters).toHaveBeenCalledTimes(1)
    expect(store.routers).toHaveLength(1)
    expect(store.routers[0]!.children).toHaveLength(1)
    expect(store.routers[0]!.children![0]!.component).toBe('system/user/index')
    expect(store.loaded).toBe(true)
  })

  it('reset → 清空树与 loaded', async () => {
    const store = useMenuStore()
    await store.loadRouters()
    store.reset()
    expect(store.routers).toEqual([])
    expect(store.loaded).toBe(false)
  })
})
