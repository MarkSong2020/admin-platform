/**
 * openapi-fetch 类型化 JSON CRUD 客户端。
 * middleware 接 session：onRequest 注入 auth header；onResponse 401（非 auth 端点）→ refreshOnce 重放。
 * 见 spec §3.1。
 *
 * openapi-fetch 0.13.8 middleware 签名：
 *   onRequest({ request, id, schemaPath, params, options }): void | Request | Response | undefined
 *   onResponse({ request, response, id, ... }): void | Response | undefined
 *   onError({ request, error, id, ... }): void | Response | Error | undefined
 *   id 类型为 string（readonly），每次请求唯一。用 Map<string, Request> 存 clone。
 */
import createClient, { type Middleware } from 'openapi-fetch'
import type { paths } from './generated/types'
import { attachAuthHeaders, clearTokens, emitSessionExpired, refreshOnce } from './session'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const AUTH_PATHS = [
  '/api/v1/auth/login', '/api/v1/auth/refresh', '/api/v1/auth/logout', '/api/v1/auth/captcha',
]

function isAuthPath(url: string): boolean {
  return AUTH_PATHS.some((p) => url.includes(p))
}

/**
 * 保存每个请求的 clone（onRequest 时 body 未消费），供 401 重放。
 * 直接 new Request(request) 重放有 body 的请求会因 body 已被发送消费而失败（openapi-fetch 不自动 clone）。
 * 以 id（string，0.13.8 readonly 字段）为 key，避免对象引用泄漏。
 */
const pendingClones = new Map<string, Request>()

const authMiddleware: Middleware = {
  async onRequest({ request, id }) {
    attachAuthHeaders(request.headers)
    pendingClones.set(id, request.clone())
    return request
  },
  async onResponse({ request, response, id }) {
    const original = pendingClones.get(id)
    pendingClones.delete(id)
    if (response.status === 401 && !isAuthPath(request.url) && original) {
      await refreshOnce() // 共享 single-flight；失败抛 SessionExpiredError → 调用方 reject
      const retry = original.clone()
      attachAuthHeaders(retry.headers)
      const retried = await fetch(retry)
      // 刷新成功但重放仍 401：access token 在「刷新→重放」窗口内被后端吊销。此时不再二次刷新
      // （避免循环），改走会话失效统一出口（清 token + 广播 → 订阅者跳登录），与 refreshOnce
      // 失败路径语义一致，避免用户停在报 401 的破页。
      if (retried.status === 401) {
        clearTokens()
        emitSessionExpired()
      }
      return retried
    }
    return response
  },
  async onError({ id }) {
    pendingClones.delete(id)
  },
}

/**
 * 传入动态 fetch wrapper，确保测试时 vi.stubGlobal('fetch', mock) 能被捕捉到。
 * createClient 在初始化时会绑定 baseFetch = globalThis.fetch（快照），
 * 这里改为每次调用时动态读 globalThis.fetch，保持 stub 可覆盖。
 */
export const apiClient = createClient<paths>({
  baseUrl: BASE,
  fetch: (req) => globalThis.fetch(req),
})
apiClient.use(authMiddleware)
