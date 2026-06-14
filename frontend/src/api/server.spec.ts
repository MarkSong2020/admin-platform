import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { getServerMetrics } from './server'

interface Captured {
  method: string
  url: string
}

function captureFetch(captured: Captured[], responder: () => Response): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init)
    captured.push({ method: req.method, url: req.url })
    return responder()
  }) as unknown as typeof fetch
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const METRICS = {
  collected_at: '2026-06-12T00:00:00Z',
  cpu: { percent: 12.5, per_cpu: [10, 15], cores: 8, load_avg: [0.5, 0.6, 0.7] },
  memory: { total: 16000, used: 8000, available: 8000, percent: 50 },
  swap: { total: 2000, used: 100, free: 1900, percent: 5 },
  disks: [
    { device: '/dev/sda1', mountpoint: '/', fstype: 'apfs', total: 500, used: 250, free: 250, percent: 50 },
  ],
  process: {
    pid: 4321,
    cpu_percent: 1.2,
    memory_rss: 123456,
    memory_percent: 0.7,
    num_threads: 12,
    create_time: '2026-06-12T00:00:00Z',
  },
  sys: {
    hostname: 'box',
    os_name: 'Darwin',
    os_release: '25.5.0',
    arch: 'arm64',
    python_version: '3.14.0',
    boot_time: '2026-06-01T00:00:00Z',
  },
}

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('server api', () => {
  it('getServerMetrics 命中 GET /monitor/server（无参）并返回指标', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(METRICS)))
    const metrics = await getServerMetrics()
    expect(metrics.cpu.percent).toBe(12.5)
    expect(metrics.sys.hostname).toBe('box')
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/server')
  })
})
