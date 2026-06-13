import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest } from './session'
import {
  listJobs,
  getJob,
  createJob,
  updateJob,
  deleteJob,
  listHandlers,
  runJob,
  listJobLogs,
} from './job'

/** 记录每次 fetch 的 method / url / body，供断言路径与请求体。 */
interface Captured {
  method: string
  url: string
  body: string
}

function captureFetch(captured: Captured[], responder: () => Response): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(String(input), init)
    captured.push({
      method: req.method,
      url: req.url,
      body: req.body ? await req.clone().text() : '',
    })
    return responder()
  }) as unknown as typeof fetch
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function emptyPage(): Record<string, unknown> {
  return { items: [], page: 1, size: 20, total: 0, total_pages: 0 }
}

beforeEach(() => {
  __resetSessionForTest()
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('job api', () => {
  it('listJobs 透传 page/size/status/handler_key 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listJobs({ page: 2, size: 10, status: 'enabled', handler_key: 'noop' })
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/monitor/jobs')
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('size')).toBe('10')
    expect(url.searchParams.get('status')).toBe('enabled')
    expect(url.searchParams.get('handler_key')).toBe('noop')
  })

  it('listJobs 无过滤项时不带 status/handler_key', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listJobs({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('status')).toBe(false)
    expect(url.searchParams.has('handler_key')).toBe(false)
  })

  it('getJob 命中 GET /monitor/jobs/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 7, name: 'j7' })))
    const job = await getJob(7)
    expect(job.id).toBe(7)
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/jobs/7')
  })

  it('createJob POST /monitor/jobs，body 写侧字段为 params（非 params_json）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 9 }, 201)))
    await createJob({
      name: '清理',
      handler_key: 'noop',
      cron_expression: '0 0 * * *',
      cron_timezone: 'Asia/Shanghai',
      params: { dry: true },
      status: 'disabled',
      allow_concurrent: false,
      misfire_grace_seconds: 300,
    })
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/jobs')
    expect(captured[0]!.body).toContain('"handler_key":"noop"')
    expect(captured[0]!.body).toContain('"params":{"dry":true}')
    expect(captured[0]!.body).not.toContain('params_json')
  })

  it('updateJob 走 PATCH /monitor/jobs/{id}', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse({ id: 3 })))
    await updateJob(3, { status: 'enabled' })
    expect(captured[0]!.method).toBe('PATCH')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/jobs/3')
    expect(captured[0]!.body).toContain('"status":"enabled"')
  })

  it('deleteJob 走 DELETE /monitor/jobs/{id}（204 无 body）', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => new Response(null, { status: 204 })))
    await expect(deleteJob(5)).resolves.toBeUndefined()
    expect(captured[0]!.method).toBe('DELETE')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/jobs/5')
  })

  it('listHandlers 命中 GET /monitor/jobs/handlers，返回裸数组', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () =>
      jsonResponse([{ key: 'noop', display_name: '空操作', allow_manual: true }]),
    ))
    const handlers = await listHandlers()
    expect(handlers).toHaveLength(1)
    expect(handlers[0]!.key).toBe('noop')
    expect(captured[0]!.method).toBe('GET')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/jobs/handlers')
  })

  it('runJob POST /monitor/jobs/{id}/run（无 body）→ 执行日志', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () =>
      jsonResponse({ id: 1, task_id: 7, status: 'running', trigger_type: 'manual' }),
    ))
    const log = await runJob(7)
    expect(log.status).toBe('running')
    expect(captured[0]!.method).toBe('POST')
    expect(new URL(captured[0]!.url).pathname).toBe('/api/v1/monitor/jobs/7/run')
  })

  it('runJob 409 → 抛归一化 ApiError（保留 status）', async () => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      jsonResponse(
        { type: 'job.CONCURRENT', title: '任务正在执行', status: 409, request_id: 'r' },
        409,
      ),
    ))
    await expect(runJob(7)).rejects.toMatchObject({ status: 409 })
  })

  it('listJobLogs 透传 task_id/status 到 query', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listJobLogs({ page: 1, size: 20, task_id: 7, status: 'success' })
    const url = new URL(captured[0]!.url)
    expect(url.pathname).toBe('/api/v1/monitor/jobs/logs')
    expect(url.searchParams.get('task_id')).toBe('7')
    expect(url.searchParams.get('status')).toBe('success')
  })

  it('listJobLogs 无 task_id 时不带该参数', async () => {
    const captured: Captured[] = []
    vi.stubGlobal('fetch', captureFetch(captured, () => jsonResponse(emptyPage())))
    await listJobLogs({ page: 1, size: 20 })
    const url = new URL(captured[0]!.url)
    expect(url.searchParams.has('task_id')).toBe(false)
  })
})
