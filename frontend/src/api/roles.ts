/**
 * roles 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 *
 * 角色是最复杂域：CRUD + 菜单数据权限绑定 + 自定义部门数据范围绑定。
 */
import { apiClient } from './client'
import { unwrap } from './transport'
import type { components, operations } from './generated/types'

export type RoleRead = components['schemas']['RoleRead']
export type RoleCreate = components['schemas']['RoleCreate']
export type RoleUpdate = components['schemas']['RoleUpdate']
export type RolePage = components['schemas']['RolePage']
export type BindingRead = components['schemas']['BindingRead']

/** 列表查询参数：后端 GET /roles 当前仅认 page/size，keyword 为前向兼容预留（同 users.ts）。 */
export interface RoleListParams {
  page?: number
  size?: number
  keyword?: string
}

/**
 * 角色分页列表。后端 roles_list 仅声明 page/size；keyword 暂不被后端消费
 * （cheatsheet §2 / generated 无 keyword），此处带上以便后端补齐后零改动联通——
 * openapi-fetch 运行期会序列化该额外参数，对当前后端是无副作用的多余 query。
 *
 * ⚠️ 签名扩展（新增可选 keyword）向后兼容：P6.2-A user「分配角色」对话框只传
 * { page, size }，仍正常工作；不破坏已在用的调用点。
 */
export async function listRoles(params: RoleListParams = {}): Promise<RolePage> {
  const query = {
    page: params.page,
    size: params.size,
    ...(params.keyword ? { keyword: params.keyword } : {}),
  } as operations['roles_list']['parameters']['query']
  return unwrap(await apiClient.GET('/api/v1/roles', { params: { query } }))
}

/** 角色详情。 */
export async function getRole(roleId: number): Promise<RoleRead> {
  return unwrap(
    await apiClient.GET('/api/v1/roles/{item_id}', {
      params: { path: { item_id: roleId } },
    }),
  )
}

/** 新建角色。 */
export async function createRole(payload: RoleCreate): Promise<RoleRead> {
  return unwrap(await apiClient.POST('/api/v1/roles', { body: payload }))
}

/** 部分更新（改名 / 改数据范围 / 改排序 / 改状态，PATCH merge 语义；code 后端约束不可改）。 */
export async function updateRole(roleId: number, payload: RoleUpdate): Promise<RoleRead> {
  return unwrap(
    await apiClient.PATCH('/api/v1/roles/{item_id}', {
      params: { path: { item_id: roleId } },
      body: payload,
    }),
  )
}

/** 删除角色（204；被引用 409）。 */
export async function deleteRole(roleId: number): Promise<void> {
  unwrap(
    await apiClient.DELETE('/api/v1/roles/{item_id}', {
      params: { path: { item_id: roleId } },
    }),
  )
}

/** 取角色已绑定菜单 id 集（用于 el-tree default-checked-keys）。 */
export async function getRoleMenus(roleId: number): Promise<BindingRead> {
  return unwrap(
    await apiClient.GET('/api/v1/roles/{role_id}/menus', {
      params: { path: { role_id: roleId } },
    }),
  )
}

/** 全量替换角色菜单绑定（空数组=解绑全部）。 */
export async function setRoleMenus(roleId: number, menuIds: number[]): Promise<void> {
  unwrap(
    await apiClient.PUT('/api/v1/roles/{role_id}/menus', {
      params: { path: { role_id: roleId } },
      body: { menu_ids: menuIds },
    }),
  )
}

/** 取角色已绑定自定义数据范围部门 id 集（data_scope=custom_dept 用）。 */
export async function getRoleDepts(roleId: number): Promise<BindingRead> {
  return unwrap(
    await apiClient.GET('/api/v1/roles/{role_id}/depts', {
      params: { path: { role_id: roleId } },
    }),
  )
}

/** 全量替换角色自定义数据范围部门绑定（空数组=清空）。 */
export async function setRoleDepts(roleId: number, deptIds: number[]): Promise<void> {
  unwrap(
    await apiClient.PUT('/api/v1/roles/{role_id}/depts', {
      params: { path: { role_id: roleId } },
      body: { dept_ids: deptIds },
    }),
  )
}
