/**
 * composition root 行为测试（spec §6）：bootstrap 时序 / 守卫 / 动态路由装配 / session 失效出口。
 * mock api/auth（getInfo/getRouters）；session 用真实模块 + 注入 refresh 实现。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import router, {
  bootstrap,
  installDynamicRoutes,
  resetDynamicRoutes,
  __resetBootstrapForTest,
} from './index'
import {
  SessionExpiredError,
  __resetSessionForTest,
  __setRefreshImplForTest,
} from '@/api/session'
import { registerSessionExpiryHandler, __resetSessionExpiryForTest } from '@/stores/session-expiry'
import { usePermissionStore } from '@/stores/permission'
import { useMenuStore } from '@/stores/menu'
import {
  fetchUserInfo,
  fetchRouters,
  type RouterVO,
  type UserInfoResponse,
} from '@/api/auth'

vi.mock('@/api/auth', () => ({
  fetchUserInfo: vi.fn(),
  fetchRouters: vi.fn(),
}))

/** 与 api/session.ts 的 REFRESH_STORAGE_KEY 一致（直写 sessionStorage 模拟"有 refresh 的刷新"）。 */
const REFRESH_KEY = 'admin.refresh'

const userInfoFixture: UserInfoResponse = {
  user: {
    id: 1,
    username: 'admin',
    nickname: '管理员',
    dept_id: null,
    status: 'active',
    is_super_admin: true,
  },
  roles: ['admin'],
  permissions: ['*:*:*'],
}

const routersFixture: RouterVO[] = [
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
]

beforeEach(async () => {
  vi.clearAllMocks()
  setActivePinia(createPinia())
  sessionStorage.clear()
  __resetSessionForTest()
  __resetSessionExpiryForTest()
  __resetBootstrapForTest()
  resetDynamicRoutes()
  // 对齐 main.ts：bootstrap 首次 refresh 之前注册唯一订阅者
  registerSessionExpiryHandler({
    resetDynamicRoutes,
    redirectToLogin: () => {
      void router.replace({ name: 'login' })
    },
  })
  vi.mocked(fetchUserInfo).mockResolvedValue(userInfoFixture)
  vi.mocked(fetchRouters).mockResolvedValue(routersFixture)
  // 回到已知公开路由，隔离上一条用例的导航状态
  await router.replace({ name: 'login' })
})

describe('守卫 + bootstrap 时序', () => {
  it('深链刷新：有 refresh → bootstrap 走完 → 放行目标动态路由', async () => {
    sessionStorage.setItem(REFRESH_KEY, 'refresh-1')
    __setRefreshImplForTest(async () => ({ accessToken: 'a1', refreshToken: 'r2' }))

    await router.push('/system/user')

    expect(router.currentRoute.value.name).toBe('User')
    expect(fetchUserInfo).toHaveBeenCalledTimes(1)
    expect(fetchRouters).toHaveBeenCalledTimes(1)
  })

  it('refresh 失败：emit sessionExpired → 清 store + reset 动态路由 + 跳登录', async () => {
    sessionStorage.setItem(REFRESH_KEY, 'stale-refresh')
    __setRefreshImplForTest(async () => {
      throw new SessionExpiredError('refresh 401')
    })
    // 预装配 + 预置权限，验证失效后被清空
    installDynamicRoutes(routersFixture)
    const perm = usePermissionStore()
    perm.setPermissions(['system:user:list'])
    expect(router.hasRoute('User')).toBe(true)

    await router.push('/system/user')

    expect(router.currentRoute.value.name).toBe('login')
    expect(perm.has('system:user:list')).toBe(false)
    expect(useMenuStore().loaded).toBe(false)
    expect(router.hasRoute('User')).toBe(false)
    expect(sessionStorage.getItem(REFRESH_KEY)).toBeNull()
  })

  it('无 refresh：守卫 redirect /login?redirect=<目标>', async () => {
    await router.push('/system/user')

    expect(router.currentRoute.value.name).toBe('login')
    expect(router.currentRoute.value.query.redirect).toBe('/system/user')
  })

  it('守卫等待 bootstrap 完成才放行（竞态）', async () => {
    sessionStorage.setItem(REFRESH_KEY, 'refresh-1')
    let resolveRefresh:
      | ((tokens: { accessToken: string; refreshToken: string }) => void)
      | undefined
    __setRefreshImplForTest(
      () =>
        new Promise((resolve) => {
          resolveRefresh = resolve
        }),
    )

    const nav = router.push('/system/user')
    await new Promise((resolve) => setTimeout(resolve))
    // refresh 未完成：动态路由不可见、导航未放行
    expect(router.hasRoute('User')).toBe(false)
    expect(router.currentRoute.value.name).toBe('login')

    resolveRefresh!({ accessToken: 'a1', refreshToken: 'r2' })
    await nav

    expect(router.currentRoute.value.name).toBe('User')
  })
})

describe('bootstrap single-run', () => {
  it('并发调用复用同一 promise，refresh/getInfo/getRouters 各只发一次', async () => {
    sessionStorage.setItem(REFRESH_KEY, 'refresh-1')
    const refreshSpy = vi.fn(async () => ({ accessToken: 'a1', refreshToken: 'r2' }))
    __setRefreshImplForTest(refreshSpy)

    await Promise.all([bootstrap(), bootstrap()])
    expect(refreshSpy).toHaveBeenCalledTimes(1)
    expect(fetchUserInfo).toHaveBeenCalledTimes(1)
    expect(fetchRouters).toHaveBeenCalledTimes(1)

    // 完成后再调不重跑
    await bootstrap()
    expect(refreshSpy).toHaveBeenCalledTimes(1)
  })
})

describe('动态路由装配/重置', () => {
  it('install 后路由可解析，reset 后移除；reset 再 install 幂等无 name 冲突', () => {
    installDynamicRoutes(routersFixture)
    expect(router.hasRoute('System')).toBe(true)
    expect(router.hasRoute('User')).toBe(true)
    expect(router.resolve('/system/user').name).toBe('User')

    resetDynamicRoutes()
    expect(router.hasRoute('System')).toBe(false)
    expect(router.hasRoute('User')).toBe(false)

    // 重复 install 前先 reset：不报 name 冲突
    installDynamicRoutes(routersFixture)
    resetDynamicRoutes()
    installDynamicRoutes(routersFixture)
    expect(router.hasRoute('User')).toBe(true)
  })

  it('reset 可重复调用（无已装配路由时为 no-op）', () => {
    expect(() => {
      resetDynamicRoutes()
      resetDynamicRoutes()
    }).not.toThrow()
  })
})
