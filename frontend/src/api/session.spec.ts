import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  SessionExpiredError,
  onSessionExpired,
  emitSessionExpired,
  setTokens,
  clearTokens,
  hasRefresh,
  attachAuthHeaders,
  refreshOnce,
  __resetSessionForTest,
  __setRefreshImplForTest,
} from './session'

describe('session error & emitter', () => {
  it('SessionExpiredError 是带 name 的 Error 子类', () => {
    const err = new SessionExpiredError('refresh failed')
    expect(err).toBeInstanceOf(Error)
    expect(err.name).toBe('SessionExpiredError')
    expect(err.message).toBe('refresh failed')
  })

  it('onSessionExpired 订阅者在 emit 时被调用一次', () => {
    const handler = vi.fn()
    const off = onSessionExpired(handler)
    emitSessionExpired()
    expect(handler).toHaveBeenCalledTimes(1)
    off()
    emitSessionExpired()
    expect(handler).toHaveBeenCalledTimes(1)
  })
})

describe('session tokens & single-flight refresh', () => {
  beforeEach(() => {
    __resetSessionForTest()
    sessionStorage.clear()
  })

  it('setTokens 写入后 attachAuthHeaders 注入 Bearer，hasRefresh 为真', () => {
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    const headers = new Headers()
    attachAuthHeaders(headers)
    expect(headers.get('Authorization')).toBe('Bearer a1')
    expect(hasRefresh()).toBe(true)
  })

  it('clearTokens 清空内存与 sessionStorage 的 refresh', () => {
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    clearTokens()
    expect(hasRefresh()).toBe(false)
    const headers = new Headers()
    attachAuthHeaders(headers)
    expect(headers.get('Authorization')).toBeNull()
  })

  it('并发 refreshOnce 只发起一次刷新请求（single-flight，client/transport 共享）', async () => {
    setTokens({ accessToken: 'a0', refreshToken: 'r0' })
    const impl = vi.fn(async () => {
      await new Promise((r) => setTimeout(r, 10))
      return { accessToken: 'a1', refreshToken: 'r1' }
    })
    __setRefreshImplForTest(impl)
    const [r1, r2, r3] = await Promise.all([refreshOnce(), refreshOnce(), refreshOnce()])
    expect(impl).toHaveBeenCalledTimes(1)
    expect(r1).toBe('a1'); expect(r2).toBe('a1'); expect(r3).toBe('a1')
  })

  it('refresh 失败 → clearTokens + emit sessionExpired + 抛 SessionExpiredError', async () => {
    setTokens({ accessToken: 'a0', refreshToken: 'r0' })
    const handler = vi.fn()
    onSessionExpired(handler)
    __setRefreshImplForTest(async () => { throw new Error('401') })
    await expect(refreshOnce()).rejects.toBeInstanceOf(SessionExpiredError)
    expect(handler).toHaveBeenCalledTimes(1)
    expect(hasRefresh()).toBe(false)
  })
})
