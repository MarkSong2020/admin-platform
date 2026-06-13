import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { __resetSessionForTest, setTokens } from './session'
import { listFiles, uploadFile, downloadFile, deleteFile } from './file'

/** 记录每次 fetch 的 method / url / body，供断言路径、方法、请求体（含 multipart 字段）。 */
interface Captured {
  method: string
  url: string
  request: Request
}

function captureFetch(captured: Captured[], responder: () => Response): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init)
    captured.push({ method: req.method, url: req.url, request: req })
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
  // download 端点经 transport，attachAuthHeaders 需要 token 才注入；upload 同理。
  setTokens({ accessToken: 'a1', refreshToken: 'r1' })
})

describe('file api', () => {
  it('listFiles 命中 GET /files 并透传 page/size', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({ items: [], page: 2, size: 10, total: 0, total_pages: 0 }),
      ),
    )
    const page = await listFiles({ page: 2, size: 10 })
    expect(page.page).toBe(2)
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/files')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(captured[0]!.method).toBe('GET')
  })

  it('uploadFile 以 multipart 发送，文件字段名为 upload', async () => {
    // transport 以 fetch(url, {body: form}) 调用，init.body 即原始 FormData 实例，
    // 直接断言字段名（jsdom 不可靠解析 multipart 流，故不走 req.formData()）。
    let method = ''
    let pathname = ''
    let form: FormData | null = null
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        method = init?.method ?? 'GET'
        pathname = new URL(String(input)).pathname
        form = init?.body instanceof FormData ? init.body : null
        return jsonResponse(
          {
            id: 7,
            original_filename: 'a.txt',
            content_type: 'text/plain',
            size_bytes: 1,
            sha256: 'x',
            status: 'active',
            uploader_id: 1,
            created_at: '2026-06-01T00:00:00Z',
          },
          201,
        )
      }),
    )
    const file = new File(['hello'], 'a.txt', { type: 'text/plain' })
    const created = await uploadFile(file)
    expect(created.id).toBe(7)
    expect(method).toBe('POST')
    expect(pathname).toBe('/api/v1/files')
    expect(form!.has('upload')).toBe(true)
    const uploaded = form!.get('upload')
    expect(uploaded).toBeInstanceOf(File)
    expect((uploaded as File).name).toBe('a.txt')
  })

  describe('downloadFile', () => {
    // jsdom 不真正下载；spy a.click，并打桩 createObjectURL/revokeObjectURL（jsdom 未实现），保留 URL 构造能力。
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click')

    beforeEach(() => {
      clickSpy.mockImplementation(() => {})
      URL.createObjectURL = vi.fn(() => 'blob:mock') as unknown as typeof URL.createObjectURL
      URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL
    })

    afterEach(() => {
      clickSpy.mockReset()
    })

    it('downloadFile 命中 GET /files/{id}/download 并触发保存', async () => {
      const captured: Captured[] = []
      vi.stubGlobal('fetch', captureFetch(captured, () => new Response('binary', { status: 200 })))
      await downloadFile(9, 'report.pdf')
      expect(captured[0]!.method).toBe('GET')
      expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/files/9/download')
      expect(clickSpy).toHaveBeenCalledTimes(1)
    })
  })

  it('deleteFile 走 DELETE /files/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteFile(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/files/5')
  })

  it('deleteFile 409 → 抛归一化 ApiError（保留 status/code）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ type: 'file.IN_USE', title: '存在关联', status: 409, request_id: 'r' }, 409),
      ),
    )
    await expect(deleteFile(5)).rejects.toMatchObject({ code: 'file.IN_USE', status: 409 })
  })
})
