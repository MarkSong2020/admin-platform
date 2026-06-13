/**
 * posts 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type PostRead = components['schemas']['PostRead']
export type PostCreate = components['schemas']['PostCreate']
export type PostUpdate = components['schemas']['PostUpdate']
export type PostPage = components['schemas']['PostPage']

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

/** 岗位分页列表（仅 page/size）。user 页「分配岗位」对话框也复用此签名，不要改。 */
export async function listPosts(params: { page?: number; size?: number } = {}): Promise<PostPage> {
  const { data, error, response } = await apiClient.GET('/api/v1/posts', {
    params: { query: { page: params.page, size: params.size } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 岗位详情。 */
export async function getPost(postId: number): Promise<PostRead> {
  const { data, error, response } = await apiClient.GET('/api/v1/posts/{item_id}', {
    params: { path: { item_id: postId } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 新建岗位（201）。 */
export async function createPost(payload: PostCreate): Promise<PostRead> {
  const { data, error, response } = await apiClient.POST('/api/v1/posts', { body: payload })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 部分更新（PATCH merge 语义；code 一般不改）。 */
export async function updatePost(postId: number, payload: PostUpdate): Promise<PostRead> {
  const { data, error, response } = await apiClient.PATCH('/api/v1/posts/{item_id}', {
    params: { path: { item_id: postId } },
    body: payload,
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 删除岗位（204；被引用 409）。 */
export async function deletePost(postId: number): Promise<void> {
  const { error, response } = await apiClient.DELETE('/api/v1/posts/{item_id}', {
    params: { path: { item_id: postId } },
  })
  if (error !== undefined) throw toApiError(error, response)
}
