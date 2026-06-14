import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import ElementPlus from 'element-plus'
import JobFormDialog from './JobFormDialog.vue'
import { listHandlers, createJob } from '@/api/job'
import type { ScheduledTaskRead } from '@/api/job'

vi.mock('@/api/job', () => ({
  createJob: vi.fn(),
  updateJob: vi.fn(),
  listHandlers: vi.fn(),
}))

function mountDialog(over: Partial<{ editing: ScheduledTaskRead | null }> = {}): VueWrapper {
  return mount(JobFormDialog, {
    props: {
      visible: true,
      editing: over.editing ?? null,
      'onUpdate:visible': () => {},
    },
    global: { plugins: [ElementPlus] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  vi.mocked(listHandlers).mockReset()
  vi.mocked(listHandlers).mockResolvedValue([
    { key: 'cleanup', display_name: '清理', allow_manual: true },
    { key: 'reconcile', display_name: '对账', allow_manual: false },
  ])
  vi.mocked(createJob).mockReset()
  vi.mocked(createJob).mockResolvedValue({} as ScheduledTaskRead)
  document.body.innerHTML = ''
})

describe('JobFormDialog', () => {
  it('打开时从白名单加载 handler 选项', async () => {
    mountDialog()
    await flushPromises()
    expect(listHandlers).toHaveBeenCalledTimes(1)
    const options = document.body.querySelectorAll('.el-select-dropdown__item')
    const labels = Array.from(options).map((el) => el.textContent ?? '')
    expect(labels.some((l) => l.includes('清理') && l.includes('cleanup'))).toBe(true)
    expect(labels.some((l) => l.includes('对账'))).toBe(true)
  })

  it('handler 字段是受白名单约束的 el-select（非自由文本，杜绝选未注册 handler 防 RCE）', async () => {
    mountDialog()
    await flushPromises()
    // 处理器项渲染为 el-select（约束选择），而非可任意输入的文本框
    expect(document.body.querySelectorAll('.el-select').length).toBe(1)
    // 下拉项仅来自 listHandlers 白名单（两项），无任意串入口
    const options = document.body.querySelectorAll('.el-select-dropdown__item')
    expect(options.length).toBe(2)
    const labels = Array.from(options).map((el) => el.textContent ?? '')
    expect(labels.every((l) => l.includes('cleanup') || l.includes('reconcile'))).toBe(true)
  })

  it('params 非法 JSON → 校验拦截，不调 createJob', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      form: { name: string; handlerKey: string; cronExpression: string; paramsText: string }
      submit: () => Promise<void>
    }
    // 填齐必填项，但 params 为非法 JSON
    vm.form.name = '任务A'
    vm.form.handlerKey = 'cleanup'
    vm.form.cronExpression = '0 0 * * *'
    vm.form.paramsText = '{不是合法json'
    await vm.submit()
    await flushPromises()
    expect(createJob).not.toHaveBeenCalled()
    expect(document.body.textContent).toContain('params 不是合法 JSON')
  })

  it('params 合法 JSON 对象 + 必填齐全 → 调 createJob，body 字段为 params', async () => {
    const wrapper = mountDialog()
    await flushPromises()
    const vm = wrapper.vm as unknown as {
      form: { name: string; handlerKey: string; cronExpression: string; paramsText: string }
      submit: () => Promise<void>
    }
    vm.form.name = '任务A'
    vm.form.handlerKey = 'cleanup'
    vm.form.cronExpression = '0 0 * * *'
    vm.form.paramsText = '{"dry": true}'
    await vm.submit()
    await flushPromises()
    expect(createJob).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(createJob).mock.calls[0]![0]
    expect(payload.handler_key).toBe('cleanup')
    expect(payload.params).toEqual({ dry: true })
  })
})
