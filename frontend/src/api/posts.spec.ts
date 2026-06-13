import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { listPosts, getPost, createPost, updatePost, deletePost } from './posts'

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

function postRead(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: 1,
    code: 'P001',
    name: '主管',
    sort_order: 0,
    status: 'active',
    created_at: '',
    updated_at: '',
    ...overrides,
  }
}

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('posts api', () => {
  it('listPosts 透传 page/size 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listPosts({ page: 2, size: 10 })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/posts')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
  })

  it('getPost 命中 GET /posts/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(postRead({ id: 7 }))))
    const post = await getPost(7)
    expect(post.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/posts/7')
  })

  it('createPost POST /posts 携带 body', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () => jsonResponse(postRead({ id: 9, code: 'NEW' }), 201)),
    )
    const created = await createPost({ code: 'NEW', name: '新岗位', sort_order: 0, status: 'active' })
    expect(created.id).toBe(9)
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/posts')
    expect(captured[0]!.body).toContain('"code":"NEW"')
  })

  it('updatePost 走 PATCH /posts/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () => jsonResponse(postRead({ id: 3, status: 'disabled' }))),
    )
    const updated = await updatePost(3, { name: '改名', status: 'disabled' })
    expect(updated.status).toBe('disabled')
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/posts/3')
    expect(captured[0]!.body).toContain('"status":"disabled"')
  })

  it('deletePost 走 DELETE /posts/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deletePost(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/posts/5')
  })

  it('deletePost 409 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          { type: 'post.IN_USE', title: '存在关联', status: 409, request_id: 'r' },
          409,
        ),
      ),
    )
    await expect(deletePost(5)).rejects.toMatchObject({ code: 'post.IN_USE', status: 409 })
  })
})
