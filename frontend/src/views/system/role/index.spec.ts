import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import RolePage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listRoles, deleteRole } from '@/api/roles'
import { ElMessageBox, type MessageBoxData } from 'element-plus'

vi.mock('@/api/roles', () => ({
  listRoles: vi.fn(),
  createRole: vi.fn(),
  updateRole: vi.fn(),
  deleteRole: vi.fn(),
  getRoleMenus: vi.fn(),
  setRoleMenus: vi.fn(),
  getRoleDepts: vi.fn(),
  setRoleDepts: vi.fn(),
}))
// 子对话框跨文件依赖的 menus / depts API（菜单/部门树），单测一律 mock，
// 不依赖真实 @/api/menus 文件是否就位。
vi.mock('@/api/menus', () => ({ listMenus: vi.fn() }))
vi.mock('@/api/depts', () => ({ listDepts: vi.fn() }))

const ROLES = [
  {
    id: 1,
    code: 'admin',
    name: '管理员',
    data_scope: 'all',
    sort_order: 0,
    status: 'active',
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    code: 'auditor',
    name: '审计员',
    data_scope: 'custom_dept',
    sort_order: 1,
    status: 'disabled',
    created_at: '',
    updated_at: '',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(RolePage, {
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
  vi.mocked(listRoles).mockReset()
  vi.mocked(listRoles).mockResolvedValue({
    items: ROLES,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(deleteRole).mockReset()
  document.body.innerHTML = ''
})

describe('角色管理页', () => {
  it('挂载即拉列表并渲染行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listRoles).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('审计员')
  })

  it('渲染 data_scope 中文标签', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('全部数据权限')
    expect(wrapper.text()).toContain('自定义数据权限')
  })

  it('点新增 → 打开表单对话框', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    expect(addBtn).toBeTruthy()
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增角色')
  })

  it('搜索栏查询 → listRoles 带 keyword 且回第 1 页', async () => {
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(listRoles).mockClear()
    await wrapper.find('input').setValue('admin')
    const queryBtn = wrapper.findAll('button').find((b) => b.text().includes('查询'))
    await queryBtn!.trigger('click')
    await flushPromises()
    expect(listRoles).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, keyword: 'admin' }),
    )
  })

  it('删除走二次确认 → deleteRole', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteRole).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteRole).toHaveBeenCalledWith(1)
  })
})
