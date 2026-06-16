import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import UserRolesDialog from './UserRolesDialog.vue'
import { listRoles, type RoleRead } from '@/api/roles'
import { getUserRoles, setUserRoles } from '@/api/users'

vi.mock('@/api/roles', () => ({ listRoles: vi.fn() }))
vi.mock('@/api/users', () => ({
  getUserRoles: vi.fn(),
  setUserRoles: vi.fn(),
}))

const ROLES: RoleRead[] = [
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
    status: 'active',
    created_at: '',
    updated_at: '',
  },
]

function mountDialog(userId: number | null = 5) {
  return mount(UserRolesDialog, {
    props: { userId, visible: false },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.mocked(listRoles).mockReset()
  vi.mocked(listRoles).mockResolvedValue({
    items: ROLES,
    page: 1,
    size: 100,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(getUserRoles).mockReset()
  vi.mocked(getUserRoles).mockResolvedValue({ ids: [2] })
  vi.mocked(setUserRoles).mockReset()
  vi.mocked(setUserRoles).mockResolvedValue(undefined)
  document.body.innerHTML = ''
})

describe('UserRolesDialog', () => {
  it('打开时并发加载全部角色 + 用户已绑角色', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listRoles).toHaveBeenCalledWith({ page: 1, size: 100 })
    expect(getUserRoles).toHaveBeenCalledWith(5)
    const vm = wrapper.vm as unknown as {
      options: { key: number; label: string }[]
      selected: number[]
    }
    expect(vm.options).toEqual([
      { key: 1, label: '管理员（admin）' },
      { key: 2, label: '审计员（auditor）' },
    ])
    expect(vm.selected).toEqual([2])
  })

  it('确定 → setUserRoles 携带已选角色后关闭', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const okBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('确定'),
    )
    okBtn!.click()
    await flushPromises()
    expect(setUserRoles).toHaveBeenCalledWith(5, [2])
    expect(wrapper.emitted('update:visible')?.at(-1)).toEqual([false])
  })

  it('userId 为 null 时不加载，submit 早退', async () => {
    const wrapper = mountDialog(null)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listRoles).not.toHaveBeenCalled()
    const vm = wrapper.vm as unknown as { submit: () => Promise<void> }
    await vm.submit()
    expect(setUserRoles).not.toHaveBeenCalled()
  })

  it('分配失败 → ElMessage.error', async () => {
    const errSpy = vi.spyOn(ElMessage, 'error')
    vi.mocked(setUserRoles).mockRejectedValue(new Error('boom'))
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const vm = wrapper.vm as unknown as { submit: () => Promise<void> }
    await vm.submit()
    expect(errSpy).toHaveBeenCalled()
    errSpy.mockRestore()
  })
})
