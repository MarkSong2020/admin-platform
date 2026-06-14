import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import MenuFormDialog from './MenuFormDialog.vue'
import { createMenu, type MenuRead } from '@/api/menus'

vi.mock('@/api/menus', () => ({
  createMenu: vi.fn(),
  updateMenu: vi.fn(),
}))

const MENUS: MenuRead[] = [
  {
    id: 1,
    name: '系统管理',
    menu_type: 'M',
    parent_id: null,
    path: 'system',
    component: null,
    perms: null,
    icon: 'setting',
    sort_order: 0,
    visible: true,
    status: 'active',
    created_at: '',
    updated_at: '',
  },
]

function mountDialog(over: Partial<{ editing: MenuRead | null }> = {}): VueWrapper {
  return mount(MenuFormDialog, {
    props: {
      visible: true,
      editing: over.editing ?? null,
      menus: MENUS,
      'onUpdate:visible': () => {},
    },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.mocked(createMenu).mockReset()
  vi.mocked(createMenu).mockResolvedValue(MENUS[0]!)
  document.body.innerHTML = ''
})

/** 取对话框内某 label 的 el-form-item 是否存在（条件渲染断言用）。 */
function hasFormItem(label: string): boolean {
  const items = document.body.querySelectorAll('.el-form-item__label')
  return Array.from(items).some((el) => el.textContent?.includes(label) ?? false)
}

describe('MenuFormDialog 类型联动', () => {
  it('默认 menu_type=M（目录）：显示路由地址/图标，隐藏组件/权限标识', async () => {
    mountDialog()
    await flushPromises()
    expect(hasFormItem('路由地址')).toBe(true)
    expect(hasFormItem('菜单图标')).toBe(true)
    expect(hasFormItem('组件路径')).toBe(false)
    expect(hasFormItem('权限标识')).toBe(false)
  })

  it('选 C（菜单）：显示组件路径/权限标识/路由地址', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    // 选 menu_type=C
    await wrapper.findComponent(MenuFormDialog).vm.$nextTick()
    const radios = document.body.querySelectorAll('.el-radio')
    const cRadio = Array.from(radios).find((r) => r.textContent?.includes('菜单'))
    ;(cRadio as HTMLElement).click()
    await flushPromises()
    expect(hasFormItem('组件路径')).toBe(true)
    expect(hasFormItem('权限标识')).toBe(true)
    expect(hasFormItem('路由地址')).toBe(true)
  })

  it('选 F（按钮）：隐藏路由地址/组件路径/图标，仅留权限标识', async () => {
    mountDialog()
    await flushPromises()
    const radios = document.body.querySelectorAll('.el-radio')
    const fRadio = Array.from(radios).find((r) => r.textContent?.includes('按钮'))
    ;(fRadio as HTMLElement).click()
    await flushPromises()
    expect(hasFormItem('路由地址')).toBe(false)
    expect(hasFormItem('组件路径')).toBe(false)
    expect(hasFormItem('菜单图标')).toBe(false)
    expect(hasFormItem('权限标识')).toBe(true)
  })
})

describe('MenuFormDialog 提交', () => {
  it('F 型提交：隐藏字段强制归零（防 C→F 切换后 path/component/icon 残留污染路由树）', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      form: { menuType: string; name: string; path: string; component: string; icon: string }
      submit: () => Promise<void>
    }
    // 模拟用户先填了 C 的字段、再切回 F：值仍残留在 form，提交时必须按类型裁掉
    vm.form.menuType = 'F'
    vm.form.name = '导出按钮'
    vm.form.path = '/leftover'
    vm.form.component = 'system/x/index'
    vm.form.icon = 'leftover-icon'
    await vm.submit()
    await flushPromises()

    expect(createMenu).toHaveBeenCalledTimes(1)
    expect(vi.mocked(createMenu).mock.calls[0]![0]).toMatchObject({
      menu_type: 'F',
      name: '导出按钮',
      path: '',
      component: null,
      icon: '',
      perms: null,
      visible: true,
    })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })

  it('M 型提交：保留 path/icon，component/perms 归 null', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      form: { menuType: string; name: string; path: string; icon: string }
      submit: () => Promise<void>
    }
    vm.form.menuType = 'M'
    vm.form.name = '系统管理'
    vm.form.path = 'system'
    vm.form.icon = 'setting'
    await vm.submit()
    await flushPromises()

    expect(vi.mocked(createMenu).mock.calls[0]![0]).toMatchObject({
      menu_type: 'M',
      path: 'system',
      icon: 'setting',
      component: null,
      perms: null,
    })
  })
})
