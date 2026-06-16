import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import ElementPlus, { ElMessage } from 'element-plus'
import UserPostsDialog from './UserPostsDialog.vue'
import { listPosts, type PostRead } from '@/api/posts'
import { getUserPosts, setUserPosts } from '@/api/users'

// 跨文件依赖：listPosts 来自 @/api/posts，单测 mock 不依赖真实文件。
vi.mock('@/api/posts', () => ({ listPosts: vi.fn() }))
vi.mock('@/api/users', () => ({
  getUserPosts: vi.fn(),
  setUserPosts: vi.fn(),
}))

const POSTS: PostRead[] = [
  { id: 10, code: 'dev', name: '研发', sort_order: 0, status: 'active', created_at: '', updated_at: '' },
  { id: 11, code: 'qa', name: '测试', sort_order: 1, status: 'active', created_at: '', updated_at: '' },
]

function mountDialog(userId: number | null = 5) {
  return mount(UserPostsDialog, {
    props: { userId, visible: false },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.mocked(listPosts).mockReset()
  vi.mocked(listPosts).mockResolvedValue({
    items: POSTS,
    page: 1,
    size: 100,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(getUserPosts).mockReset()
  vi.mocked(getUserPosts).mockResolvedValue({ ids: [10] })
  vi.mocked(setUserPosts).mockReset()
  vi.mocked(setUserPosts).mockResolvedValue(undefined)
  document.body.innerHTML = ''
})

describe('UserPostsDialog', () => {
  it('打开时并发加载全部岗位 + 用户已绑岗位，选项标签为「名（code）」', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listPosts).toHaveBeenCalledWith({ page: 1, size: 100 })
    expect(getUserPosts).toHaveBeenCalledWith(5)
    const vm = wrapper.vm as unknown as {
      options: { key: number; label: string }[]
      selected: number[]
    }
    expect(vm.options).toEqual([
      { key: 10, label: '研发（dev）' },
      { key: 11, label: '测试（qa）' },
    ])
    expect(vm.selected).toEqual([10])
  })

  it('确定 → setUserPosts 携带已选岗位后关闭', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    const okBtn = Array.from(document.body.querySelectorAll('button')).find((b) =>
      (b.textContent ?? '').includes('确定'),
    )
    okBtn!.click()
    await flushPromises()
    expect(setUserPosts).toHaveBeenCalledWith(5, [10])
    expect(wrapper.emitted('update:visible')?.at(-1)).toEqual([false])
  })

  it('userId 为 null 时不加载，submit 早退', async () => {
    const wrapper = mountDialog(null)
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(listPosts).not.toHaveBeenCalled()
    const vm = wrapper.vm as unknown as { submit: () => Promise<void> }
    await vm.submit()
    expect(setUserPosts).not.toHaveBeenCalled()
  })

  it('加载失败 → ElMessage.error', async () => {
    const errSpy = vi.spyOn(ElMessage, 'error')
    vi.mocked(listPosts).mockRejectedValue(new Error('boom'))
    const wrapper = mountDialog()
    await wrapper.setProps({ visible: true })
    await flushPromises()
    expect(errSpy).toHaveBeenCalled()
    errSpy.mockRestore()
  })
})
