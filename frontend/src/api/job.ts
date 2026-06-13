/**
 * 定时任务（monitor/jobs）域 API 类型化封装，经 client.ts 的 openapi-fetch 实例。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts / posts.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 *
 * 字段口径（见 cheatsheet §5）：写侧用 `params`（对象），读侧字段是 `params_json`；
 * 任务 status 取值 `"enabled" | "disabled"`（区别于业务实体的 active/disabled）。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type ScheduledTaskRead = components['schemas']['ScheduledTaskRead']
export type ScheduledTaskCreate = components['schemas']['ScheduledTaskCreate']
export type ScheduledTaskUpdate = components['schemas']['ScheduledTaskUpdate']
export type ScheduledTaskPage = components['schemas']['ScheduledTaskPage']
export type ScheduledTaskLogRead = components['schemas']['ScheduledTaskLogRead']
export type ScheduledTaskLogPage = components['schemas']['ScheduledTaskLogPage']
export type HandlerInfo = components['schemas']['HandlerInfo']

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 任务列表查询参数（status / handler_key 可选过滤）。 */
export interface JobListParams {
  page?: number
  size?: number
  status?: string
  handler_key?: string
}

/** 执行日志查询参数（task_id / status 可选过滤）。 */
export interface JobLogListParams {
  page?: number
  size?: number
  task_id?: number
  status?: string
}

/** 定时任务分页列表。 */
export async function listJobs(params: JobListParams = {}): Promise<ScheduledTaskPage> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/jobs', {
    params: {
      query: {
        page: params.page,
        size: params.size,
        ...(params.status ? { status: params.status } : {}),
        ...(params.handler_key ? { handler_key: params.handler_key } : {}),
      },
    },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 任务详情。 */
export async function getJob(taskId: number): Promise<ScheduledTaskRead> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/jobs/{task_id}', {
    params: { path: { task_id: taskId } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 新建任务（201）。handler_key 必须取自 listHandlers 白名单。 */
export async function createJob(payload: ScheduledTaskCreate): Promise<ScheduledTaskRead> {
  const { data, error, response } = await apiClient.POST('/api/v1/monitor/jobs', { body: payload })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 部分更新（PATCH merge 语义，全字段可选）。 */
export async function updateJob(
  taskId: number,
  payload: ScheduledTaskUpdate,
): Promise<ScheduledTaskRead> {
  const { data, error, response } = await apiClient.PATCH('/api/v1/monitor/jobs/{task_id}', {
    params: { path: { task_id: taskId } },
    body: payload,
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 删除任务（204）。 */
export async function deleteJob(taskId: number): Promise<void> {
  const { error, response } = await apiClient.DELETE('/api/v1/monitor/jobs/{task_id}', {
    params: { path: { task_id: taskId } },
  })
  if (error !== undefined) throw toApiError(error, response)
}

/** handler 白名单（裸数组），创建/编辑表单的 handler_key 下拉选项来源。 */
export async function listHandlers(): Promise<HandlerInfo[]> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/jobs/handlers')
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 手动触发执行（无 body）。返回本次执行日志；409 并发冲突。 */
export async function runJob(taskId: number): Promise<ScheduledTaskLogRead> {
  const { data, error, response } = await apiClient.POST('/api/v1/monitor/jobs/{task_id}/run', {
    params: { path: { task_id: taskId } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 执行日志分页列表（按 task_id / status 过滤）。 */
export async function listJobLogs(params: JobLogListParams = {}): Promise<ScheduledTaskLogPage> {
  const { data, error, response } = await apiClient.GET('/api/v1/monitor/jobs/logs', {
    params: {
      query: {
        page: params.page,
        size: params.size,
        ...(params.task_id !== undefined ? { task_id: params.task_id } : {}),
        ...(params.status ? { status: params.status } : {}),
      },
    },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}
