import { describe, it, expect, vi, beforeEach } from 'vitest'
import { nextTick } from 'vue'
import { useCrudTable } from './useCrudTable'

const { confirmMock, msgSuccess, msgError } = vi.hoisted(() => ({
  confirmMock: vi.fn(),
  msgSuccess: vi.fn(),
  msgError: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessageBox: { confirm: confirmMock },
  ElMessage: { success: msgSuccess, error: msgError },
}))

interface Row {
  id: number
  name: string
}
interface Query {
  keyword?: string
}

function makeFetch(total = 3) {
  return vi.fn(async (params: { page: number; size: number; keyword?: string }) => ({
    items: [{ id: params.page, name: `p${params.page}-${params.keyword ?? ''}` }] as Row[],
    total,
  }))
}

beforeEach(() => {
  confirmMock.mockReset()
  msgSuccess.mockReset()
  msgError.mockReset()
})

describe('useCrudTable', () => {
  it('refresh 初次加载：调用 fetchPage 带 page=1/size，写入 rows/total，loading 复位', async () => {
    const fetchPage = makeFetch(42)
    const table = useCrudTable<Row, Query>({ fetchPage })
    expect(table.loading.value).toBe(false)
    const p = table.refresh()
    expect(table.loading.value).toBe(true)
    await p
    expect(fetchPage).toHaveBeenCalledWith({ page: 1, size: table.size.value })
    expect(table.rows.value).toHaveLength(1)
    expect(table.total.value).toBe(42)
    expect(table.loading.value).toBe(false)
  })

  it('handlePageChange 翻页：带新 page 调 fetchPage', async () => {
    const fetchPage = makeFetch()
    const table = useCrudTable<Row, Query>({ fetchPage })
    await table.refresh()
    fetchPage.mockClear()
    await table.handlePageChange(3)
    expect(table.page.value).toBe(3)
    expect(fetchPage).toHaveBeenCalledWith({ page: 3, size: table.size.value })
  })

  it('search：重置到第 1 页并带 query 调 fetchPage', async () => {
    const fetchPage = makeFetch()
    const table = useCrudTable<Row, Query>({ fetchPage })
    table.page.value = 5
    table.query.keyword = 'abc'
    await table.search()
    expect(table.page.value).toBe(1)
    expect(fetchPage).toHaveBeenLastCalledWith({ page: 1, size: table.size.value, keyword: 'abc' })
  })

  it('reset：清空 query、回第 1 页并刷新', async () => {
    const fetchPage = makeFetch()
    const table = useCrudTable<Row, Query>({ fetchPage })
    table.query.keyword = 'abc'
    table.page.value = 4
    await table.reset()
    expect(table.query.keyword).toBeUndefined()
    expect(table.page.value).toBe(1)
    expect(fetchPage).toHaveBeenLastCalledWith({ page: 1, size: table.size.value })
  })

  it('remove：确认后调 removeItem + 刷新 + 成功提示', async () => {
    confirmMock.mockResolvedValue('confirm')
    const removeItem = vi.fn(async () => {})
    const fetchPage = makeFetch()
    const table = useCrudTable<Row, Query>({ fetchPage, removeItem })
    await table.refresh()
    fetchPage.mockClear()
    await table.remove(7)
    expect(removeItem).toHaveBeenCalledWith(7)
    expect(fetchPage).toHaveBeenCalledTimes(1) // 删除后刷新
    expect(msgSuccess).toHaveBeenCalledTimes(1)
  })

  it('remove：用户取消确认 → 不调 removeItem', async () => {
    confirmMock.mockRejectedValue('cancel')
    const removeItem = vi.fn(async () => {})
    const table = useCrudTable<Row, Query>({ fetchPage: makeFetch(), removeItem })
    await table.remove(1)
    expect(removeItem).not.toHaveBeenCalled()
    expect(msgSuccess).not.toHaveBeenCalled()
  })

  it('remove：409 关联冲突 → 提示「存在关联，无法删除」', async () => {
    confirmMock.mockResolvedValue('confirm')
    const removeItem = vi.fn(async () => {
      throw { code: 'x.IN_USE', status: 409, message: '冲突' }
    })
    const table = useCrudTable<Row, Query>({ fetchPage: makeFetch(), removeItem })
    await table.remove(1)
    expect(msgError).toHaveBeenCalledWith('存在关联，无法删除')
  })

  it('remove：非 409 失败 → 透出后端 message', async () => {
    confirmMock.mockResolvedValue('confirm')
    const removeItem = vi.fn(async () => {
      throw { code: 'x.OOPS', status: 500, message: '服务器错误' }
    })
    const table = useCrudTable<Row, Query>({ fetchPage: makeFetch(), removeItem })
    await table.remove(1)
    expect(msgError).toHaveBeenCalledWith('服务器错误')
  })

  it('fetchPage 抛错 → loading 复位、error 提示，不悬挂', async () => {
    const fetchPage = vi.fn(async () => {
      throw { code: 'x.OOPS', status: 500, message: '加载失败' }
    })
    const table = useCrudTable<Row, Query>({ fetchPage })
    await table.refresh()
    await nextTick()
    expect(table.loading.value).toBe(false)
    expect(msgError).toHaveBeenCalledWith('加载失败')
  })
})
