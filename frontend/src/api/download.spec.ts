import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { saveBlob } from './download'

/**
 * saveBlob 是文件 / Excel 下载的唯一落盘收口点（createObjectURL → a[download] → click → revoke）。
 * jsdom 无 URL.createObjectURL，桩入；通过 createElement 钩子捕获生成的 anchor 断言 download 文件名。
 */
describe('saveBlob 浏览器落盘', () => {
  const createSpy = vi.fn(() => 'blob:mock-url')
  const revokeSpy = vi.fn()
  let clickSpy: ReturnType<typeof vi.spyOn>
  let captured: HTMLAnchorElement | null

  beforeEach(() => {
    createSpy.mockClear()
    revokeSpy.mockClear()
    URL.createObjectURL = createSpy as unknown as typeof URL.createObjectURL
    URL.revokeObjectURL = revokeSpy as unknown as typeof URL.revokeObjectURL
    clickSpy = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    captured = null
    const realCreate = document.createElement.bind(document)
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => {
      const el = realCreate(tag)
      if (tag === 'a') captured = el as HTMLAnchorElement
      return el
    }) as typeof document.createElement)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('以给定 filename 触发下载，并在点击后释放 objectURL、移除 anchor', () => {
    const blob = new Blob(['hello'], { type: 'text/plain' })
    saveBlob(blob, '报表.xlsx')

    expect(createSpy).toHaveBeenCalledWith(blob)
    expect(captured).not.toBeNull()
    expect(captured!.download).toBe('报表.xlsx')
    expect(captured!.getAttribute('href')).toBe('blob:mock-url')
    expect(clickSpy).toHaveBeenCalledTimes(1)
    expect(revokeSpy).toHaveBeenCalledWith('blob:mock-url')
    // 落盘后 anchor 不残留在 DOM
    expect(document.body.contains(captured)).toBe(false)
  })
})
