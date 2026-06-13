import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import RoleMenuDialog from './RoleMenuDialog.vue'
import { listMenus } from '@/api/menus'
import { getRoleMenus, setRoleMenus } from '@/api/roles'

// 跨文件依赖：listMenus 来自 @/api/menus（menu 页提供导出），单测 mock 不依赖真实文件。
vi.mock('@/api/menus', () => ({ listMenus: vi.fn() }))
vi.mock('@/api/roles', () => ({
  getRoleMenus: vi.fn(),
  setRoleMenus: vi.fn(),
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
    icon: '',
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
    icon: '',
    sort_order: 0,
    visible: true,
    status: 'active',
    created_at: '',
    updated_at: '',
  },
]

function mountDialog() {
  return mount(RoleMenuDialog, {
    props: { roleId: 7, visible: false },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.mocked(listMenus).mockReset()
  vi.mocked(listMenus).mockResolvedValue({
    items: MENUS,
    page: 1,
    size: 100,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(getRoleMenus).mockReset()
  vi.mocked(getRoleMenus).mockResolvedValue({ ids: [2] })
  vi.mocked(setRoleMenus).mockReset()
  vi.mocked(setRoleMenus).mockResolvedValue(undefined)
  document.body.innerHTML = ''
})

describe('RoleMenuDialog', () => {
  it('打开时并发加载全部菜单 + 角色已选菜单', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listMenus).toHaveBeenCalledWith({ page: 1, size: 100 })
    expect(getRoleMenus).toHaveBeenCalledWith(7)
    // 菜单名渲染进树
    expect(document.body.textContent).toContain('系统管理')
    expect(document.body.textContent).toContain('用户管理')
  })

  it('确定 → setRoleMenus 携带勾选 id 后关闭', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    // el-dialog footer 经 append-to-body teleport 到 document.body，从全局取「确定」按钮。
    const okBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('确定'),
    )
    expect(okBtn).toBeTruthy()
    okBtn!.click()
    await flushPromises()
    expect(setRoleMenus).toHaveBeenCalledTimes(1)
    const [roleId, ids] = vi.mocked(setRoleMenus).mock.calls[0]!
    expect(roleId).toBe(7)
    // 已选叶子 id=2 应在提交集合内（半选父 id=1 也会随级联纳入）
    expect(ids).toContain(2)
  })

  it('roleId 为 null 时不加载', async () => {
    const wrapper = mount(RoleMenuDialog, {
      props: { roleId: null, visible: false },
      global: { plugins: [ElementPlus] },
      attachTo: document.body,
    })
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listMenus).not.toHaveBeenCalled()
    expect(getRoleMenus).not.toHaveBeenCalled()
  })
})
