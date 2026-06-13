import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import {
  listConfigs,
  getConfig,
  createConfig,
  updateConfig,
  deleteConfig,
  getConfigValue,
} from './config'

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

describe('configs api', () => {
  it('listConfigs 透传 page/size/keyword 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listConfigs({ page: 2, size: 10, keyword: 'sys' })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/configs')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(url.searchParams.get('keyword')).toBe('sys')
  })

  it('listConfigs 无 keyword 时不带 keyword 参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 20, total: 0, total_pages: 0 }),
      ),
    )
    await listConfigs({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('keyword')).toBe(false)
  })

  it('getConfig 命中 GET /configs/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 7,
          name: '系统名称',
          config_key: 'sys.name',
          config_value: 'admin',
          is_builtin: true,
          remark: null,
          created_at: '2026-06-01T00:00:00Z',
          updated_at: '2026-06-01T00:00:00Z',
        }),
      ),
    )
    const config = await getConfig(7)
    expect(config.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/configs/7')
  })

  it('createConfig POST /configs 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse(
          {
            id: 9,
            name: '新参数',
            config_key: 'sys.new',
            config_value: 'v',
            is_builtin: false,
            remark: null,
            created_at: '2026-06-01T00:00:00Z',
            updated_at: '2026-06-01T00:00:00Z',
          },
          201,
        ),
      ),
    )
    const created = await createConfig({
      name: '新参数',
      config_key: 'sys.new',
      config_value: 'v',
      is_builtin: false,
    })
    expect(created.id).toBe(9)
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/configs')
    expect(captured[0]!.body).toContain('"config_key":"sys.new"')
  })

  it('updateConfig 走 PATCH /configs/{id}（不含 config_key）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 3,
          name: '改名',
          config_key: 'sys.name',
          config_value: 'v2',
          is_builtin: false,
          remark: null,
          created_at: '2026-06-01T00:00:00Z',
          updated_at: '2026-06-01T00:00:00Z',
        }),
      ),
    )
    const updated = await updateConfig(3, { name: '改名', config_value: 'v2' })
    expect(updated.config_value).toBe('v2')
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/configs/3')
    expect(captured[0]!.body).toContain('"config_value":"v2"')
    expect(captured[0]!.body).not.toContain('"config_key"')
  })

  it('deleteConfig 走 DELETE /configs/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteConfig(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/configs/5')
  })

  it('deleteConfig 409（内置）→ 抛归一化 ApiError（保留 status）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'config.BUILTIN', title: '内置不可删', status: 409, request_id: 'r' },
          409,
        ),
      ),
    )
    await expect(deleteConfig(5)).rejects.toMatchObject({ status: 409 })
  })

  it('getConfigValue 命中 GET /configs/value/{key}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ config_key: 'sys.name', config_value: 'admin' }),
      ),
    )
    const value = await getConfigValue('sys.name')
    expect(value.config_value).toBe('admin')
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/configs/value/sys.name')
  })
})
