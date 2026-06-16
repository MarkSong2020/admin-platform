import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import RoleDeptDialog from './RoleDeptDialog.vue'
import { listDepts, type DeptRead } from '@/api/depts'
import { getRoleDepts, setRoleDepts } from '@/api/roles'

// 跨文件依赖：listDepts 来自 @/api/depts，单测 mock 不依赖真实文件。
vi.mock('@/api/depts', () => ({ listDepts: vi.fn() }))
vi.mock('@/api/roles', () => ({
  getRoleDepts: vi.fn(),
  setRoleDepts: vi.fn(),
}))

// 平铺部门（parent_id 全 null）→ 无半选父，getCheckedKeys 精确等于勾选叶子，断言确定。
const DEPTS: DeptRead[] = [
  {
    id: 1,
    code: 'HQ',
    name: '总部',
    parent_id: null,
    leader: null,
    phone: null,
    email: null,
    sort_order: 0,
    status: 'active',
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    code: 'RD',
    name: '研发部',
    parent_id: null,
    leader: null,
    phone: null,
    email: null,
    sort_order: 1,
    status: 'active',
    created_at: '',
    updated_at: '',
  },
]

function mountDialog(roleId: number | null = 7) {
  return mount(RoleDeptDialog, {
    props: { roleId, visible: false },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.mocked(listDepts).mockReset()
  vi.mocked(listDepts).mockResolvedValue({
    items: DEPTS,
    page: 1,
    size: 100,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(getRoleDepts).mockReset()
  vi.mocked(getRoleDepts).mockResolvedValue({ ids: [2] })
  vi.mocked(setRoleDepts).mockReset()
  vi.mocked(setRoleDepts).mockResolvedValue(undefined)
  document.body.innerHTML = ''
})

describe('RoleDeptDialog', () => {
  it('打开时并发加载全部部门 + 角色已绑部门，并渲染部门名', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listDepts).toHaveBeenCalledWith({ page: 1, size: 100 })
    expect(getRoleDepts).toHaveBeenCalledWith(7)
    expect(document.body.textContent).toContain('总部')
    expect(document.body.textContent).toContain('研发部')
  })

  it('确定 → setRoleDepts 携带勾选部门 id 后关闭', async () => {
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
    expect(setRoleDepts).toHaveBeenCalledTimes(1)
    const [roleId, ids] = vi.mocked(setRoleDepts).mock.calls[0]!
    expect(roleId).toBe(7)
    expect(ids).toContain(2)
    // 平铺树无半选父，未勾选的 id=1 不得纳入
    expect(ids).not.toContain(1)
    // 提交成功后关闭：visible 末次置 false
    expect(wrapper.emitted('update:visible')?.at(-1)).toEqual([false])
  })

  it('roleId 为 null 时不加载', async () => {
    const wrapper = mountDialog(null)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listDepts).not.toHaveBeenCalled()
    expect(getRoleDepts).not.toHaveBeenCalled()
  })

  it('roleId 为 null 时 submit 直接早退，不调用 setRoleDepts', async () => {
    const wrapper = mountDialog(null)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const vm = wrapper.vm as unknown as { submit: () => Promise<void> }
    await vm.submit()
    expect(setRoleDepts).not.toHaveBeenCalled()
  })

  it('加载失败 → ElMessage.error 提示', async () => {
    const errSpy = vi.spyOn(ElMessage, 'error')
    vi.mocked(getRoleDepts).mockRejectedValue(new Error('boom'))
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(errSpy).toHaveBeenCalled()
    errSpy.mockRestore()
  })
})
