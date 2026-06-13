import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import CachePage from './index.vue'
import { getCacheMetrics } from '@/api/cache'

vi.mock('@/api/cache', () => ({
  getCacheMetrics: vi.fn(),
}))

const AVAILABLE = {
  available: true,
  collected_at: '2026-06-12T00:00:00Z',
  db_size: 42,
  info: {
    version: '7.2.0',
    mode: 'standalone',
    uptime_seconds: 3600,
    connected_clients: 3,
    used_memory: 1048576,
    used_memory_human: '1.00M',
    maxmemory: 0,
    mem_fragmentation_ratio: 1.1,
    keyspace_hits: 100,
    keyspace_misses: 10,
    hit_rate: 0.91,
    total_commands_processed: 200,
  },
  command_stats: [{ name: 'get', calls: 100, usec: 500, usec_per_call: 5 }],
}

const UNAVAILABLE = {
  available: false,
  collected_at: '2026-06-12T00:00:00Z',
  db_size: null,
  info: null,
  command_stats: [],
}

let pinia: ReturnType<typeof createPinia>

function mountPage(): VueWrapper {
  return mount(CachePage, {
    global: { plugins: [ElementPlus, pinia] },
    attachTo: document.body,
  })
}

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.mocked(getCacheMetrics).mockReset()
  document.body.innerHTML = ''
})

describe('缓存监控页', () => {
  it('available=true 正常渲染 info + command_stats', async () => {
    vi.mocked(getCacheMetrics).mockResolvedValue(AVAILABLE)
    const wrapper = mountPage()
    await flushPromises()
    expect(getCacheMetrics).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('7.2.0')
    expect(wrapper.text()).toContain('1.00M')
    // command_stats 表里的命令名。
    expect(wrapper.text()).toContain('get')
  })

  it('available=false 降级：显示不可用提示，不渲染 info', async () => {
    vi.mocked(getCacheMetrics).mockResolvedValue(UNAVAILABLE)
    const wrapper = mountPage()
    await flushPromises()
    expect(getCacheMetrics).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('缓存不可用')
    // 降级时不应出现 info 字段值（如版本号标签）。
    expect(wrapper.text()).not.toContain('7.2.0')
  })

  it('点刷新重新拉取指标', async () => {
    vi.mocked(getCacheMetrics).mockResolvedValue(AVAILABLE)
    const wrapper = mountPage()
    await flushPromises()
    const refreshBtn = wrapper.findAll('button').find((b) => b.text().includes('刷新'))
    await refreshBtn!.trigger('click')
    await flushPromises()
    expect(getCacheMetrics).toHaveBeenCalledTimes(2)
  })
})
