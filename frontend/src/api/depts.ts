/**
 * depts 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 *
 * dept 无独立树端点：list 平铺分页，前端按 parent_id 组树（见 composables/useTree.ts）。
 */
import { apiClient } from './client'
import { unwrap } from './transport'
import type { components, operations } from './generated/types'

export type DeptRead = components['schemas']['DeptRead']
export type DeptCreate = components['schemas']['DeptCreate']
export type DeptUpdate = components['schemas']['DeptUpdate']
export type DeptPage = components['schemas']['DeptPage']

/** 列表查询参数：后端 GET /depts 当前仅认 page/size，keyword 为前向兼容预留（同 users.ts）。 */
export interface DeptListParams {
  page?: number
  size?: number
  keyword?: string
}

/**
 * 部门分页列表。后端 depts_list 仅声明 page/size；keyword 暂不被后端消费
 * （cheatsheet §2 / generated 无 keyword），此处带上以便后端补齐后零改动联通——
 * openapi-fetch 运行期会序列化该额外参数，对当前后端是无副作用的多余 query。
 */
export async function listDepts(params: DeptListParams = {}): Promise<DeptPage> {
  const query = {
    page: params.page,
    size: params.size,
    ...(params.keyword ? { keyword: params.keyword } : {}),
  } as operations['depts_list']['parameters']['query']
  return unwrap(await apiClient.GET('/api/v1/depts', { params: { query } }))
}

/** 部门详情。 */
export async function getDept(deptId: number): Promise<DeptRead> {
  return unwrap(
    await apiClient.GET('/api/v1/depts/{item_id}', {
      params: { path: { item_id: deptId } },
    }),
  )
}

/** 新建部门。 */
export async function createDept(payload: DeptCreate): Promise<DeptRead> {
  return unwrap(await apiClient.POST('/api/v1/depts', { body: payload }))
}

/** 部分更新（改名 / 移动父部门 / 改状态等，PATCH merge 语义）。 */
export async function updateDept(deptId: number, payload: DeptUpdate): Promise<DeptRead> {
  return unwrap(
    await apiClient.PATCH('/api/v1/depts/{item_id}', {
      params: { path: { item_id: deptId } },
      body: payload,
    }),
  )
}

/** 删除部门（204；存在子部门或关联 409）。 */
export async function deleteDept(deptId: number): Promise<void> {
  unwrap(
    await apiClient.DELETE('/api/v1/depts/{item_id}', {
      params: { path: { item_id: deptId } },
    }),
  )
}
