import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import DictPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listDictTypes, deleteDictType, listDictData } from '@/api/dict'

vi.mock('@/api/dict', () => ({
  listDictTypes: vi.fn(),
  getDictType: vi.fn(),
  createDictType: vi.fn(),
  updateDictType: vi.fn(),
  deleteDictType: vi.fn(),
  listDictData: vi.fn(),
  getDictData: vi.fn(),
  createDictData: vi.fn(),
  updateDictData: vi.fn(),
  deleteDictData: vi.fn(),
}))

const TYPES = [
  {
    id: 1,
    name: '用户性别',
    type: 'sys_user_sex',
    is_builtin: true,
    remark: '内置',
    status: 'active',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    name: '系统开关',
    type: 'sys_normal_disable',
    is_builtin: false,
    remark: null,
    status: 'disabled',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(DictPage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listDictTypes).mockReset()
  vi.mocked(listDictTypes).mockResolvedValue({
    items: TYPES,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(deleteDictType).mockReset()
  vi.mocked(listDictData).mockReset()
  vi.mocked(listDictData).mockResolvedValue({
    items: [],
    page: 1,
    size: 20,
    total: 0,
    total_pages: 0,
  })
  document.body.innerHTML = ''
})

describe('字典管理页', () => {
  it('挂载即加载并渲染字典类型行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listDictTypes).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('用户性别')
    expect(wrapper.text()).toContain('sys_normal_disable')
  })

  it('点新增 → 打开字典类型对话框', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增字典类型')
  })

  it('查询带 keyword 回第一页', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('input').setValue('性别')
    const queryBtn = wrapper.findAll('button').find((b) => b.text().includes('查询'))
    await queryBtn!.trigger('click')
    await flushPromises()
    expect(listDictTypes).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, keyword: '性别' }),
    )
  })

  it('删除走二次确认 → deleteDictType', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteDictType).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteDictType).toHaveBeenCalledWith(1)
  })

  it('点「数据」打开抽屉并按 dict_type_id 拉数据', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const dataBtn = wrapper.findAll('button').find((b) => b.text().includes('数据'))
    await dataBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('字典数据 - 用户性别')
    expect(listDictData).toHaveBeenLastCalledWith(
      expect.objectContaining({ dict_type_id: 1 }),
    )
  })
})
