import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import ServerPage from './index.vue'
import { getServerMetrics } from '@/api/server'

vi.mock('@/api/server', () => ({
  getServerMetrics: vi.fn(),
}))

const METRICS = {
  collected_at: '2026-06-12T00:00:00Z',
  cpu: { percent: 33.3, per_cpu: [30, 40], cores: 8, load_avg: [0.5, 0.6, 0.7] },
  memory: { total: 16000000000, used: 8000000000, available: 8000000000, percent: 50 },
  swap: { total: 2000000000, used: 100000000, free: 1900000000, percent: 5 },
  disks: [
    {
      device: '/dev/disk1',
      mountpoint: '/',
      fstype: 'apfs',
      total: 500000000000,
      used: 250000000000,
      free: 250000000000,
      percent: 50,
    },
  ],
  process: {
    pid: 4321,
    cpu_percent: 1.2,
    memory_rss: 123456789,
    memory_percent: 0.7,
    num_threads: 12,
    create_time: '2026-06-12T00:00:00Z',
  },
  sys: {
    hostname: 'demo-host',
    os_name: 'Darwin',
    os_release: '25.5.0',
    arch: 'arm64',
    python_version: '3.14.0',
    boot_time: '2026-06-01T00:00:00Z',
  },
}

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(ServerPage, {
    global: { plugins: [ElementPlus, pinia] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.mocked(getServerMetrics).mockReset()
  vi.mocked(getServerMetrics).mockResolvedValue(METRICS)
  document.body.innerHTML = ''
})

describe('服务监控页', () => {
  it('挂载即拉取并渲染关键指标', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(getServerMetrics).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('demo-host')
    expect(wrapper.text()).toContain('3.14.0')
    expect(wrapper.text()).toContain('4321')
  })

  it('点刷新重新拉取指标', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const refreshBtn = wrapper.findAll('button').find((b) => b.text().includes('刷新'))
    await refreshBtn!.trigger('click')
    await flushPromises()
    expect(getServerMetrics).toHaveBeenCalledTimes(2)
  })
})
