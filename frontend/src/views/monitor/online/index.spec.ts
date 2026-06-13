import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import OnlinePage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listOnline, kickOnline } from '@/api/online'

vi.mock('@/api/online', () => ({
  listOnline: vi.fn(),
  kickOnline: vi.fn(),
}))

const SESSIONS = [
  {
    session_id: 'sess-1',
    user_id: 1,
    username: 'admin',
    login_time: '2026-06-12T08:00:00Z',
    last_active_time: '2026-06-12T09:00:00Z',
    expires_at: '2026-06-12T18:00:00Z',
  },
  {
    session_id: 'sess-2',
    user_id: 2,
    username: 'alice',
    login_time: '2026-06-12T08:30:00Z',
    last_active_time: '2026-06-12T09:30:00Z',
    expires_at: '2026-06-12T18:30:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(OnlinePage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listOnline).mockReset()
  vi.mocked(listOnline).mockResolvedValue({
    items: SESSIONS,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(kickOnline).mockReset()
  document.body.innerHTML = ''
})

afterEach(() => {
  // 还原对 ElMessageBox.confirm 的 spy，避免跨用例累计调用次数。
  vi.restoreAllMocks()
})

describe('在线用户页', () => {
  it('挂载即加载并渲染会话行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listOnline).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('admin')
    expect(wrapper.text()).toContain('alice')
  })

  it('强制下线走二次确认 → kickOnline(session_id) → 刷新', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(kickOnline).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const kickBtn = wrapper.findAll('button').find((b) => b.text().includes('强制下线'))
    await kickBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(kickOnline).toHaveBeenCalledWith('sess-1')
    // 下线后重新拉列表（首次挂载 1 次 + 下线后 1 次）。
    expect(listOnline).toHaveBeenCalledTimes(2)
  })

  it('取消二次确认时不调用 kickOnline', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockRejectedValue(new Error('cancel'))
    const wrapper = mountPage()
    await flushPromises()
    const kickBtn = wrapper.findAll('button').find((b) => b.text().includes('强制下线'))
    await kickBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(kickOnline).not.toHaveBeenCalled()
  })
})
