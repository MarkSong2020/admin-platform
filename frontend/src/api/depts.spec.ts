import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { listDepts, getDept, createDept, updateDept, deleteDept } from './depts'

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

describe('depts api', () => {
  it('listDepts 透传 page/size/keyword 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 100, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listDepts({ page: 1, size: 100, keyword: '研发' })
    expect(page.size).toBe(100)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/depts')
    expect(url.searchParams.get('page')).toBe('1')
    expect(url.searchParams.get('size')).toBe('100')
    expect(url.searchParams.get('keyword')).toBe('研发')
  })

  it('listDepts 无 keyword 时不带 keyword 参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 100, total: 0, total_pages: 0 }),
      ),
    )
    await listDepts({ page: 1, size: 100 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('keyword')).toBe(false)
  })

  it('getDept 命中 GET /depts/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 7,
          code: 'rd',
          name: '研发部',
          parent_id: null,
          leader: '张三',
          phone: null,
          email: null,
          sort_order: 0,
          status: 'active',
          created_at: '',
          updated_at: '',
        }),
      ),
    )
    const dept = await getDept(7)
    expect(dept.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/depts/7')
  })

  it('createDept POST /depts 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse(
          {
            id: 9,
            code: 'qa',
            name: '测试部',
            parent_id: 1,
            leader: null,
            phone: null,
            email: null,
            sort_order: 0,
            status: 'active',
            created_at: '',
            updated_at: '',
          },
          201,
        ),
      ),
    )
    const created = await createDept({ code: 'qa', name: '测试部', parent_id: 1, sort_order: 0 })
    expect(created.id).toBe(9)
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/depts')
    expect(captured[0]!.body).toContain('"code":"qa"')
    expect(captured[0]!.body).toContain('"parent_id":1')
  })

  it('updateDept 走 PATCH /depts/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 3,
          code: 'rd',
          name: '研发中心',
          parent_id: null,
          leader: null,
          phone: null,
          email: null,
          sort_order: 0,
          status: 'disabled',
          created_at: '',
          updated_at: '',
        }),
      ),
    )
    const updated = await updateDept(3, { name: '研发中心', status: 'disabled' })
    expect(updated.status).toBe('disabled')
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/depts/3')
    expect(captured[0]!.body).toContain('"status":"disabled"')
  })

  it('deleteDept 走 DELETE /depts/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteDept(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/depts/5')
  })

  it('deleteDept 409 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'dept.IN_USE', title: '存在子部门', status: 409, request_id: 'r' },
          409,
        ),
      ),
    )
    await expect(deleteDept(5)).rejects.toMatchObject({ code: 'dept.IN_USE', status: 409 })
  })
})
