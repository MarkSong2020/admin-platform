/**
 * posts 域 API（本任务仅放 listPosts，供用户「分配岗位」对话框拉选项；
 * 岗位页 CRUD / Excel 后续切片补全）。错误归一同 users.ts。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type PostRead = components['schemas']['PostRead']
export type PostPage = components['schemas']['PostPage']

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 岗位分页列表（仅 page/size）。 */
export async function listPosts(params: { page?: number; size?: number } = {}): Promise<PostPage> {
  const { data, error, response } = await apiClient.GET('/api/v1/posts', {
    params: { query: { page: params.page, size: params.size } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}
