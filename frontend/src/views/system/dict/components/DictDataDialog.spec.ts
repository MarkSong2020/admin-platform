import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import DictDataDialog from './DictDataDialog.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listDictData, deleteDictData } from '@/api/dict'

vi.mock('@/api/dict', () => ({
  listDictData: vi.fn(),
  getDictData: vi.fn(),
  createDictData: vi.fn(),
  updateDictData: vi.fn(),
  deleteDictData: vi.fn(),
}))

const DICT_TYPE = {
  id: 7,
  name: '性别',
  type: 'sys_user_sex',
  is_builtin: true,
  remark: '',
  status: 'active',
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-01T00:00:00Z',
}

const DATA = [
  {
    id: 11,
    dict_type_id: 7,
    label: '男',
    value: '1',
    sort_order: 0,
    css_class: '',
    is_default: true,
    remark: '',
    status: 'active',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountDrawer() {
  return mount(DictDataDialog, {
    props: { dictType: DICT_TYPE, visible: false },
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listDictData).mockReset()
  vi.mocked(listDictData).mockResolvedValue({
    items: DATA,
    page: 1,
    size: 20,
    total: 1,
    total_pages: 1,
  })
  vi.mocked(deleteDictData).mockReset()
  document.body.innerHTML = ''
})

describe('DictDataDialog（字典数据抽屉）', () => {
  it('打开抽屉按 dict_type_id 加载该类型数据', async () => {
    const wrapper = mountDrawer()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listDictData).toHaveBeenCalledWith(
      expect.objectContaining({ dict_type_id: 7, page: 1 }),
    )
    expect(document.body.textContent).toContain('男')
  })

  it('点新增 → 打开数据表单对话框', async () => {
    const wrapper = mountDrawer()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const addBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('新增'),
    )
    addBtn!.click()
    await flushPromises()
    expect(document.body.textContent).toContain('新增字典数据')
  })

  it('删除走二次确认 → deleteDictData(id)', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteDictData).mockResolvedValue(undefined)
    const wrapper = mountDrawer()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const delBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('删除'),
    )
    delBtn!.click()
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteDictData).toHaveBeenCalledWith(11)
  })
})
