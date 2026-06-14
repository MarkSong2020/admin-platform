import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus, { ElMessageBox, type MessageBoxData } from 'element-plus'
import JobPage from './index.vue'
import { hasPermi } from '@/directives/has-permi'
import { usePermissionStore } from '@/stores/permission'
import {
  listJobs,
  deleteJob,
  runJob,
  listJobLogs,
  listHandlers,
  type ScheduledTaskRead,
} from '@/api/job'

vi.mock('@/api/job', () => ({
  listJobs: vi.fn(),
  getJob: vi.fn(),
  createJob: vi.fn(),
  updateJob: vi.fn(),
  deleteJob: vi.fn(),
  listHandlers: vi.fn(),
  runJob: vi.fn(),
  listJobLogs: vi.fn(),
}))

const JOBS: ScheduledTaskRead[] = [
  {
    id: 1,
    name: '每日清理',
    handler_key: 'cleanup',
    cron_expression: '0 0 * * *',
    cron_timezone: 'Asia/Shanghai',
    params_json: {},
    status: 'enabled',
    last_status: 'success',
    last_run_at: '2026-06-12T00:00:00Z',
    next_run_at: '2026-06-13T00:00:00Z',
    allow_concurrent: false,
    misfire_grace_seconds: 300,
    timeout_seconds: null,
    remark: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
  {
    id: 2,
    name: '对账',
    handler_key: 'reconcile',
    cron_expression: '0 1 * * *',
    cron_timezone: 'Asia/Shanghai',
    params_json: {},
    status: 'disabled',
    last_status: null,
    last_run_at: null,
    next_run_at: null,
    allow_concurrent: false,
    misfire_grace_seconds: 300,
    timeout_seconds: null,
    remark: null,
    created_at: '2026-06-01T00:00:00Z',
    updated_at: '2026-06-01T00:00:00Z',
  },
]

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(JobPage, {
    global: { plugins: [ElementPlus, pinia], directives: { hasPermi } },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.restoreAllMocks() // 清掉上个用例 spyOn(ElMessageBox.confirm) 等遗留 spy，避免跨用例计数泄漏
  usePermissionStore().setPermissions(['*:*:*'])
  vi.mocked(listJobs).mockReset()
  vi.mocked(listJobs).mockResolvedValue({
    items: JOBS,
    page: 1,
    size: 20,
    total: 2,
    total_pages: 1,
  })
  vi.mocked(deleteJob).mockReset()
  vi.mocked(runJob).mockReset()
  vi.mocked(listHandlers).mockReset()
  vi.mocked(listHandlers).mockResolvedValue([])
  vi.mocked(listJobLogs).mockReset()
  vi.mocked(listJobLogs).mockResolvedValue({
    items: [],
    page: 1,
    size: 20,
    total: 0,
    total_pages: 0,
  })
  document.body.innerHTML = ''
})

describe('定时任务管理页', () => {
  it('挂载即加载并渲染任务行', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(listJobs).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('每日清理')
    expect(wrapper.text()).toContain('对账')
  })

  it('点新增 → 打开对话框（新增任务标题）', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const addBtn = wrapper.findAll('button').find((b) => b.text().includes('新增'))
    await addBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('新增任务')
  })

  it('删除走二次确认 → deleteJob', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(deleteJob).mockResolvedValue(undefined)
    const wrapper = mountPage()
    await flushPromises()
    const delBtn = wrapper.findAll('button').find((b) => b.text().includes('删除'))
    await delBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(deleteJob).toHaveBeenCalledWith(1)
  })

  it('执行走二次确认 → runJob', async () => {
    const confirmSpy = vi
      .spyOn(ElMessageBox, 'confirm')
      .mockResolvedValue('confirm' as unknown as MessageBoxData)
    vi.mocked(runJob).mockResolvedValue({
      id: 1,
      task_id: 1,
      handler_key: 'cleanup',
      trigger_type: 'manual',
      status: 'running',
      params_json: {},
      execution_id: 'e1',
      scheduled_at: null,
      started_at: null,
      finished_at: null,
      duration_ms: null,
      result_summary: null,
      error_code: null,
      error_message: null,
      actor_user_id: null,
      worker_id: null,
      created_at: '2026-06-12T00:00:00Z',
    })
    const wrapper = mountPage()
    await flushPromises()
    const runBtn = wrapper.findAll('button').find((b) => b.text().includes('执行'))
    await runBtn!.trigger('click')
    await flushPromises()
    expect(confirmSpy).toHaveBeenCalledTimes(1)
    expect(runJob).toHaveBeenCalledWith(1)
  })

  it('点日志 → 打开执行日志对话框并拉该任务日志', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const logBtn = wrapper.findAll('button').find((b) => b.text().trim() === '日志')
    await logBtn!.trigger('click')
    await flushPromises()
    expect(document.body.textContent).toContain('执行日志')
    expect(listJobLogs).toHaveBeenCalledWith(
      expect.objectContaining({ task_id: 1 }),
    )
  })
})
