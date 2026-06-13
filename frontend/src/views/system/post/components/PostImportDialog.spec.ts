import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import PostImportDialog from './PostImportDialog.vue'
import { importPosts } from '@/api/posts'

vi.mock('@/api/posts', () => ({
  importPosts: vi.fn(),
}))

function mountDialog(): VueWrapper {
  return mount(PostImportDialog, {
    props: { visible: true },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

/** 直接驱动 el-upload 的 before-upload 钩子（绕过隐藏 input 在 jsdom 的不确定行为）。 */
async function triggerSelect(wrapper: VueWrapper): Promise<boolean> {
  const upload = wrapper.findComponent({ name: 'ElUpload' })
  const before = upload.props('beforeUpload') as (f: File) => Promise<boolean>
  const result = await before(new File(['xlsx'], 'posts.xlsx'))
  await flushPromises()
  return result
}

beforeEach(() => {
  vi.mocked(importPosts).mockReset()
  document.body.innerHTML = ''
})

describe('PostImportDialog', () => {
  it('导入成功（无错误）→ 展示 imported 条数并 emit imported', async () => {
    vi.mocked(importPosts).mockResolvedValue({ imported: 5, errors: [] })
    const wrapper = mountDialog()
    await flushPromises()
    const blocked = await triggerSelect(wrapper)
    expect(importPosts).toHaveBeenCalledTimes(1)
    expect(blocked).toBe(false) // 阻止 el-upload 自身 XHR
    expect(wrapper.emitted('imported')).toHaveLength(1)
    expect(document.body.textContent).toContain('导入成功，共 5 条')
  })

  it('有错误 → imported=0 不 emit，全量展示错误行（row/column/message）', async () => {
    vi.mocked(importPosts).mockResolvedValue({
      imported: 0,
      errors: [
        { row: 2, column: 'code', code: 'VALIDATION', message: '编码必填' },
        { row: 4, column: null, code: 'DUPLICATE_IN_FILE', message: '文件内重复' },
      ],
    })
    const wrapper = mountDialog()
    await flushPromises()
    await triggerSelect(wrapper)
    expect(wrapper.emitted('imported')).toBeUndefined()
    const text = document.body.textContent ?? ''
    expect(text).toContain('存在 2 处错误')
    // 错误行细节全部呈现。
    expect(text).toContain('编码必填')
    expect(text).toContain('文件内重复')
    expect(text).toContain('VALIDATION')
    expect(text).toContain('DUPLICATE_IN_FILE')
  })

  it('传输级失败（如 413）→ 走 error 提示，不 emit', async () => {
    vi.mocked(importPosts).mockRejectedValue({ code: 'file.TOO_LARGE', status: 413, message: '文件过大' })
    const wrapper = mountDialog()
    await flushPromises()
    await triggerSelect(wrapper)
    expect(wrapper.emitted('imported')).toBeUndefined()
  })
})
