import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  __resetSessionForTest, __setRefreshImplForTest, setTokens, onSessionExpired,
} from './session'
import { apiClient } from './client'
import { downloadBlob } from './transport'

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('跨通道 single-flight / 失效统一出口', () => {
  it('JSON(client) 与 blob(transport) 同轮 401 只刷新一次', async () => {
    setTokens({ accessToken: 'old', refreshToken: 'r0' })
    const impl = vi.fn(async () => {
      await new Promise((r) => setTimeout(r, 5))
      return { accessToken: 'new', refreshToken: 'r1' }
    })
    __setRefreshImplForTest(impl)

    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(String(input), init)
      const auth = req.headers.get('Authorization') ?? ''
      if (auth.includes('old')) return new Response(null, { status: 401 })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    await Promise.all([
      apiClient.GET('/api/v1/users' as never, {} as never),
      downloadBlob('/api/v1/files/1/download'),
    ])
    expect(impl).toHaveBeenCalledTimes(1)
  })

  it('refresh 失败时两条通道都触达唯一 handleSessionExpired（emit 一次）', async () => {
    setTokens({ accessToken: 'old', refreshToken: 'r0' })
    const handler = vi.fn()
    onSessionExpired(handler)
    __setRefreshImplForTest(async () => { throw new Error('401') })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 401 })))

    await Promise.allSettled([
      apiClient.GET('/api/v1/users' as never, {} as never),
      downloadBlob('/api/v1/files/1/download'),
    ])
    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('POST(带 body)401 重放保留 body（clone 未被消费）', async () => {
    setTokens({ accessToken: 'old', refreshToken: 'r0' })
    __setRefreshImplForTest(async () => ({ accessToken: 'new', refreshToken: 'r1' }))
    const bodies: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(String(input), init)
      const auth = req.headers.get('Authorization') ?? ''
      bodies.push(await req.clone().text())
      return auth.includes('old')
        ? new Response(null, { status: 401 })
        : new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    vi.stubGlobal('fetch', fetchMock)

    await apiClient.POST('/api/v1/posts' as never, { body: { code: 'A', name: '岗位' } } as never)
    expect(bodies).toHaveLength(2)
    expect(bodies[0]).toContain('岗位')
    expect(bodies[1]).toContain('岗位')
  })
})
