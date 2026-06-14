/**
 * notices 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 */
import { apiClient } from './client'
import { unwrap } from './transport'
import type { components } from './generated/types'

export type NoticeRead = components['schemas']['NoticeRead']
export type NoticeCreate = components['schemas']['NoticeCreate']
export type NoticeUpdate = components['schemas']['NoticeUpdate']
export type NoticePage = components['schemas']['NoticePage']

/** 公告类型枚举（与后端 notice_type 字段对齐）。 */
export type NoticeType = 'notification' | 'announcement'

/** 列表查询参数：后端 GET /notices 认 notice_type/status/page/size。 */
export interface NoticeListParams {
  page?: number
  size?: number
  notice_type?: NoticeType
  status?: 'active' | 'disabled'
}

/** 公告分页列表（notice_type/status/page/size）。 */
export async function listNotices(params: NoticeListParams = {}): Promise<NoticePage> {
  return unwrap(
    await apiClient.GET('/api/v1/notices', {
      params: {
        query: {
          page: params.page,
          size: params.size,
          ...(params.notice_type ? { notice_type: params.notice_type } : {}),
          ...(params.status ? { status: params.status } : {}),
        },
      },
    }),
  )
}

/** 公告详情。 */
export async function getNotice(noticeId: number): Promise<NoticeRead> {
  return unwrap(
    await apiClient.GET('/api/v1/notices/{item_id}', {
      params: { path: { item_id: noticeId } },
    }),
  )
}

/** 新建公告（201）。 */
export async function createNotice(payload: NoticeCreate): Promise<NoticeRead> {
  return unwrap(await apiClient.POST('/api/v1/notices', { body: payload }))
}

/** 部分更新（PATCH merge 语义）。 */
export async function updateNotice(noticeId: number, payload: NoticeUpdate): Promise<NoticeRead> {
  return unwrap(
    await apiClient.PATCH('/api/v1/notices/{item_id}', {
      params: { path: { item_id: noticeId } },
      body: payload,
    }),
  )
}

/** 删除公告（204）。 */
export async function deleteNotice(noticeId: number): Promise<void> {
  unwrap(
    await apiClient.DELETE('/api/v1/notices/{item_id}', {
      params: { path: { item_id: noticeId } },
    }),
  )
}
