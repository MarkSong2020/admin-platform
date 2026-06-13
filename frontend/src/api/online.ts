/**
 * 在线用户监控 API 类型化封装（经 client.ts 的 openapi-fetch 实例）。
 * 端点：GET /monitor/online（分页列表）+ DELETE /monitor/online/{session_id}（强制下线）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type OnlineSession = components['schemas']['OnlineSession']
export type OnlineSessionPage = components['schemas']['OnlineSessionPage']

/** 列表查询参数：后端 GET /monitor/online 仅认 page/size。 */
export interface OnlineListParams {
  page?: number
  size?: number
}

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 在线会话分页列表。 */
export async function listOnline(params: OnlineListParams = {}): Promise<OnlineSessionPage> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/online', {
    params: { query: { page: params.page, size: params.size } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/**
 * 强制下线（撤该会话 refresh token family，204；会话不存在 404）。
 * 注意 session_id 是字符串路径参数（非 number 主键），与 user CRUD 的数字 id 不同。
 */
export async function kickOnline(sessionId: string): Promise<void> {
  const { error, response } = await apiClient.DELETE('/api/v1/monitor/online/{session_id}', {
    params: { path: { session_id: sessionId } },
  })
  if (error !== undefined) throw toApiError(error, response)
}
