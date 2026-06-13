import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { listMenus, getMenu, createMenu, updateMenu, deleteMenu } from './menus'

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

function menuRead(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    name: '系统管理',
    menu_type: 'M',
    parent_id: null,
    path: 'system',
    component: null,
    perms: null,
    icon: 'setting',
    sort_order: 0,
    visible: true,
    status: 'active',
    created_at: '',
    updated_at: '',
    ...over,
  }
}

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('menus api', () => {
  it('listMenus 透传 page/size 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [menuRead()], page: 1, size: 100, total: 1, total_pages: 1 }),
      ),
    )
    const page = await listMenus({ page: 1, size: 100 })
    expect(page.total).toBe(1)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/menus')
    expect(url.searchParams.get('page')).toBe('1')
    expect(url.searchParams.get('size')).toBe('100')
  })

  it('getMenu 命中 GET /menus/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(menuRead({ id: 7 }))))
    const menu = await getMenu(7)
    expect(menu.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/menus/7')
  })

  it('createMenu POST /menus 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () => jsonResponse(menuRead({ id: 9, name: '用户管理' }), 201)),
    )
    const created = await createMenu({
      name: '用户管理',
      menu_type: 'C',
      parent_id: 1,
      path: 'user',
      component: 'system/user/index',
      perms: 'system:user:list',
      icon: '',
      sort_order: 0,
      visible: true,
      status: 'active',
    })
    expect(created.id).toBe(9)
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/menus')
    expect(captured[0]!.body).toContain('"name":"用户管理"')
    expect(captured[0]!.body).toContain('"menu_type":"C"')
  })

  it('updateMenu 走 PATCH /menus/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () => jsonResponse(menuRead({ id: 3, name: '改名' }))),
    )
    const updated = await updateMenu(3, { name: '改名' })
    expect(updated.name).toBe('改名')
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/menus/3')
    expect(captured[0]!.body).toContain('"name":"改名"')
  })

  it('deleteMenu 走 DELETE /menus/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteMenu(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/menus/5')
  })

  it('deleteMenu 409 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'menu.HAS_CHILDREN', title: '存在子菜单', status: 409, request_id: 'r' },
          409,
        ),
      ),
    )
    await expect(deleteMenu(5)).rejects.toMatchObject({ code: 'menu.HAS_CHILDREN', status: 409 })
  })
})
