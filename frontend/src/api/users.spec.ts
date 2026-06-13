import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import {
  listUsers,
  getUser,
  createUser,
  updateUser,
  deleteUser,
  getUserRoles,
  setUserRoles,
  getUserPosts,
  setUserPosts,
} from './users'

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

describe('users api', () => {
  it('listUsers 透传 page/size/keyword 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listUsers({ page: 2, size: 10, keyword: 'admin' })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/users')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(url.searchParams.get('keyword')).toBe('admin')
  })

  it('listUsers 无 keyword 时不带 keyword 参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 1, size: 20, total: 0, total_pages: 0 }),
      ),
    )
    await listUsers({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('keyword')).toBe(false)
  })

  it('getUser 命中 GET /users/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 7,
          username: 'u7',
          nickname: '七',
          dept_id: null,
          status: 'active',
          is_super_admin: false,
        }),
      ),
    )
    const user = await getUser(7)
    expect(user.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/users/7')
  })

  it('createUser POST /users 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse(
          {
            id: 9,
            username: 'newbie',
            nickname: '',
            dept_id: null,
            status: 'active',
            is_super_admin: false,
          },
          201,
        ),
      ),
    )
    const created = await createUser({ username: 'newbie', password: 'pw', nickname: '' })
    expect(created.id).toBe(9)
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/users')
    expect(captured[0]!.body).toContain('"username":"newbie"')
  })

  it('updateUser 走 PATCH /users/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
          id: 3,
          username: 'u3',
          nickname: '改名',
          dept_id: null,
          status: 'disabled',
          is_super_admin: false,
        }),
      ),
    )
    const updated = await updateUser(3, { nickname: '改名', status: 'disabled' })
    expect(updated.status).toBe('disabled')
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/users/3')
    expect(captured[0]!.body).toContain('"status":"disabled"')
  })

  it('deleteUser 走 DELETE /users/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteUser(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/users/5')
  })

  it('deleteUser 409 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'user.IN_USE', title: '存在关联', status: 409, request_id: 'r' },
          409,
        ),
      ),
    )
    await expect(deleteUser(5)).rejects.toMatchObject({ code: 'user.IN_USE', status: 409 })
  })

  it('getUserRoles → BindingRead.ids', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ ids: [1, 2] })))
    const binding = await getUserRoles(4)
    expect(binding.ids).toEqual([1, 2])
  })

  it('setUserRoles PUT body 为 {role_ids}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await setUserRoles(4, [10, 20])
    expect(captured[0]!.method).toBe('PUT')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/users/4/roles')
    expect(captured[0]!.body).toContain('"role_ids":[10,20]')
  })

  it('getUserPosts / setUserPosts body 为 {post_ids}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await setUserPosts(4, [33])
    expect(captured[0]!.method).toBe('PUT')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/users/4/posts')
    expect(captured[0]!.body).toContain('"post_ids":[33]')

    captured.length = 0
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ ids: [33] })))
    const binding = await getUserPosts(4)
    expect(binding.ids).toEqual([33])
  })
})
