/**
 * dict 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts / posts.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 * 含「字典类型」+「字典数据」两组资源：删有数据的类型走 FK RESTRICT → 409。
 */
import { apiClient } from './client'
import { normalizeProblemBody, type ApiError } from './transport'
import type { components } from './generated/types'

export type DictTypeRead = components['schemas']['DictTypeRead']
export type DictTypeCreate = components['schemas']['DictTypeCreate']
export type DictTypeUpdate = components['schemas']['DictTypeUpdate']
export type DictTypePage = components['schemas']['DictTypePage']

export type DictDataRead = components['schemas']['DictDataRead']
export type DictDataCreate = components['schemas']['DictDataCreate']
export type DictDataUpdate = components['schemas']['DictDataUpdate']
export type DictDataPage = components['schemas']['DictDataPage']

function toApiError(error: unknown, response: Response): ApiError {
  return normalizeProblemBody(error, response.status, response.statusText || '请求失败')
}

// ---------------------------------------------------------------------------
// 字典类型 /dict/types
// ---------------------------------------------------------------------------

/** 字典类型分页列表（page/size + keyword 模糊匹配名称/类型）。 */
export async function listDictTypes(
  params: { page?: number; size?: number; keyword?: string } = {},
): Promise<DictTypePage> {
  const { data, error, response } = await apiClient.GET('/api/v1/dict/types', {
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

/** 字典类型详情。 */
export async function getDictType(typeId: number): Promise<DictTypeRead> {
  const { data, error, response } = await apiClient.GET('/api/v1/dict/types/{type_id}', {
    params: { path: { type_id: typeId } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 新建字典类型（201）。 */
export async function createDictType(payload: DictTypeCreate): Promise<DictTypeRead> {
  const { data, error, response } = await apiClient.POST('/api/v1/dict/types', { body: payload })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 部分更新字典类型（PATCH；type 不可改，is_builtin 可切换解保护）。 */
export async function updateDictType(
  typeId: number,
  payload: DictTypeUpdate,
): Promise<DictTypeRead> {
  const { data, error, response } = await apiClient.PATCH('/api/v1/dict/types/{type_id}', {
    params: { path: { type_id: typeId } },
    body: payload,
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 删除字典类型（204；内置或有数据 409）。 */
export async function deleteDictType(typeId: number): Promise<void> {
  const { error, response } = await apiClient.DELETE('/api/v1/dict/types/{type_id}', {
    params: { path: { type_id: typeId } },
  })
  if (error !== undefined) throw toApiError(error, response)
}

// ---------------------------------------------------------------------------
// 字典数据 /dict/data
// ---------------------------------------------------------------------------

/** 字典数据分页列表（page/size + dict_type_id 过滤）。 */
export async function listDictData(
  params: { page?: number; size?: number; dict_type_id?: number } = {},
): Promise<DictDataPage> {
  const { data, error, response } = await apiClient.GET('/api/v1/dict/data', {
    params: {
      query: {
        page: params.page,
        size: params.size,
        ...(params.dict_type_id !== undefined ? { dict_type_id: params.dict_type_id } : {}),
      },
    },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 字典数据详情。 */
export async function getDictData(dataId: number): Promise<DictDataRead> {
  const { data, error, response } = await apiClient.GET('/api/v1/dict/data/{data_id}', {
    params: { path: { data_id: dataId } },
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 新建字典数据（201）。 */
export async function createDictData(payload: DictDataCreate): Promise<DictDataRead> {
  const { data, error, response } = await apiClient.POST('/api/v1/dict/data', { body: payload })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 部分更新字典数据（PATCH；不含 dict_type_id，数据不跨类型迁移）。 */
export async function updateDictData(
  dataId: number,
  payload: DictDataUpdate,
): Promise<DictDataRead> {
  const { data, error, response } = await apiClient.PATCH('/api/v1/dict/data/{data_id}', {
    params: { path: { data_id: dataId } },
    body: payload,
  })
  if (error !== undefined) throw toApiError(error, response)
  return data
}

/** 删除字典数据（204）。 */
export async function deleteDictData(dataId: number): Promise<void> {
  const { error, response } = await apiClient.DELETE('/api/v1/dict/data/{data_id}', {
    params: { path: { data_id: dataId } },
  })
  if (error !== undefined) throw toApiError(error, response)
}
