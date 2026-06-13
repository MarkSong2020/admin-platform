import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import {
  listDictTypes,
  getDictType,
  createDictType,
  updateDictType,
  deleteDictType,
  listDictData,
  getDictData,
  createDictData,
  updateDictData,
  deleteDictData,
} from './dict'

/** 记录每次 fetch 的 method / url / body，供断言路径与请求体（同 users.spec 范式）。 */
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

function emptyPage(): unknown {
  return { items: [], page: 1, size: 20, total: 0, total_pages: 0 }
}

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('dict types api', () => {
  it('listDictTypes 透传 page/size/keyword 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listDictTypes({ page: 2, size: 10, keyword: '性别' })
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/dict/types')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(url.searchParams.get('keyword')).toBe('性别')
  })

  it('listDictTypes 无 keyword 时不带 keyword 参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listDictTypes({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('keyword')).toBe(false)
  })

  it('getDictType 命中 GET /dict/types/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 3 })))
    await getDictType(3)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/types/3')
  })

  it('createDictType POST /dict/types 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 9 }, 201)))
    await createDictType({ name: '性别', type: 'sys_gender', is_builtin: false, status: 'active' })
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/types')
    expect(captured[0]!.body).toContain('"type":"sys_gender"')
  })

  it('updateDictType 走 PATCH /dict/types/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 3 })))
    await updateDictType(3, { name: '改名', status: 'disabled' })
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/types/3')
    expect(captured[0]!.body).toContain('"status":"disabled"')
  })

  it('deleteDictType 走 DELETE /dict/types/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteDictType(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/types/5')
  })

  it('deleteDictType 409 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ type: 'dict.IN_USE', title: '存在数据', status: 409, request_id: 'r' }, 409),
      ),
    )
    await expect(deleteDictType(5)).rejects.toMatchObject({ code: 'dict.IN_USE', status: 409 })
  })
})

describe('dict data api', () => {
  it('listDictData 透传 page/size/dict_type_id', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listDictData({ page: 1, size: 50, dict_type_id: 7 })
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/dict/data')
    expect(url.searchParams.get('dict_type_id')).toBe('7')
    expect(url.searchParams.get('size')).toBe('50')
  })

  it('listDictData 无 dict_type_id 时不带该参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listDictData({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('dict_type_id')).toBe(false)
  })

  it('getDictData 命中 GET /dict/data/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 11 })))
    await getDictData(11)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/data/11')
  })

  it('createDictData POST /dict/data 携带 dict_type_id', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 12 }, 201)))
    await createDictData({
      dict_type_id: 7,
      label: '男',
      value: '1',
      is_default: false,
      sort_order: 0,
      status: 'active',
    })
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/data')
    expect(captured[0]!.body).toContain('"dict_type_id":7')
    expect(captured[0]!.body).toContain('"label":"男"')
  })

  it('updateDictData 走 PATCH /dict/data/{id}（不含 dict_type_id）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 12 })))
    await updateDictData(12, { label: '女', value: '2', is_default: true })
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/data/12')
    expect(captured[0]!.body).toContain('"is_default":true')
    expect(captured[0]!.body).not.toContain('dict_type_id')
  })

  it('deleteDictData 走 DELETE /dict/data/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteDictData(12)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/dict/data/12')
  })
})
