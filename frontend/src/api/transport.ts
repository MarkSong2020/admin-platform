/**
 * 二进制/错误通道：multipart 上传、blob 下载、统一错误归一。
 * auth header 经 session.attachAuthHeaders；不与 openapi-fetch 重复造 refresh 逻辑。
 * 见 spec §3.1。
 */
import { attachAuthHeaders, refreshOnce, SessionExpiredError } from './session'

const JSON_TIMEOUT_MS = 15_000
const BINARY_TIMEOUT_MS = 120_000 // 下载/上传更长，防 Excel 导出被误 abort（spec §3.1）

/** 归一后的业务错误形状（RFC9457 ProblemDetail 子集 + 传输级）。 */
export interface ApiError {
  code: string
  status: number
  message: string
  detail?: string
}

/** 抛出/异常侧归一：SessionExpiredError 必须透传不降级。 */
export function normalizeApiError(err: unknown): SessionExpiredError | ApiError {
  if (err instanceof SessionExpiredError) return err
  if (err instanceof DOMException && err.name === 'AbortError') {
    return { code: 'TIMEOUT', status: 0, message: '请求超时' }
  }
  if (err instanceof Error) {
    return { code: 'NETWORK', status: 0, message: err.message }
  }
  return { code: 'UNKNOWN', status: 0, message: String(err) }
}

/**
 * 已解析 body 侧归一：优先读 RFC9457 ProblemDetail 的 type/title/status/detail。
 * 供 normalizeResponseError（自己读 body）与 openapi-fetch 调用方（body 已被 openapi-fetch 消费、
 * 仅剩解析后的 error 对象）共用，归一化逻辑单一来源。
 */
export function normalizeProblemBody(
  body: unknown,
  fallbackStatus: number,
  fallbackMessage = '请求失败',
): ApiError {
  if (body && typeof body === 'object') {
    const pd = body as Record<string, unknown>
    return {
      code: typeof pd.type === 'string' ? pd.type : `HTTP_${fallbackStatus}`,
      status: typeof pd.status === 'number' ? pd.status : fallbackStatus,
      message: typeof pd.title === 'string' ? pd.title : fallbackMessage,
      detail: typeof pd.detail === 'string' ? pd.detail : undefined,
    }
  }
  return { code: `HTTP_${fallbackStatus}`, status: fallbackStatus, message: fallbackMessage }
}

/**
 * 非 2xx Response 侧归一：优先解析 RFC9457 ProblemDetail（spec §3.1）。
 * blob/multipart 接口失败时后端仍返回 JSON ProblemDetail，这里读出 type/title/status/detail。
 */
export async function normalizeResponseError(res: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await res.clone().json()
  } catch {
    // 非 JSON（纯文本/空）→ normalizeProblemBody 用 status 兜底
  }
  return normalizeProblemBody(body, res.status, res.statusText || '请求失败')
}

function withTimeout(ms: number): { signal: AbortSignal; done: () => void } {
  const ctrl = new AbortController()
  const id = setTimeout(() => ctrl.abort(), ms)
  return { signal: ctrl.signal, done: () => clearTimeout(id) }
}

const BASE = import.meta.env.VITE_API_BASE ?? ''

export async function downloadBlob(path: string): Promise<Blob> {
  const send = async (): Promise<Response> => {
    const headers = new Headers()
    attachAuthHeaders(headers)
    const t = withTimeout(BINARY_TIMEOUT_MS)
    try {
      return await fetch(`${BASE}${path}`, { headers, signal: t.signal })
    } finally {
      t.done()
    }
  }
  let res = await send()
  if (res.status === 401) {
    await refreshOnce() // 与 JSON 通道共享 single-flight；失败抛 SessionExpiredError
    res = await send()
  }
  if (!res.ok) throw await normalizeResponseError(res) // RFC9457 归一，保留 status/code
  return await res.blob()
}

export async function uploadMultipart(path: string, form: FormData): Promise<Response> {
  // 不手动设 Content-Type：浏览器会带 multipart boundary。
  const send = async (): Promise<Response> => {
    const headers = new Headers()
    attachAuthHeaders(headers)
    const t = withTimeout(BINARY_TIMEOUT_MS)
    try {
      return await fetch(`${BASE}${path}`, { method: 'POST', headers, body: form, signal: t.signal })
    } finally {
      t.done()
    }
  }
  let res = await send()
  if (res.status === 401) {
    await refreshOnce() // 与 JSON 通道共享 single-flight
    res = await send()
  }
  // import 业务通道是 200+summary.errors（spec），故 200 即使含行级错误也放行；
  // 仅传输级失败（409 并发 / 413 超大 / 4xx/5xx）归一抛出。
  if (!res.ok) throw await normalizeResponseError(res)
  return res
}

export const _timeouts = { JSON_TIMEOUT_MS, BINARY_TIMEOUT_MS }
