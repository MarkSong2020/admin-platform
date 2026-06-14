import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import NoticePage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listNotices, createNotice, deleteNotice } from '@/api/notice'

vi.mock('@/api/notice', () => ({
  listNotices: vi.fn(),
  getNotice: vi.fn(),
  createNotice: vi.fn(),
  updateNotice: vi.fn(),
  deleteNotice: vi.fn(),
}))

const NOTICES = [
  {
    id: 1,
    title: '系统维护通知',
    content: '<b>今晚维护</b>',
    notice_type: 'notification',
    status: 'active',
    remark: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    title: '春节放假公告',
    content: '放假七天',
    notice_type: 'announcement',
    status: 'disabled',
    remark: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(NoticePage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listNotices).mockReset()
  vi.mocked(listNotices).mockResolvedValue({
    items: NOTICES,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(createNotice).mockReset()
  vi.mocked(deleteNotice).mockReset()
  document.body.innerHTML = ''
})

describe('通知公告页', () => {
  it('挂载即加载并渲染公告行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listNotices).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('系统维护通知')
    expect(wrapper.text()).toContain('春节放假公告')
  })

  it('列表渲染类型标签（通知/公告）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('通知')
    expect(wrapper.text()).toContain('公告')
  })

  it('列表不 v-html 渲染 content（防 XSS）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    // content 含 <b> 标签：列表既不展示也不以 HTML 渲染，故不应出现解析后的 <b> 节点
    expect(wrapper.find('b').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('<b>今晚维护</b>')
  })

  it('点新增 → 打开对话框，content 用 textarea 而非 v-html', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增公告')
    // content 输入用 textarea 纯文本，对话框内无 raw HTML 渲染
    expect(document.body.querySelector('textarea')).not.toBeNull()
  })

  it('删除走二次确认 → deleteNotice', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteNotice).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteNotice).toHaveBeenCalledWith(1)
  })
})
