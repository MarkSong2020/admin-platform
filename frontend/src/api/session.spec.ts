import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SessionExpiredError, onSessionExpired, emitSessionExpired } from './session'

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
