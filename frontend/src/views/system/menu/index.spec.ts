import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import MenuPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listMenus, deleteMenu } from '@/api/menus'
import { ElMessageBox, type MessageBoxData } from 'element-plus'

vi.mock('@/api/menus', () => ({
  listMenus: vi.fn(),
  getMenu: vi.fn(),
  createMenu: vi.fn(),
  updateMenu: vi.fn(),
  deleteMenu: vi.fn(),
}))

const MENUS = [
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
  {
    id: 2,
    name: '用户管理',
    menu_type: 'C',
    parent_id: 1,
    path: 'user',
    component: 'system/user/index',
    perms: 'system:user:list',
    icon: 'user',
    sort_order: 1,
    visible: true,
    status: 'active',
    created_at: '',
    updated_at: '',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(MenuPage, {
    global: {
      plugins: [ElementPlus, pinia],
      directives: { hasPermi },
    },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  // 授全权，按钮可见（mount 与 seed 必须共用同一 pinia）
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listMenus).mockReset()
  vi.mocked(listMenus).mockResolvedValue({
    items: MENUS,
    page: 1,
    size: 100,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(deleteMenu).mockReset()
  document.body.innerHTML = ''
})

describe('菜单管理页', () => {
  it('挂载即拉列表并渲染父子两级（树形）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listMenus).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('系统管理')
    expect(wrapper.text()).toContain('用户管理')
  })

  it('menu_type 以中文标签渲染（目录/菜单）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('目录')
    expect(wrapper.text()).toContain('菜单')
  })

  it('点新增 → 打开表单对话框', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().trim() === '新增')
    expect(addBtn).toBeTruthy()
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增菜单')
  })

  it('删除走二次确认 → deleteMenu', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteMenu).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteMenu).toHaveBeenCalledWith(1)
  })

  it('删除 409 → 提示存在子菜单', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteMenu).mockRejectedValue({
      status: 409,
      code: 'menu.HAS_CHILDREN',
      message: '存在子菜单',
    })
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('存在子菜单，无法删除')
  })
})
