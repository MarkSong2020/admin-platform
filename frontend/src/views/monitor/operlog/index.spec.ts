import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import OperlogPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listOperlog, getOperlog } from '@/api/operlog'

vi.mock('@/api/operlog', () => ({
  listOperlog: vi.fn(),
  getOperlog: vi.fn(),
}))

const EVENTS = [
  {
    id: 1,
    event_id: 'evt-1',
    event_type: 'user.login',
    title: '用户登录',
    action: 'login',
    risk_level: 'low',
    actor_user_id: 7,
    actor_username: 'admin',
    actor_is_super_admin: true,
    target_type: null,
    target_id: null,
    target_display: null,
    result_status: 'success',
    result_http_status: 200,
    result_error_code: null,
    ip: '127.0.0.1',
    method: 'POST',
    path: '/api/v1/auth/login',
    duration_ms: 12,
    redaction_applied: false,
    occurred_at: '2026-06-01T00:00:00Z',
    created_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    event_id: 'evt-2',
    event_type: 'user.delete',
    title: '删除用户',
    action: 'delete',
    risk_level: 'high',
    actor_user_id: 7,
    actor_username: 'admin',
    actor_is_super_admin: true,
    target_type: 'user',
    target_id: '9',
    target_display: 'bob',
    result_status: 'failure',
    result_http_status: 409,
    result_error_code: 'user.IN_USE',
    ip: '10.0.0.1',
    method: 'DELETE',
    path: '/api/v1/users/9',
    duration_ms: 5,
    redaction_applied: false,
    occurred_at: '2026-06-02T00:00:00Z',
    created_at: '2026-06-02T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(OperlogPage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listOperlog).mockReset()
  vi.mocked(listOperlog).mockResolvedValue({
    items: EVENTS,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(getOperlog).mockReset()
  // 按 event_pk 返回对应详情：验证「点哪行→取哪行 id→展示该行 payload」整条路径，
  // 而非固定返回（固定返回会让断言恒过，沦为测 mock 行为）。
  vi.mocked(getOperlog).mockImplementation(async (eventPk: number) => {
    const base = EVENTS.find((e) => e.id === eventPk) ?? EVENTS[0]!
    return {
      ...base,
      payload: { event: base.event_type, id: eventPk },
      request_id: `req-${eventPk}`,
      trace_id: `trace-${eventPk}`,
      user_agent: 'curl/8',
    }
  })
  document.body.innerHTML = ''
})

describe('操作日志页', () => {
  it('挂载即加载并渲染审计行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listOperlog).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('用户登录')
    expect(wrapper.text()).toContain('删除用户')
  })

  it('按事件类型 + 结果筛选回第一页', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('input').setValue('user.login')
    const queryBtn = wrapper.findAll('button').find((b) => b.text().includes('查询'))
    await queryBtn!.trigger('click')
    await flushPromises()
    expect(listOperlog).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, event_type: 'user.login' }),
    )
  })

  it('点详情调 getOperlog 并展示 payload 纯文本', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const detailBtn = wrapper.findAll('button').find((b) => b.text().includes('详情'))
    await detailBtn!.trigger('click')
    await flushPromises()
    expect(getOperlog).toHaveBeenCalledWith(1)
    // 展示的 payload 必须来自 id=1（user.login），证明用对了行 id 而非固定 mock
    expect(document.body.textContent).toContain('"event": "user.login"')
    expect(document.body.textContent).toContain('"id": 1')
  })
})
