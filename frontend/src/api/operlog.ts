/**
 * 操作日志（审计事件）域 API 类型化封装。只读：列表 + 详情。
 * 经 client.ts 的 openapi-fetch 实例，类型来自 generated/，错误归一参照 users.ts 范式。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components, operations } from './generated/types'

export type AuditEventRead = components['schemas']['AuditEventRead']
export type AuditEventDetail = components['schemas']['AuditEventDetail']
export type AuditEventPage = components['schemas']['AuditEventPage']

/** 列表查询参数：分页 + 后端支持的三个可选过滤维度。 */
export interface OperlogListParams {
  page?: number
  size?: number
  event_type?: string
  result_status?: string
  actor_user_id?: number
}

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 操作日志分页列表（GET /monitor/operlog，支持 event_type/result_status/actor_user_id 过滤）。 */
export async function listOperlog(params: OperlogListParams = {}): Promise<AuditEventPage> {
  const query = {
    page: params.page,
    size: params.size,
    ...(params.event_type ? { event_type: params.event_type } : {}),
    ...(params.result_status ? { result_status: params.result_status } : {}),
    ...(params.actor_user_id !== undefined ? { actor_user_id: params.actor_user_id } : {}),
  } as operations['monitor_operlog_list']['parameters']['query']
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/operlog', {
    params: { query },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 操作日志详情（GET /monitor/operlog/{event_pk}，含完整 payload / request_id / trace_id / user_agent）。 */
export async function getOperlog(eventPk: number): Promise<AuditEventDetail> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/operlog/{event_pk}', {
    params: { path: { event_pk: eventPk } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}
