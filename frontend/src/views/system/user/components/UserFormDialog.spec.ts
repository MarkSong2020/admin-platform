import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import UserFormDialog from './UserFormDialog.vue'
import { createUser, updateUser, type UserRead } from '@/api/users'

vi.mock('@/api/users', () => ({
  createUser: vi.fn(),
  updateUser: vi.fn(),
}))

const USER: UserRead = {
  id: 2,
  username: 'bob',
  nickname: '小明',
  dept_id: 3,
  status: 'active',
  is_super_admin: false,
}

function mountDialog(editing: UserRead | null = null): VueWrapper {
  return mount(UserFormDialog, {
    props: { visible: false, editing, 'onUpdate:visible': () => {} },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

interface FormVm {
  form: { username: string; password: string; nickname: string; deptId: number | null; status: string }
  submit: () => Promise<void>
}

beforeEach(() => {
  vi.mocked(createUser).mockReset()
  vi.mocked(createUser).mockResolvedValue(USER)
  vi.mocked(updateUser).mockReset()
  vi.mocked(updateUser).mockResolvedValue(USER)
  document.body.innerHTML = ''
})

describe('UserFormDialog 新增', () => {
  it('填表提交 → createUser（仅 username/password/nickname/dept_id），emit saved', async () => {
    const wrapper = mountDialog(null)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const vm = wrapper.vm as unknown as FormVm
    vm.form.username = 'alice'
    vm.form.password = 'pw12345678'
    vm.form.nickname = '爱丽丝'
    vm.form.deptId = 4
    await vm.submit()
    await flushPromises()
    expect(createUser).toHaveBeenCalledWith({
      username: 'alice',
      password: 'pw12345678',
      nickname: '爱丽丝',
      dept_id: 4,
    })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })
})

describe('UserFormDialog 编辑', () => {
  it('回填后提交且密码留空 → updateUser 不带 password', async () => {
    const wrapper = mountDialog(USER)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const vm = wrapper.vm as unknown as FormVm
    // 回填校验：username 来自 editing，password 清空
    expect(vm.form.username).toBe('bob')
    expect(vm.form.password).toBe('')
    vm.form.nickname = '小明改'
    await vm.submit()
    await flushPromises()
    expect(updateUser).toHaveBeenCalledTimes(1)
    const [id, payload] = vi.mocked(updateUser).mock.calls[0]!
    expect(id).toBe(2)
    expect(payload).toEqual({ nickname: '小明改', dept_id: 3, status: 'active' })
    expect('password' in payload).toBe(false)
  })

  it('编辑时填了密码 → updateUser 带 password', async () => {
    const wrapper = mountDialog(USER)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const vm = wrapper.vm as unknown as FormVm
    vm.form.password = 'newpw12345'
    await vm.submit()
    await flushPromises()
    const [, payload] = vi.mocked(updateUser).mock.calls[0]!
    expect((payload as { password?: string }).password).toBe('newpw12345')
  })
})
