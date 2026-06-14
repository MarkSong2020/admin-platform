import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import UserPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listUsers, createUser, deleteUser, getUserRoles } from '@/api/users'
import { listRoles } from '@/api/roles'
import { ElMessageBox, type MessageBoxData } from 'element-plus'

vi.mock('@/api/users', () => ({
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  deleteUser: vi.fn(),
  getUserRoles: vi.fn(),
  getUserPosts: vi.fn(),
  setUserRoles: vi.fn(),
  setUserPosts: vi.fn(),
}))

vi.mock('@/api/roles', () => ({ listRoles: vi.fn() }))
vi.mock('@/api/posts', () => ({ listPosts: vi.fn() }))

const USERS = [
  {
    id: 1,
    username: 'admin',
    nickname: '管理员',
    dept_id: null,
    status: 'active',
    is_super_admin: true,
  },
  {
    id: 2,
    username: 'bob',
    nickname: '小明',
    dept_id: 3,
    status: 'disabled',
    is_super_admin: false,
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(UserPage, {
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
  // 授全权，按钮可见（mount 与 seed 必须共用同一 pinia，否则 v-hasPermi 读空权限集移除按钮）
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listUsers).mockReset()
  vi.mocked(listUsers).mockResolvedValue({
    items: USERS,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(createUser).mockReset()
  vi.mocked(deleteUser).mockReset()
  vi.mocked(getUserRoles).mockReset()
  vi.mocked(listRoles).mockReset()
  document.body.innerHTML = ''
})

describe('用户管理页', () => {
  it('挂载即拉列表并渲染行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listUsers).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('小明')
  })

  it('点新增 → 打开表单对话框', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    expect(addBtn).toBeTruthy()
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增用户')
  })

  it('搜索栏查询 → listUsers 带 keyword 且回第 1 页', async () => {
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(listUsers).mockClear()
    await wrapper.find('input').setValue('bob')
    const queryBtn = wrapper.findAll('button').find((b) => b.text().includes('查询'))
    await queryBtn!.trigger('click')
    await flushPromises()
    expect(listUsers).toHaveBeenCalledWith(
      expect.objectContaining({ page: 1, keyword: 'bob' }),
    )
  })

  it('删除走二次确认 → deleteUser', async () => {
    const confirmSpy = vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteUser).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteUser).toHaveBeenCalledWith(1)
  })

  it('分配角色对话框打开时加载已选角色 + 全部角色', async () => {
    vi.mocked(getUserRoles).mockResolvedValue({ ids: [10] })
    vi.mocked(listRoles).mockResolvedValue({
      items: [{ id: 10, code: 'admin', name: '管理员', data_scope: 'all', sort_order: 0, status: 'active', created_at: '', updated_at: '' }],
      page: 1,
      size: 100,
      total: 1,
      total_pages: 1,
    })
    const wrapper = mountPage()
    await flushPromises()
    const roleBtn = wrapper.findAll('button').find((b) => b.text().includes('分配角色'))
    await roleBtn!.trigger('click')
    await flushPromises()
    expect(getUserRoles).toHaveBeenCalledWith(1)
    expect(listRoles).toHaveBeenCalledTimes(1)
  })
})
