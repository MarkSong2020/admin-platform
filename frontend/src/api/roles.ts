/**
 * roles 域 API（本任务仅放 listRoles，供用户「分配角色」对话框拉选项；
 * 角色页 CRUD 后续切片补全）。错误归一同 users.ts。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type RoleRead = components['schemas']['RoleRead']
export type RolePage = components['schemas']['RolePage']

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 角色分页列表（仅 page/size）。 */
export async function listRoles(params: { page?: number; size?: number } = {}): Promise<RolePage> {
  const { data, error, response } = await apiClient.GET('/api/v1/roles', {
    params: { query: { page: params.page, size: params.size } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}
