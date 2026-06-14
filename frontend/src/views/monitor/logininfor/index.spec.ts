import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import LogininforPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listLogininfor } from '@/api/logininfor'

vi.mock('@/api/logininfor', () => ({
  listLogininfor: vi.fn(),
  getLogininfor: vi.fn(),
}))

const LOGS = [
  {
    id: 1,
    user_id: 7,
    username: 'admin',
    status: 'success',
    reason_code: null,
    ip: '127.0.0.1',
    user_agent: 'curl/8',
    request_id: 'req-1',
    login_at_utc: '2026-06-01T00:00:00Z',
    created_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    user_id: null,
    username: 'ghost',
    status: 'failure',
    reason_code: 'BAD_CREDENTIALS',
    ip: '10.0.0.9',
    user_agent: 'python-requests/2',
    request_id: 'req-2',
    login_at_utc: '2026-06-02T00:00:00Z',
    created_at: '2026-06-02T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(LogininforPage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listLogininfor).mockReset()
  vi.mocked(listLogininfor).mockResolvedValue({
    items: LOGS,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  document.body.innerHTML = ''
})

describe('登录日志页', () => {
  it('挂载即加载并渲染登录行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listLogininfor).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('ghost')
    expect(wrapper.text()).toContain('BAD_CREDENTIALS')
  })

  it('按用户名 + 状态筛选回第一页', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('input').setValue('admin')
    const queryBtn = wrapper.findAll('button').find((b) => b.text().includes('查询'))
    await queryBtn!.trigger('click')
    await flushPromises()
    expect(listLogininfor).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, username: 'admin' }),
    )
  })
})
