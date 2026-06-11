import { describe, it, expect, vi, beforeEach } from 'vitest'
import { normalizeApiError, normalizeResponseError, downloadBlob, uploadMultipart } from './transport'
import { SessionExpiredError, __resetSessionForTest, setTokens } from './session'

beforeEach(() => { __resetSessionForTest(); sessionStorage.clear() })

describe('normalizeApiError', () => {
  it('透传 SessionExpiredError 不降级', () => {
    const e = new SessionExpiredError()
    expect(normalizeApiError(e)).toBe(e)
  })

  it('AbortError → 归一为带 code TIMEOUT 的 ApiError', () => {
    const e = new DOMException('aborted', 'AbortError')
    const out = normalizeApiError(e)
    expect(out).not.toBeInstanceOf(SessionExpiredError)
    expect((out as { code: string }).code).toBe('TIMEOUT')
  })
})

describe('normalizeResponseError', () => {
  it('解析 RFC9457 ProblemDetail（type/title/status/detail）', async () => {
    const res = new Response(
      JSON.stringify({ type: 'admin_platform.USER_NOT_FOUND', title: 'User not found', status: 404, detail: 'id=42' }),
      { status: 404, headers: { 'Content-Type': 'application/json' } },
    )
    const err = await normalizeResponseError(res)
    expect(err).toMatchObject({
      code: 'admin_platform.USER_NOT_FOUND', status: 404, message: 'User not found', detail: 'id=42',
    })
  })

  it('非 JSON body → 用 status 兜底为 HTTP_<status>', async () => {
    const err = await normalizeResponseError(new Response('oops', { status: 502 }))
    expect(err).toMatchObject({ code: 'HTTP_502', status: 502 })
  })
})

describe('downloadBlob / uploadMultipart', () => {
  it('downloadBlob 注入 auth header 并返回 blob', async () => {
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    // jsdom 已知 bug：Response(new Blob([...])) .blob().text() 返回 "[object Blob]"。
    // 改用文字 body，保证 blob.text() 可读（意图不变：downloadBlob 返回有内容的 blob）。
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      expect((init.headers as Headers).get('Authorization')).toBe('Bearer a1')
      return new Response('hello', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const blob = await downloadBlob('/api/v1/posts/export')
    expect(await blob.text()).toBe('hello')
  })

  it('uploadMultipart 以 FormData 发送且不设 Content-Type（交由浏览器）', async () => {
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      expect(init.body).toBeInstanceOf(FormData)
      expect((init.headers as Headers).has('Content-Type')).toBe(false)
      return new Response('{"imported":1}', { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)
    const fd = new FormData()
    fd.append('file', new Blob(['x']), 'a.xlsx')
    const res = await uploadMultipart('/api/v1/posts/import', fd)
    expect(res.status).toBe(200)
  })

  it('downloadBlob 非 2xx → 抛归一 ApiError（保留 status/code）', async () => {
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ type: 'file.NOT_FOUND', title: 'not found', status: 404 }),
      { status: 404, headers: { 'Content-Type': 'application/json' } },
    )))
    await expect(downloadBlob('/api/v1/files/9/download')).rejects.toMatchObject({
      code: 'file.NOT_FOUND', status: 404,
    })
  })
})
