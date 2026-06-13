import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import ConfigPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listConfigs, createConfig, deleteConfig } from '@/api/config'

vi.mock('@/api/config', () => ({
  listConfigs: vi.fn(),
  getConfig: vi.fn(),
  createConfig: vi.fn(),
  updateConfig: vi.fn(),
  deleteConfig: vi.fn(),
  getConfigValue: vi.fn(),
}))

const CONFIGS = [
  {
    id: 1,
    name: '系统名称',
    config_key: 'sys.name',
    config_value: 'admin-platform',
    is_builtin: true,
    remark: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    name: '主题色',
    config_key: 'sys.theme',
    config_value: 'blue',
    is_builtin: false,
    remark: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(ConfigPage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listConfigs).mockReset()
  vi.mocked(listConfigs).mockResolvedValue({
    items: CONFIGS,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(createConfig).mockReset()
  vi.mocked(deleteConfig).mockReset()
  document.body.innerHTML = ''
})

describe('参数配置页', () => {
  it('挂载即加载并渲染参数行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listConfigs).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('系统名称')
    expect(wrapper.text()).toContain('sys.theme')
  })

  it('点新增 → 打开对话框（新增参数标题）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增参数')
  })

  it('查询带 keyword 回第一页', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('input').setValue('theme')
    const queryBtn = wrapper.findAll('button').find((b) => b.text().includes('查询'))
    await queryBtn!.trigger('click')
    await flushPromises()
    expect(listConfigs).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, keyword: 'theme' }),
    )
  })

  it('删除走二次确认 → deleteConfig', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteConfig).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteConfig).toHaveBeenCalledWith(1)
  })
})
