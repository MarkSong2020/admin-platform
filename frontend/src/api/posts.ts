/**
 * posts 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 */
import { apiClient } from './client'
import { normalizeProblemBody, uploadMultipart, downloadBlob, type ApiError } from './transport'
import type { components } from './generated/types'
import { saveBlob } from './download'

export type PostRead = components['schemas']['PostRead']
export type PostCreate = components['schemas']['PostCreate']
export type PostUpdate = components['schemas']['PostUpdate']
export type PostPage = components['schemas']['PostPage']
export type PostImportSummary = components['schemas']['PostImportSummary']
export type PostImportRowError = components['schemas']['PostImportRowError']

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

/**
 * 岗位 Excel 导入（multipart，字段名 `upload`，对标后端 POST /posts/import）。
 * **始终 200 业务通道**：返回 PostImportSummary{imported, errors}，行级错误是业务结果不抛异常
 * （一步全有全无：errors 非空则 imported=0 全不入库）。仅传输级失败（并发 409 / 超大 413 /
 * 非法文件 422）由 transport.uploadMultipart 归一化抛出。
 */
export async function importPosts(file: File): Promise<PostImportSummary> {
  const form = new FormData()
  form.append('upload', file)
  const res = await uploadMultipart('/api/v1/posts/import', form)
  return (await res.json()) as PostImportSummary
}

/** 岗位 Excel 导出，保存为 posts.xlsx（全量 blob 下载，走 transport.downloadBlob）。 */
export async function exportPosts(): Promise<void> {
  const blob = await downloadBlob('/api/v1/posts/export')
  saveBlob(blob, 'posts.xlsx')
}
