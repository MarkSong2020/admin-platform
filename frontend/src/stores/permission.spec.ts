import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { usePermissionStore } from './permission'

beforeEach(() => {
  setActivePinia(createPinia())
})

describe('permission store（按钮权限判定核心）', () => {
  it('精确命中：拥有该码 → has=true，未拥有 → false', () => {
    const store = usePermissionStore()
    store.setPermissions(['system:user:list'])
    expect(store.has('system:user:list')).toBe(true)
    expect(store.has('system:user:add')).toBe(false)
  })

  it("超管 '*:*:*' 通配命中任意权限码", () => {
    const store = usePermissionStore()
    store.setPermissions(['*:*:*'])
    expect(store.has('system:user:add')).toBe(true)
    expect(store.has('monitor:job:run')).toBe(true)
    expect(store.has('anything:at:all')).toBe(true)
  })

  it('setPermissions 为覆盖式替换（非累加）', () => {
    const store = usePermissionStore()
    store.setPermissions(['a:b:c'])
    store.setPermissions(['x:y:z'])
    expect(store.has('a:b:c')).toBe(false)
    expect(store.has('x:y:z')).toBe(true)
  })

  it('reset 清空：含通配的超管态也被彻底清除（登出/失效复用）', () => {
    const store = usePermissionStore()
    store.setPermissions(['*:*:*'])
    store.reset()
    expect(store.has('*:*:*')).toBe(false)
    expect(store.has('system:user:list')).toBe(false)
  })
})
