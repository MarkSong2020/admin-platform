import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import RoleFormDialog from './RoleFormDialog.vue'
import { createRole, updateRole, type RoleRead } from '@/api/roles'

vi.mock('@/api/roles', () => ({
  createRole: vi.fn(),
  updateRole: vi.fn(),
}))

const ROLE: RoleRead = {
  id: 2,
  code: 'auditor',
  name: '审计员',
  data_scope: 'custom_dept',
  sort_order: 1,
  status: 'active',
  created_at: '',
  updated_at: '',
}

function mountDialog(editing: RoleRead | null = null): VueWrapper {
  return mount(RoleFormDialog, {
    props: { visible: false, editing, 'onUpdate:visible': () => {} },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

interface FormVm {
  form: { code: string; name: string; dataScope: string; sortOrder: number; status: string }
  submit: () => Promise<void>
}

beforeEach(() => {
  vi.mocked(createRole).mockReset()
  vi.mocked(createRole).mockResolvedValue(ROLE)
  vi.mocked(updateRole).mockReset()
  vi.mocked(updateRole).mockResolvedValue(ROLE)
  document.body.innerHTML = ''
})

describe('RoleFormDialog 新增', () => {
  it('填表提交 → createRole 全字段，emit saved', async () => {
    const wrapper = mountDialog(null)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const vm = wrapper.vm as unknown as FormVm
    vm.form.code = 'ops'
    vm.form.name = '运维'
    vm.form.dataScope = 'self_dept'
    vm.form.sortOrder = 3
    await vm.submit()
    await flushPromises()
    expect(createRole).toHaveBeenCalledWith({
      code: 'ops',
      name: '运维',
      data_scope: 'self_dept',
      sort_order: 3,
      status: 'active',
    })
    expect(wrapper.emitted('saved')).toBeTruthy()
  })
})

describe('RoleFormDialog 编辑', () => {
  it('回填后提交 → updateRole 不含 code（后端禁改）', async () => {
    const wrapper = mountDialog(ROLE)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const vm = wrapper.vm as unknown as FormVm
    expect(vm.form.code).toBe('auditor')
    vm.form.name = '审计员改'
    await vm.submit()
    await flushPromises()
    expect(updateRole).toHaveBeenCalledTimes(1)
    const [id, payload] = vi.mocked(updateRole).mock.calls[0]!
    expect(id).toBe(2)
    expect(payload).toEqual({
      name: '审计员改',
      data_scope: 'custom_dept',
      sort_order: 1,
      status: 'active',
    })
    expect('code' in payload).toBe(false)
  })
})
