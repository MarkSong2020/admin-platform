/**
 * users 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 auth.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 */
import { apiClient } from './client'
import { unwrap } from './transport'
import type { components, operations } from './generated/types'

export type UserRead = components['schemas']['UserRead']
export type UserCreate = components['schemas']['UserCreate']
export type UserUpdate = components['schemas']['UserUpdate']
export type UserPage = components['schemas']['UserPage']
export type BindingRead = components['schemas']['BindingRead']

/** 列表查询参数：后端 GET /users 当前仅认 page/size，keyword 为前向兼容预留（见下）。 */
export interface UserListParams {
  page?: number
  size?: number
  keyword?: string
}

/**
 * 用户分页列表。后端 users_list 仅声明 page/size；keyword 暂不被后端消费
 * （cheatsheet §2 / generated 无 keyword），此处带上以便后端补齐后零改动联通——
 * openapi-fetch 运行期会序列化该额外参数，对当前后端是无副作用的多余 query。
 */
export async function listUsers(params: UserListParams = {}): Promise<UserPage> {
  const query = {
    page: params.page,
    size: params.size,
    ...(params.keyword ? { keyword: params.keyword } : {}),
  } as operations['users_list']['parameters']['query']
  return unwrap(await apiClient.GET('/api/v1/users', { params: { query } }))
}

/** 用户详情。 */
export async function getUser(userId: number): Promise<UserRead> {
  return unwrap(
    await apiClient.GET('/api/v1/users/{user_id}', {
      params: { path: { user_id: userId } },
    }),
  )
}

/** 新建用户。 */
export async function createUser(payload: UserCreate): Promise<UserRead> {
  return unwrap(await apiClient.POST('/api/v1/users', { body: payload }))
}

/** 部分更新（改昵称 / 改密 / 改部门 / 改状态，PATCH merge 语义）。 */
export async function updateUser(userId: number, payload: UserUpdate): Promise<UserRead> {
  return unwrap(
    await apiClient.PATCH('/api/v1/users/{user_id}', {
      params: { path: { user_id: userId } },
      body: payload,
    }),
  )
}

/** 删除用户（204；被引用 409）。 */
export async function deleteUser(userId: number): Promise<void> {
  unwrap(
    await apiClient.DELETE('/api/v1/users/{user_id}', {
      params: { path: { user_id: userId } },
    }),
  )
}

/** 取用户已绑定角色 id 集。 */
export async function getUserRoles(userId: number): Promise<BindingRead> {
  return unwrap(
    await apiClient.GET('/api/v1/users/{user_id}/roles', {
      params: { path: { user_id: userId } },
    }),
  )
}

/** 全量替换用户角色绑定（空数组=解绑全部）。 */
export async function setUserRoles(userId: number, roleIds: number[]): Promise<void> {
  unwrap(
    await apiClient.PUT('/api/v1/users/{user_id}/roles', {
      params: { path: { user_id: userId } },
      body: { role_ids: roleIds },
    }),
  )
}

/** 取用户已绑定岗位 id 集。 */
export async function getUserPosts(userId: number): Promise<BindingRead> {
  return unwrap(
    await apiClient.GET('/api/v1/users/{user_id}/posts', {
      params: { path: { user_id: userId } },
    }),
  )
}

/** 全量替换用户岗位绑定（空数组=解绑全部）。 */
export async function setUserPosts(userId: number, postIds: number[]): Promise<void> {
  unwrap(
    await apiClient.PUT('/api/v1/users/{user_id}/posts', {
      params: { path: { user_id: userId } },
      body: { post_ids: postIds },
    }),
  )
}
