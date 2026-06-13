import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import { getCacheMetrics } from './cache'

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

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('cache api', () => {
  it('getCacheMetrics 命中 GET /monitor/cache 并返回可用指标', async () => {
    const captured: Captured[] = []
    vi.stubGlobal(
      'fetch',
      captureFetch(captured, () =>
        jsonResponse({
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
        }),
      ),
    )
    const metrics = await getCacheMetrics()
    expect(metrics.available).toBe(true)
    expect(metrics.info?.version).toBe('7.2.0')
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/cache')
  })

  it('getCacheMetrics 降级：available=false 时 info 为 null', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          available: false,
          collected_at: '2026-06-12T00:00:00Z',
          db_size: null,
          info: null,
          command_stats: [],
        }),
      ),
    )
    const metrics = await getCacheMetrics()
    expect(metrics.available).toBe(false)
    expect(metrics.info).toBeNull()
  })
})
