import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import {
  listNotices,
  getNotice,
  createNotice,
  updateNotice,
  deleteNotice,
} from './notice'

/** 记录每次 fetch 的 method / url / body，供断言路径与请求体。 */
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

describe('notices api', () => {
  it('listNotices 透传 notice_type/status/page/size 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listNotices({
      page: 2,
      size: 10,
      notice_type: 'announcement',
      status: 'active',
    })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/notices')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('notice_type')).toBe('announcement')
    expect(url.searchParams.get('status')).toBe('active')
  })

  it('listNotices 无筛选时不带 notice_type/status 参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 20, total: 0, total_pages: 0 }),
      ),
    )
    await listNotices({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('notice_type')).toBe(false)
    expect(url.searchParams.has('status')).toBe(false)
  })

  it('getNotice 命中 GET /notices/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 7,
          title: '维护通知',
          content: '今晚维护',
          notice_type: 'notification',
          status: 'active',
          remark: null,
          created_at: '2026-06-01T00:00:00Z',
          updated_at: '2026-06-01T00:00:00Z',
        }),
      ),
    )
    const notice = await getNotice(7)
    expect(notice.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/notices/7')
  })

  it('createNotice POST /notices 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse(
          {
            id: 9,
            title: '新公告',
            content: '正文',
            notice_type: 'announcement',
            status: 'active',
            remark: null,
            created_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:00:00Z',
          },
          201,
        ),
      ),
    )
    const created = await createNotice({
      title: '新公告',
      content: '正文',
      notice_type: 'announcement',
      status: 'active',
    })
    expect(created.id).toBe(9)
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/notices')
    expect(captured[0]!.body).toContain('"notice_type":"announcement"')
  })

  it('updateNotice 走 PATCH /notices/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 3,
          title: '改标题',
          content: '正文',
          notice_type: 'notification',
          status: 'disabled',
          remark: null,
          created_at: '2026-06-01T00:00:00Z',
          updated_at: '2026-06-01T00:00:00Z',
        }),
      ),
    )
    const updated = await updateNotice(3, { title: '改标题', status: 'disabled' })
    expect(updated.status).toBe('disabled')
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/notices/3')
    expect(captured[0]!.body).toContain('"status":"disabled"')
  })

  it('deleteNotice 走 DELETE /notices/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteNotice(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/notices/5')
  })
})
