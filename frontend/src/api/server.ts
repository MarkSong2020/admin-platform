/**
 * 服务监控 API 类型化封装（经 client.ts 的 openapi-fetch 实例）。
 * 端点：GET /monitor/server（无参，返回 CPU/内存/磁盘/进程/系统聚合指标）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type ServerMetrics = components['schemas']['ServerMetrics']

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 拉取服务监控指标（只读单视图）。 */
export async function getServerMetrics(): Promise<ServerMetrics> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/server')
  if (error !== undefined) throw toApiError(error, response)
  return data
}
