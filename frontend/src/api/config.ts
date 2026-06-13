/**
 * configs 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type ConfigRead = components['schemas']['ConfigRead']
export type ConfigCreate = components['schemas']['ConfigCreate']
export type ConfigUpdate = components['schemas']['ConfigUpdate']
export type ConfigPage = components['schemas']['ConfigPage']
export type ConfigValueRead = components['schemas']['ConfigValueRead']

/** 列表查询参数：后端 GET /configs 认 page/size/keyword（模糊匹配键名/名称）。 */
export interface ConfigListParams {
  page?: number
  size?: number
  keyword?: string
}

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 参数分页列表（page/size/keyword）。 */
export async function listConfigs(params: ConfigListParams = {}): Promise<ConfigPage> {
  const { data, error, response } = await apiClient.GET('/api/v1/configs', {
    params: {
      query: {
        page: params.page,
        size: params.size,
        ...(params.keyword ? { keyword: params.keyword } : {}),
      },
    },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 参数详情。 */
export async function getConfig(configId: number): Promise<ConfigRead> {
  const { data, error, response } = await apiClient.GET('/api/v1/configs/{item_id}', {
    params: { path: { item_id: configId } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 新建参数（201）。 */
export async function createConfig(payload: ConfigCreate): Promise<ConfigRead> {
  const { data, error, response } = await apiClient.POST('/api/v1/configs', { body: payload })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 部分更新（PATCH merge 语义；config_key 创建后不可变，不在 Update 中）。 */
export async function updateConfig(configId: number, payload: ConfigUpdate): Promise<ConfigRead> {
  const { data, error, response } = await apiClient.PATCH('/api/v1/configs/{item_id}', {
    params: { path: { item_id: configId } },
    body: payload,
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 删除参数（204；内置参数 409 → 前端提示「内置参数不可删除」）。 */
export async function deleteConfig(configId: number): Promise<void> {
  const { error, response } = await apiClient.DELETE('/api/v1/configs/{item_id}', {
    params: { path: { item_id: configId } },
  })
  if (error !== undefined) throw toApiError(error, response)
}

/** 按 key 读穿取最新值（热更新消费端点；404 不存在）。 */
export async function getConfigValue(configKey: string): Promise<ConfigValueRead> {
  const { data, error, response } = await apiClient.GET('/api/v1/configs/value/{config_key}', {
    params: { path: { config_key: configKey } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}
