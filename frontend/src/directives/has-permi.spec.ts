import { describe, it, expect, beforeEach } from 'vitest'
import { defineComponent, h, withDirectives } from 'vue'
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
