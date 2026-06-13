import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import {
  listRoles,
  getRole,
  createRole,
  updateRole,
  deleteRole,
  getRoleMenus,
  setRoleMenus,
  getRoleDepts,
  setRoleDepts,
} from './roles'

/** 记录每次 fetch 的 method / url / body，供断言路径与请求体（同 users.spec.ts）。 */
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

describe('roles api', () => {
  it('listRoles 透传 page/size/keyword 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listRoles({ page: 2, size: 10, keyword: 'admin' })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/roles')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(url.searchParams.get('keyword')).toBe('admin')
  })

  it('listRoles 无 keyword 时不带 keyword 参数（兼容 P6.2-A 旧调用）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 100, total: 0, total_pages: 0 }),
      ),
    )
    await listRoles({ page: 1, size: 100 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('keyword')).toBe(false)
  })

  it('getRole 命中 GET /roles/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 7,
          code: 'editor',
          name: '编辑',
          data_scope: 'self',
          sort_order: 0,
          status: 'active',
          created_at: '',
          updated_at: '',
        }),
      ),
    )
    const role = await getRole(7)
    expect(role.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles/7')
  })

  it('createRole POST /roles 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse(
          {
            id: 9,
            code: 'ops',
            name: '运维',
            data_scope: 'all',
            sort_order: 1,
            status: 'active',
            created_at: '',
            updated_at: '',
          },
          201,
        ),
      ),
    )
    const created = await createRole({
      code: 'ops',
      name: '运维',
      data_scope: 'all',
      sort_order: 1,
      status: 'active',
    })
    expect(created.id).toBe(9)
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles')
    expect(captured[0]!.body).toContain('"code":"ops"')
    expect(captured[0]!.body).toContain('"data_scope":"all"')
  })

  it('updateRole 走 PATCH /roles/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 3,
          code: 'editor',
          name: '改名',
          data_scope: 'self_dept',
          sort_order: 0,
          status: 'disabled',
          created_at: '',
          updated_at: '',
        }),
      ),
    )
    const updated = await updateRole(3, { name: '改名', data_scope: 'self_dept', status: 'disabled' })
    expect(updated.status).toBe('disabled')
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles/3')
    expect(captured[0]!.body).toContain('"data_scope":"self_dept"')
  })

  it('deleteRole 走 DELETE /roles/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteRole(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles/5')
  })

  it('deleteRole 409 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'role.IN_USE', title: '存在关联', status: 409, request_id: 'r' },
          409,
        ),
      ),
    )
    await expect(deleteRole(5)).rejects.toMatchObject({ code: 'role.IN_USE', status: 409 })
  })

  it('getRoleMenus → GET /roles/{id}/menus 返回 BindingRead.ids', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ ids: [1, 2] })))
    const binding = await getRoleMenus(4)
    expect(binding.ids).toEqual([1, 2])
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles/4/menus')
  })

  it('setRoleMenus PUT body 为 {menu_ids}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await setRoleMenus(4, [10, 20])
    expect(captured[0]!.method).toBe('PUT')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles/4/menus')
    expect(captured[0]!.body).toContain('"menu_ids":[10,20]')
  })

  it('getRoleDepts → GET /roles/{id}/depts 返回 BindingRead.ids', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ ids: [5] })))
    const binding = await getRoleDepts(4)
    expect(binding.ids).toEqual([5])
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles/4/depts')
  })

  it('setRoleDepts PUT body 为 {dept_ids}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await setRoleDepts(4, [33])
    expect(captured[0]!.method).toBe('PUT')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/roles/4/depts')
    expect(captured[0]!.body).toContain('"dept_ids":[33]')
  })
})
