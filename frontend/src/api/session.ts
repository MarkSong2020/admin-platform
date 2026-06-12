/**
 * 唯一认证/刷新协调器（token 真值源）。
 * 严格不依赖 stores/router：失效经 emitter 发事件 + 抛 typed error，
 * 由 router composition root 注册的唯一订阅者处理 redirect/清 Pinia/reset 路由。
 * 见 spec §3.1/§4/§6。
 */

/** refresh 失败 / token 失效的 typed error；normalizeApiError 必须透传它不降级。 */
export class SessionExpiredError extends Error {
  constructor(message = 'session expired') {
    super(message)
    this.name = 'SessionExpiredError'
  }
}

type ExpiredHandler = () => void
const expiredHandlers = new Set<ExpiredHandler>()

/** 注册 session 失效订阅者；返回退订函数。router composition root 注册唯一一个。 */
export function onSessionExpired(handler: ExpiredHandler): () => void {
  expiredHandlers.add(handler)
  return () => expiredHandlers.delete(handler)
}

/** 触发 session 失效事件（清理副作用必达，无论哪条请求路径触发）。 */
export function emitSessionExpired(): void {
  for (const handler of expiredHandlers) handler()
}

const REFRESH_STORAGE_KEY = 'admin.refresh'
const BASE = import.meta.env.VITE_API_BASE ?? ''

interface Tokens {
  accessToken: string
  refreshToken: string
}

/** refresh 实现：传入旧 refresh，返回新 token 对。运行时为裸 fetch 调 /auth/refresh（防递归）。 */
export type RefreshImpl = (refreshToken: string) => Promise<Tokens>

let accessToken: string | null = null
let inflight: Promise<string> | null = null // single-flight 句柄（模块级 → client/transport 共享）

/** 默认 refresh 实现：不挂任何拦截的裸 fetch，避免递归 401（spec §3.1）。 */
const defaultRefreshImpl: RefreshImpl = async (refreshToken) => {
  const res = await fetch(`${BASE}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
  if (!res.ok) throw new SessionExpiredError(`refresh ${res.status}`)
  const data = (await res.json()) as { access_token: string; refresh_token: string }
  return { accessToken: data.access_token, refreshToken: data.refresh_token }
}
let refreshImpl: RefreshImpl = defaultRefreshImpl

export function setTokens(tokens: Tokens): void {
  accessToken = tokens.accessToken
  sessionStorage.setItem(REFRESH_STORAGE_KEY, tokens.refreshToken)
}

export function clearTokens(): void {
  accessToken = null
  sessionStorage.removeItem(REFRESH_STORAGE_KEY)
}

export function hasRefresh(): boolean {
  return !!sessionStorage.getItem(REFRESH_STORAGE_KEY)
}

/** 读当前 refresh token（logout 请求体需要；无则 null）。 */
export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_STORAGE_KEY)
}

export function attachAuthHeaders(headers: Headers): void {
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
}

/**
 * single-flight 刷新（无参，client 与 transport 共享同一 inflight）。
 * 成功 → setTokens 返回新 access；失败 → clearTokens + emit + 抛 SessionExpiredError。
 */
export function refreshOnce(): Promise<string> {
  if (inflight) return inflight
  const refreshToken = sessionStorage.getItem(REFRESH_STORAGE_KEY)
  inflight = (async () => {
    try {
      if (!refreshToken) throw new SessionExpiredError('no refresh token')
      const tokens = await refreshImpl(refreshToken)
      setTokens(tokens)
      return tokens.accessToken
    } catch (err) {
      clearTokens()
      emitSessionExpired()
      throw err instanceof SessionExpiredError ? err : new SessionExpiredError('refresh failed')
    } finally {
      inflight = null
    }
  })()
  return inflight
}

/** 仅供单测注入 mock refresh 实现。 */
export function __setRefreshImplForTest(impl: RefreshImpl): void {
  refreshImpl = impl
}

/** 仅供单测重置模块级状态。 */
export function __resetSessionForTest(): void {
  accessToken = null
  inflight = null
  refreshImpl = defaultRefreshImpl
  expiredHandlers.clear()
}
