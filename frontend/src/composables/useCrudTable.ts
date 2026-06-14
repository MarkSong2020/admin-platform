/**
 * 可复用 CRUD 列表 composable（user/role/menu/dept/post 五页共用）。
 * 纯逻辑、不依赖具体域：管 列表数据 / loading / 分页 / 查询参数 / 刷新 / 翻页 / 删除确认。
 * fetchPage 由调用方注入（接 {page,size,...query} 返回 {items,total}），removeItem 可选。
 * 见 spec §8 P6.2。
 */
import { ref, reactive, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { normalizeApiError, type ApiError } from '@/api/transport'

/**
 * 归一为展示用 ApiError。normalizeApiError 已能透传归一化的 ApiError 普通对象，
 * 本函数额外把 SessionExpiredError 降级成展示友好的 SESSION_EXPIRED（避免 session 跳转
 * 信号以原始 typed error 形态泄漏到列表 UI——跳转由 client/transport 兜底，这里仅取 message）。
 */
function toApiError(err: unknown): ApiError {
  const normalized = normalizeApiError(err)
  // SessionExpiredError（非普通 ApiError）→ 列表层只需展示文案。
  return 'code' in normalized
    ? normalized
    : { code: 'SESSION_EXPIRED', status: 401, message: '登录已失效' }
}

/** fetchPage 入参：分页 + 展开的查询条件。 */
export type FetchPageParams<TQuery> = { page: number; size: number } & TQuery

/** fetchPage 返回：列表项 + 总数（适配后端 XxxPage 包络）。 */
export interface PageResult<TRow> {
  items: TRow[]
  total: number
}

export interface UseCrudTableOptions<TRow, TQuery> {
  /** 拉取一页数据。 */
  fetchPage: (params: FetchPageParams<TQuery>) => Promise<PageResult<TRow>>
  /** 删除单项（可选；无则 remove 不可用）。 */
  removeItem?: (id: number) => Promise<void>
  /** 每页条数默认值（默认 20，对齐后端上限 100）。 */
  defaultSize?: number
}

export interface UseCrudTableReturn<TRow, TQuery> {
  rows: Ref<TRow[]>
  loading: Ref<boolean>
  total: Ref<number>
  page: Ref<number>
  size: Ref<number>
  /** 响应式查询条件（与搜索栏 v-model 双向绑定）。 */
  query: TQuery
  /** 按当前 page/size/query 重新加载。 */
  refresh: () => Promise<void>
  /** 翻到指定页并加载。 */
  handlePageChange: (nextPage: number) => Promise<void>
  /** 查询：回第 1 页后加载（保留 query）。 */
  search: () => Promise<void>
  /** 重置：清空 query、回第 1 页后加载。 */
  reset: () => Promise<void>
  /** 删除：二次确认 → removeItem → 刷新 + 提示（409 给关联提示）。 */
  remove: (id: number) => Promise<void>
}

export function useCrudTable<TRow, TQuery extends object>(
  options: UseCrudTableOptions<TRow, TQuery>,
): UseCrudTableReturn<TRow, TQuery> {
  const rows = ref<TRow[]>([]) as Ref<TRow[]>
  const loading = ref(false)
  const total = ref(0)
  const page = ref(1)
  const size = ref(options.defaultSize ?? 20)
  const query = reactive({} as TQuery) as TQuery

  async function refresh(): Promise<void> {
    loading.value = true
    try {
      const params = { page: page.value, size: size.value, ...query } as FetchPageParams<TQuery>
      const result = await options.fetchPage(params)
      rows.value = result.items
      total.value = result.total
    } catch (err) {
      ElMessage.error(toApiError(err).message)
    } finally {
      loading.value = false
    }
  }

  async function handlePageChange(nextPage: number): Promise<void> {
    page.value = nextPage
    await refresh()
  }

  async function search(): Promise<void> {
    page.value = 1
    await refresh()
  }

  async function reset(): Promise<void> {
    for (const key of Object.keys(query)) {
      delete (query as Record<string, unknown>)[key]
    }
    page.value = 1
    await refresh()
  }

  async function remove(id: number): Promise<void> {
    if (!options.removeItem) return
    try {
      await ElMessageBox.confirm('确认删除该记录吗？', '提示', {
        type: 'warning',
        confirmButtonText: '确定',
        cancelButtonText: '取消',
      })
    } catch {
      return // 用户取消，不视为错误
    }
    try {
      await options.removeItem(id)
      ElMessage.success('删除成功')
      await refresh()
    } catch (err) {
      const apiError = toApiError(err)
      const message = apiError.status === 409 ? '存在关联，无法删除' : apiError.message
      ElMessage.error(message)
    }
  }

  return {
    rows,
    loading,
    total,
    page,
    size,
    query,
    refresh,
    handlePageChange,
    search,
    reset,
    remove,
  }
}
