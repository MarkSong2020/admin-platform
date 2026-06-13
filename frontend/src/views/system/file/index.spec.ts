import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import FilePage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import { listFiles, uploadFile, downloadFile, deleteFile } from '@/api/file'

vi.mock('@/api/file', () => ({
  listFiles: vi.fn(),
  uploadFile: vi.fn(),
  downloadFile: vi.fn(),
  deleteFile: vi.fn(),
}))

const FILES = [
  {
    id: 1,
    original_filename: 'report.pdf',
    content_type: 'application/pdf',
    size_bytes: 2048,
    sha256: 'a',
    status: 'active',
    uploader_id: 1,
    created_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    original_filename: 'photo.png',
    content_type: 'image/png',
    size_bytes: 5 * 1024 * 1024,
    sha256: 'b',
    status: 'active',
    uploader_id: 1,
    created_at: '2026-06-02T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(FilePage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listFiles).mockReset()
  vi.mocked(listFiles).mockResolvedValue({
    items: FILES,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(uploadFile).mockReset()
  vi.mocked(downloadFile).mockReset()
  vi.mocked(deleteFile).mockReset()
  document.body.innerHTML = ''
})

describe('文件管理页', () => {
  it('挂载即加载并渲染文件行（含大小格式化）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listFiles).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('report.pdf')
    expect(wrapper.text()).toContain('photo.png')
    expect(wrapper.text()).toContain('2.00 KB')
    expect(wrapper.text()).toContain('5.00 MB')
  })

  it('选文件触发 before-upload → 调 uploadFile 并刷新', async () => {
    vi.mocked(uploadFile).mockResolvedValue({
      id: 9,
      original_filename: 'new.txt',
      content_type: 'text/plain',
      size_bytes: 10,
      sha256: 'c',
      status: 'active',
      uploader_id: 1,
      created_at: '2026-06-03T00:00:00Z',
    })
    const wrapper = mountPage()
    await flushPromises()
    // 直接驱动 el-upload 的 before-upload 钩子（避免依赖隐藏 input 的 jsdom 行为）。
    const upload = wrapper.findComponent({ name: 'ElUpload' })
    const before = upload.props('beforeUpload') as (f: File) => Promise<boolean>
    const result = await before(new File(['x'], 'new.txt', { type: 'text/plain' }))
    await flushPromises()
    expect(uploadFile).toHaveBeenCalledTimes(1)
    expect(result).toBe(false) // 阻止 el-upload 自身 XHR
    expect(listFiles).toHaveBeenCalledTimes(2) // 上传后刷新
  })

  it('点下载 → 调 downloadFile（带 id + 文件名）', async () => {
    vi.mocked(downloadFile).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const dlBtn = wrapper.findAll('button').find((b) => b.text().includes('下载'))
    await dlBtn!.trigger('click')
    await flushPromises()
    expect(downloadFile).toHaveBeenCalledWith(1, 'report.pdf')
  })

  it('点删除走二次确认 → deleteFile', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteFile).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteFile).toHaveBeenCalledWith(1)
  })
})
