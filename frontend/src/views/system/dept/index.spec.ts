import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import DeptPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listDepts, deleteDept } from '@/api/depts'
import { ElMessageBox, type MessageBoxData } from 'element-plus'

vi.mock('@/api/depts', () => ({
  listDepts: vi.fn(),
  getDept: vi.fn(),
  createDept: vi.fn(),
  updateDept: vi.fn(),
  deleteDept: vi.fn(),
}))

const DEPTS = [
  {
    id: 1,
    code: 'root',
    name: '总公司',
    parent_id: null,
    leader: '张总',
    phone: '010-0001',
    email: null,
    sort_order: 0,
    status: 'active',
    created_at: '',
    updated_at: '',
  },
  {
    id: 2,
    code: 'rd',
    name: '研发部',
    parent_id: 1,
    leader: '李工',
    phone: '010-0002',
    email: null,
    sort_order: 1,
    status: 'disabled',
    created_at: '',
    updated_at: '',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(DeptPage, {
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
  vi.mocked(listDepts).mockReset()
  vi.mocked(listDepts).mockResolvedValue({
    items: DEPTS,
    page: 1,
    size: 100,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(deleteDept).mockReset()
  document.body.innerHTML = ''
})

describe('部门管理页', () => {
  it('挂载即拉列表并渲染父子两级（树形）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listDepts).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('总公司')
    expect(wrapper.text()).toContain('研发部')
  })

  it('点新增 → 打开表单对话框', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    expect(addBtn).toBeTruthy()
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增部门')
  })

  it('删除走二次确认 → deleteDept', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteDept).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteDept).toHaveBeenCalledWith(1)
  })

  it('删除 409 → 提示存在子部门或关联', async () => {
    vi.spyOn(ElMessageBox, 'confirm').mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteDept).mockRejectedValue({ status: 409, code: 'dept.IN_USE', message: '存在子部门' })
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('存在子部门或关联，无法删除')
  })
})
