import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, {
  ElMessageBox,
  type MessageBoxData,
  type UploadFile,
} from 'element-plus'
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

  it('选文件触发 on-change（status=ready）→ 调 uploadFile 并刷新', async () => {
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
    // 驱动 el-upload 选中文件时真实触发的 on-change（auto-upload=false 下 before-upload 不触发）。
    const upload = wrapper.findComponent({ name: 'ElUpload' })
    const onChange = upload.props('onChange') as (f: UploadFile) => void | Promise<void>
    const raw = new File(['x'], 'new.txt', { type: 'text/plain' })
    await onChange({
      name: 'new.txt',
      status: 'ready',
      uid: 1,
      size: 1,
      raw,
    } as UploadFile)
    await flushPromises()
    expect(uploadFile).toHaveBeenCalledTimes(1)
    expect(uploadFile).toHaveBeenCalledWith(raw)
    expect(listFiles).toHaveBeenCalledTimes(2) // 上传后刷新
  })

  it('on-change 非 ready 状态（如上传后 success 回调）不重复触发 uploadFile', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const upload = wrapper.findComponent({ name: 'ElUpload' })
    const onChange = upload.props('onChange') as (f: UploadFile) => void | Promise<void>
    await onChange({ name: 'x', status: 'success', uid: 2, size: 1 } as UploadFile)
    await flushPromises()
    expect(uploadFile).not.toHaveBeenCalled()
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
