import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { listOnline, kickOnline } from './online'

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

describe('online api', () => {
  it('listOnline 命中 GET /monitor/online 并透传 page/size', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const result = await listOnline({ page: 2, size: 10 })
    expect(result.page).toBe(2)
    expect(captured[0]!.method).toBe('GET')
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/monitor/online')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
  })

  it('kickOnline 走 DELETE /monitor/online/{session_id}（字符串路径参数，204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(kickOnline('sess-abc-123')).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/online/sess-abc-123')
  })

  it('kickOnline 404 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'monitor.SESSION_NOT_FOUND', title: '会话不存在', status: 404, request_id: 'r' },
          404,
        ),
      ),
    )
    await expect(kickOnline('gone')).rejects.toMatchObject({
      code: 'monitor.SESSION_NOT_FOUND',
      status: 404,
    })
  })
})
