import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import PostPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listPosts, createPost, deletePost } from '@/api/posts'

vi.mock('@/api/posts', () => ({
  listPosts: vi.fn(),
  getPost: vi.fn(),
  createPost: vi.fn(),
  updatePost: vi.fn(),
  deletePost: vi.fn(),
}))

const POSTS = [
  {
    id: 1,
    code: 'ceo',
    name: '董事长',
    sort_order: 1,
    status: 'active',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    code: 'dev',
    name: '研发',
    sort_order: 2,
    status: 'disabled',
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(PostPage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listPosts).mockReset()
  vi.mocked(listPosts).mockResolvedValue({
    items: POSTS,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(createPost).mockReset()
  vi.mocked(deletePost).mockReset()
  document.body.innerHTML = ''
})

describe('岗位管理页', () => {
  it('挂载即加载并渲染岗位行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listPosts).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('董事长')
    expect(wrapper.text()).toContain('研发')
  })

  it('点新增 → 打开对话框（新增岗位标题）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增岗位')
  })

  it('查询带 keyword 回第一页', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('input').setValue('研发')
    const queryBtn = wrapper.findAll('button').find((b) => b.text().includes('查询'))
    await queryBtn!.trigger('click')
    await flushPromises()
    expect(listPosts).toHaveBeenLastCalledWith(
      expect.objectContaining({ page: 1, keyword: '研发' }),
    )
  })

  it('删除走二次确认 → deletePost', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deletePost).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deletePost).toHaveBeenCalledWith(1)
  })
})
