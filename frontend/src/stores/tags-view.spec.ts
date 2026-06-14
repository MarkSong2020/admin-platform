import { describe, it, expect, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useTagsViewStore } from './tags-view'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('tags-view store', () => {
  it('初始仅含首页 affix 标签', () => {
    const store = useTagsViewStore()
    expect(store.visited).toEqual([{ path: '/home', title: '首页', affix: true }])
  })

  it('addView 入表且按 path 去重', () => {
    const store = useTagsViewStore()
    store.addView({ path: '/system/user', title: '用户管理' })
    store.addView({ path: '/system/user', title: '用户管理（重复）' })
    expect(store.visited).toHaveLength(2)
    expect(store.visited[1]?.path).toBe('/system/user')
  })

  it('removeView 关闭普通标签，affix（首页）不可关', () => {
    const store = useTagsViewStore()
    store.addView({ path: '/system/role', title: '角色管理' })
    store.removeView('/system/role')
    expect(store.visited.map((v) => v.path)).toEqual(['/home'])
    store.removeView('/home')
    expect(store.visited.map((v) => v.path)).toEqual(['/home'])
  })

  it('closeOthers 仅保留 affix 与指定 path', () => {
    const store = useTagsViewStore()
    store.addView({ path: '/a', title: 'A' })
    store.addView({ path: '/b', title: 'B' })
    store.closeOthers('/a')
    expect(store.visited.map((v) => v.path).sort()).toEqual(['/a', '/home'])
  })

  it('closeAll 仅留 affix；reset 复位为首页', () => {
    const store = useTagsViewStore()
    store.addView({ path: '/a', title: 'A' })
    store.addView({ path: '/b', title: 'B' })
    store.closeAll()
    expect(store.visited.map((v) => v.path)).toEqual(['/home'])
    store.addView({ path: '/c', title: 'C' })
    store.reset()
    expect(store.visited).toEqual([{ path: '/home', title: '首页', affix: true }])
  })
})
