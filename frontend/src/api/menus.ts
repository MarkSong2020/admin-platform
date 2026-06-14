/**
 * menus 域 API 类型化封装（经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * 错误经 transport.normalizeProblemBody 归一化抛出（参照 users.ts / depts.ts 范式）。
 * 401 自动 refresh 重放由 client.ts middleware 兜底，本层不重复造。
 *
 * menu 无独立树端点：list 平铺分页（size 上限 100），前端按 parent_id 组树
 * （见 composables/useTree.ts）。role 页装配菜单授权树会 import listMenus，签名固定勿改。
 */
import { apiClient } from './client'
import { unwrap } from './transport'
import type { components, operations } from './generated/types'

export type MenuRead = components['schemas']['MenuRead']
export type MenuCreate = components['schemas']['MenuCreate']
export type MenuUpdate = components['schemas']['MenuUpdate']
export type MenuPage = components['schemas']['MenuPage']

/** 列表查询参数：后端 GET /menus 仅认 page/size（size 上限 100）。 */
export interface MenuListParams {
  page?: number
  size?: number
}

/**
 * 菜单分页列表（平铺）。后端 menus_list 仅声明 page/size；
 * 前端按 parent_id 用 buildTree 组树供 el-table / el-tree-select 使用。
 * role 页装配菜单授权树复用此函数，签名（{page,size}）固定。
 */
export async function listMenus(params: MenuListParams = {}): Promise<MenuPage> {
  const query = {
    page: params.page,
    size: params.size,
  } as operations['menus_list']['parameters']['query']
  return unwrap(await apiClient.GET('/api/v1/menus', { params: { query } }))
}

/** 菜单详情。 */
export async function getMenu(menuId: number): Promise<MenuRead> {
  return unwrap(
    await apiClient.GET('/api/v1/menus/{item_id}', {
      params: { path: { item_id: menuId } },
    }),
  )
}

/** 新建菜单。 */
export async function createMenu(payload: MenuCreate): Promise<MenuRead> {
  return unwrap(await apiClient.POST('/api/v1/menus', { body: payload }))
}

/** 部分更新（改名 / 移动父菜单 / 改类型字段等，PATCH merge 语义）。 */
export async function updateMenu(menuId: number, payload: MenuUpdate): Promise<MenuRead> {
  return unwrap(
    await apiClient.PATCH('/api/v1/menus/{item_id}', {
      params: { path: { item_id: menuId } },
      body: payload,
    }),
  )
}

/** 删除菜单（204；存在子菜单 409）。 */
export async function deleteMenu(menuId: number): Promise<void> {
  unwrap(
    await apiClient.DELETE('/api/v1/menus/{item_id}', {
      params: { path: { item_id: menuId } },
    }),
  )
}
