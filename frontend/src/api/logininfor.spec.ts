import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { listLogininfor, getLogininfor } from './logininfor'

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

describe('logininfor api', () => {
  it('listLogininfor 透传 page/size/username/status 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listLogininfor({ page: 2, size: 10, username: 'admin', status: 'success' })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/monitor/logininfor')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(url.searchParams.get('username')).toBe('admin')
    expect(url.searchParams.get('status')).toBe('success')
  })

  it('listLogininfor 空筛选时不带可选参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 20, total: 0, total_pages: 0 }),
      ),
    )
    await listLogininfor({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('username')).toBe(false)
    expect(url.searchParams.has('status')).toBe(false)
  })

  it('getLogininfor 命中 GET /monitor/logininfor/{log_pk}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 5,
          user_id: 7,
          username: 'admin',
          status: 'success',
          reason_code: null,
          ip: '127.0.0.1',
          user_agent: 'curl/8',
          request_id: 'req-1',
          login_at_utc: '2026-06-01T00:00:00Z',
          created_at: '2026-06-01T00:00:00Z',
        }),
      ),
    )
    const log = await getLogininfor(5)
    expect(log.id).toBe(5)
    expect(log.username).toBe('admin')
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/logininfor/5')
  })

  it('listLogininfor 403 → 抛归一化 ApiError（保留 status）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'auth.FORBIDDEN_BY_ROLE', title: '无权限', status: 403, request_id: 'r' },
          403,
        ),
      ),
    )
    await expect(listLogininfor({ page: 1, size: 20 })).rejects.toMatchObject({ status: 403 })
  })
})
