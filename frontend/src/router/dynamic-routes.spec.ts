import { describe, it, expect } from 'vitest'
import { toRoutes, SHELL_ALLOWLIST, type RouterNode } from './dynamic-routes'

const sample: RouterNode[] = [
  {
    name: 'System', path: '/system', component: 'Layout', hidden: false,
    redirect: 'noRedirect', alwaysShow: true,
    meta: { title: '系统管理', icon: 'system', noCache: false, link: null },
    children: [
      {
        name: 'User', path: 'user', component: 'system/user/index', hidden: false,
        redirect: null, alwaysShow: false,
        meta: { title: '用户管理', icon: 'user', noCache: false, link: null },
      },
    ],
  },
]

describe('toRoutes', () => {
  it('Layout/ParentView 映射到壳，页面 component 映射到 views', () => {
    const routes = toRoutes(sample)
    const root = routes[0]!
    expect(root.path).toBe('/system')
    expect(SHELL_ALLOWLIST).toContain('Layout')
    const child = root.children?.[0]!
    expect(child.path).toBe('user')
    expect(typeof child.component).toBe('function')
  })

  it('未知 component 抛错（fail fast，不静默忽略）', () => {
    const badChild: RouterNode = { ...sample[0]!.children![0]!, component: 'no/such/page' }
    const bad: RouterNode[] = [{ ...sample[0]!, children: [badChild] }]
    expect(() => toRoutes(bad)).toThrow(/no\/such\/page/)
  })
})
