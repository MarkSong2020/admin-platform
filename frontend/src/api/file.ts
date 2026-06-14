/**
 * file 域 API 封装。
 * list/delete 走 client.ts 的 openapi-fetch（JSON CRUD，类型来自 generated/）；
 * upload/download 走 transport（multipart 上传 / blob 下载，专为二进制通道而建，见 transport.ts）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 */
import { apiClient } from './client'
import { unwrap, uploadMultipart, downloadBlob } from './transport'
import type { components } from './generated/types'
import { saveBlob } from './download'

export type FileRead = components['schemas']['FileRead']
export type FilePage = components['schemas']['FilePage']

/** 文件分页列表（仅 page/size）。 */
export async function listFiles(params: { page?: number; size?: number } = {}): Promise<FilePage> {
  return unwrap(
    await apiClient.GET('/api/v1/files', {
      params: { query: { page: params.page, size: params.size } },
    }),
  )
}

/**
 * 上传文件（multipart，字段名 `upload`，对标后端 POST /files）。
 * 走 transport.uploadMultipart：浏览器自动带 multipart boundary，auth header 由 transport 注入。
 * 成功返回 201 + FileRead；413 超大 / 415 类型不过白名单由 transport 归一化抛出。
 */
export async function uploadFile(file: File): Promise<FileRead> {
  const form = new FormData()
  form.append('upload', file)
  const res = await uploadMultipart('/api/v1/files', form)
  return (await res.json()) as FileRead
}

/**
 * 下载文件并触发浏览器保存。
 * 走 transport.downloadBlob 取二进制流（auth + 401 重放由 transport 兜底），再经 saveBlob 落盘。
 */
export async function downloadFile(id: number, filename: string): Promise<void> {
  const blob = await downloadBlob(`/api/v1/files/${id}/download`)
  saveBlob(blob, filename)
}

/** 软删除文件（204；transport 之外的 JSON 通道，复用 openapi-fetch）。 */
export async function deleteFile(id: number): Promise<void> {
  unwrap(
    await apiClient.DELETE('/api/v1/files/{file_id}', {
      params: { path: { file_id: id } },
    }),
  )
}
