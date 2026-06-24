import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, {
  ElMessage,
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
  beforeEach(() => {
    vi.useRealTimers()
  })

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
    const created = {
      id: 9,
      original_filename: 'new.txt',
      content_type: 'text/plain',
      size_bytes: 10,
      sha256: 'c',
      status: 'active',
      uploader_id: 1,
      created_at: '2026-06-03T00:00:00Z',
    }
    vi.mocked(uploadFile).mockResolvedValue(created)
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(listFiles).mockResolvedValueOnce({
      items: [created, ...FILES],
      page: 1,
      size: 20,
      total: 3,
      total_pages: 1,
    })
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
    expect(listFiles).toHaveBeenLastCalledWith({ page: 1, size: 20 })
    expect(wrapper.text()).toContain('new.txt')
  })

  it('上传后首次刷新未看到新文件时重试并回到第一页', async () => {
    vi.useFakeTimers()
    const created = {
      id: 9,
      original_filename: 'new.txt',
      content_type: 'text/plain',
      size_bytes: 10,
      sha256: 'c',
      status: 'active',
      uploader_id: 1,
      created_at: '2026-06-03T00:00:00Z',
    }
    vi.mocked(uploadFile).mockResolvedValue(created)
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(listFiles)
      .mockResolvedValueOnce({
        items: FILES,
        page: 1,
        size: 20,
        total: 2,
        total_pages: 1,
      })
      .mockResolvedValueOnce({
        items: [created, ...FILES],
        page: 1,
        size: 20,
        total: 3,
        total_pages: 1,
      })

    const pagination = wrapper.findComponent({ name: 'TablePagination' })
    pagination.vm.$emit('update:page', 2)
    await flushPromises()

    const upload = wrapper.findComponent({ name: 'ElUpload' })
    const onChange = upload.props('onChange') as (f: UploadFile) => void | Promise<void>
    const raw = new File(['x'], 'new.txt', { type: 'text/plain' })
    const pending = onChange({
      name: 'new.txt',
      status: 'ready',
      uid: 1,
      size: 1,
      raw,
    } as UploadFile)
    await flushPromises()

    expect(listFiles).toHaveBeenCalledTimes(2)
    expect(listFiles).toHaveBeenLastCalledWith({ page: 1, size: 20 })

    await vi.advanceTimersByTimeAsync(50)
    await pending
    await flushPromises()

    expect(listFiles).toHaveBeenCalledTimes(3)
    expect(listFiles).toHaveBeenLastCalledWith({ page: 1, size: 20 })
    expect(wrapper.text()).toContain('new.txt')
    vi.useRealTimers()
  })

  it('选文件触发 on-change（status=ready）→ 提交窗口内多次刷新都未命中时不本地篡改分页结果', async () => {
    vi.useFakeTimers()
    const infoSpy = vi.spyOn(ElMessage, 'info').mockImplementation(vi.fn() as never)
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
    const pending = onChange({
      name: 'new.txt',
      status: 'ready',
      uid: 1,
      size: 1,
      raw,
    } as UploadFile)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(50)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(150)
    await pending
    expect(uploadFile).toHaveBeenCalledTimes(1)
    expect(uploadFile).toHaveBeenCalledWith(raw)
    expect(listFiles).toHaveBeenCalledTimes(4) // 首次刷新 + 两次重试 + 初始加载
    expect(wrapper.text()).not.toContain('new.txt')
    expect(wrapper.text()).toContain('report.pdf')
    expect(infoSpy).toHaveBeenCalledWith('上传成功，列表稍后会显示最新文件')
    vi.useRealTimers()
  })

  it('上传成功但刷新失败时不误报上传失败', async () => {
    const successSpy = vi.spyOn(ElMessage, 'success').mockImplementation(vi.fn() as never)
    const warningSpy = vi.spyOn(ElMessage, 'warning').mockImplementation(vi.fn() as never)
    const errorSpy = vi.spyOn(ElMessage, 'error').mockImplementation(vi.fn() as never)
    const created = {
      id: 9,
      original_filename: 'new.txt',
      content_type: 'text/plain',
      size_bytes: 10,
      sha256: 'c',
      status: 'active',
      uploader_id: 1,
      created_at: '2026-06-03T00:00:00Z',
    }
    vi.mocked(uploadFile).mockResolvedValue(created)
    const wrapper = mountPage()
    await flushPromises()
    vi.mocked(listFiles).mockRejectedValueOnce(new Error('network down'))

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

    expect(uploadFile).toHaveBeenCalledWith(raw)
    expect(successSpy).toHaveBeenCalledWith('上传成功：new.txt')
    expect(warningSpy).toHaveBeenCalledWith(expect.stringContaining('上传成功，但列表刷新失败'))
    expect(errorSpy).not.toHaveBeenCalled()
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
