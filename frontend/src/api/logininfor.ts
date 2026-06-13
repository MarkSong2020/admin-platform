/**
 * 登录日志域 API 类型化封装。只读：列表 + 详情。
 * 经 client.ts 的 openapi-fetch 实例，类型来自 generated/，错误归一参照 users.ts 范式。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components, operations } from './generated/types'

export type LoginLogRead = components['schemas']['LoginLogRead']
export type LoginLogPage = components['schemas']['LoginLogPage']

/** 列表查询参数：分页 + 后端支持的 username/status 过滤。 */
export interface LogininforListParams {
  page?: number
  size?: number
  username?: string
  status?: string
}

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 登录日志分页列表（GET /monitor/logininfor，支持 username/status 过滤）。 */
export async function listLogininfor(params: LogininforListParams = {}): Promise<LoginLogPage> {
  const query = {
    page: params.page,
    size: params.size,
    ...(params.username ? { username: params.username } : {}),
    ...(params.status ? { status: params.status } : {}),
  } as operations['monitor_logininfor_list']['parameters']['query']
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/logininfor', {
    params: { query },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 登录日志详情（GET /monitor/logininfor/{log_pk}）。 */
export async function getLogininfor(logPk: number): Promise<LoginLogRead> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/logininfor/{log_pk}', {
    params: { path: { log_pk: logPk } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}
