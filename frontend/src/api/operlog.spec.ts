import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { listOperlog, getOperlog } from './operlog'

/** 记录每次 fetch 的 method / url / body，供断言路径与查询参数。 */
interface Captured {
  method: string
  url: string
  body: string
}

function captureFetch(captured: Captured[], responder: () => Response): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init)
    captured.push({
      method: req.method,
      url: req.url,
      body: req.body ? await req.clone().text() : '',
    })
    return responder()
  }) as unknown as typeof fetch
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('operlog api', () => {
  it('listOperlog 透传 page/size/event_type/result_status/actor_user_id 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listOperlog({
      page: 2,
      size: 10,
      event_type: 'user.login',
      result_status: 'success',
      actor_user_id: 7,
    })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/monitor/operlog')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(url.searchParams.get('event_type')).toBe('user.login')
    expect(url.searchParams.get('result_status')).toBe('success')
    expect(url.searchParams.get('actor_user_id')).toBe('7')
  })

  it('listOperlog 空筛选时不带可选参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 20, total: 0, total_pages: 0 }),
      ),
    )
    await listOperlog({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('event_type')).toBe(false)
    expect(url.searchParams.has('result_status')).toBe(false)
    expect(url.searchParams.has('actor_user_id')).toBe(false)
  })

  it('getOperlog 命中 GET /monitor/operlog/{event_pk} 并返回 detail', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 42,
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
          payload: { foo: 'bar' },
          request_id: 'req-1',
          trace_id: 'trace-1',
          user_agent: 'curl/8',
        }),
      ),
    )
    const detail = await getOperlog(42)
    expect(detail.id).toBe(42)
    expect(detail.payload).toEqual({ foo: 'bar' })
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/operlog/42')
  })

  it('listOperlog 403 → 抛归一化 ApiError（保留 status）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'auth.FORBIDDEN_BY_ROLE', title: '无权限', status: 403, request_id: 'r' },
          403,
        ),
      ),
    )
    await expect(listOperlog({ page: 1, size: 20 })).rejects.toMatchObject({ status: 403 })
  })
})
