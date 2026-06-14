import { describe, it, expect, beforeEach } from 'vitest'
import { defineComponent, h, withDirectives, type DirectiveBinding, type ObjectDirective } from 'vue'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { hasPermi, type HasPermiValue } from './has-permi'
import { usePermissionStore } from '@/stores/permission'

/** 挂一个带 v-hasPermi 按钮的最小组件（render 函数避免运行时模板编译）。 */
function mountWithPerms(perms: string[], value: HasPermiValue) {
  const pinia: Pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(perms)
  const Comp = defineComponent({
    render() {
      return h('div', [withDirectives(h('button', '新增'), [[hasPermi, value]])])
    },
  })
  return mount(Comp, { global: { plugins: [pinia] } })
}

beforeEach(() => {
  setActivePinia(undefined)
})

describe('v-hasPermi 指令', () => {
  it('有权限 → 元素保留', () => {
    const wrapper = mountWithPerms(['system:user:add'], 'system:user:add')
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('无权限 → 元素从 DOM 移除', () => {
    const wrapper = mountWithPerms(['system:user:list'], 'system:user:add')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it("超管 '*:*:*' 通配 → 恒显", () => {
    const wrapper = mountWithPerms(['*:*:*'], 'system:user:add')
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('数组任一命中 → 显示', () => {
    const wrapper = mountWithPerms(['system:user:edit'], ['system:user:add', 'system:user:edit'])
    expect(wrapper.find('button').exists()).toBe(true)
  })

  it('数组全不命中 → 移除', () => {
    const wrapper = mountWithPerms(['system:role:list'], ['system:user:add', 'system:user:edit'])
    expect(wrapper.find('button').exists()).toBe(false)
  })
})

/** 直接调用 mounted（实现只读 binding.value）以确定性断言 fail-fast 抛错，绕过 Vue 错误边界。 */
function invokeMounted(perms: string[], value: unknown): void {
  setActivePinia(createPinia())
  usePermissionStore().setPermissions(perms)
  const el = document.createElement('button')
  const binding = { value } as unknown as DirectiveBinding<HasPermiValue>
  const dir = hasPermi as ObjectDirective<HTMLElement, HasPermiValue>
  dir.mounted!(el, binding, {} as never, null as never)
}

describe('v-hasPermi fail-fast（误配抛错，不静默隐藏）', () => {
  it('权限码为 null → 抛错', () => {
    expect(() => invokeMounted(['*:*:*'], null)).toThrow('需要权限码')
  })

  it('权限码为 undefined → 抛错', () => {
    expect(() => invokeMounted(['*:*:*'], undefined)).toThrow('需要权限码')
  })

  it('权限码数组为空 → 抛错', () => {
    expect(() => invokeMounted(['*:*:*'], [])).toThrow('不能为空')
  })
})
