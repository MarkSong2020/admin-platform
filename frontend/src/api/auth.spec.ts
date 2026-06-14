import { describe, it, expect, vi, beforeEach } from 'vitest'
import { __resetSessionForTest, setTokens, hasRefresh, attachAuthHeaders } from './session'
import {
  MissingRefreshTokenError,
  getCaptcha,
  login,
  logout,
  fetchUserInfo,
  fetchRouters,
} from './auth'

/** 构造 JSON Response（同 cross-channel.spec 的 mock 风格）。 */
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

describe('login', () => {
  it('成功 → setTokens（access 进内存 / refresh 进 sessionStorage）并返回响应', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          access_token: 'a1',
          token_type: 'bearer',
          expires_in: 900,
          refresh_token: 'r1',
          refresh_expires_in: 86400,
        }),
      ),
    )
    const res = await login({ username: 'admin', password: 'pass' })
    expect(res.access_token).toBe('a1')
    expect(hasRefresh()).toBe(true)
    const headers = new Headers()
    attachAuthHeaders(headers)
    expect(headers.get('Authorization')).toBe('Bearer a1')
  })

  it('响应缺 refresh_token（pepper 未配）→ 抛 MissingRefreshTokenError 且不 setTokens', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          access_token: 'a1',
          token_type: 'bearer',
          expires_in: 900,
          refresh_token: null,
          refresh_expires_in: null,
        }),
      ),
    )
    await expect(login({ username: 'admin', password: 'pass' })).rejects.toBeInstanceOf(
      MissingRefreshTokenError,
    )
    expect(hasRefresh()).toBe(false)
    const headers = new Headers()
    attachAuthHeaders(headers)
    expect(headers.get('Authorization')).toBeNull()
  })

  it('401 RFC9457 业务错误 → 抛归一化错误，错误码在 code（type 字段）且保留 title/detail', async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse(
        {
          type: 'auth.CAPTCHA_REQUIRED',
          title: '需要验证码',
          status: 401,
          detail: '失败次数过多，请输入验证码',
          request_id: 'req-1',
        },
        401,
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    await expect(login({ username: 'admin', password: 'bad' })).rejects.toMatchObject({
      code: 'auth.CAPTCHA_REQUIRED',
      status: 401,
      message: '需要验证码',
      detail: '失败次数过多，请输入验证码',
    })
    // login 在 AUTH_PATHS 内：401 不得触发自动 refresh 重放
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('422 RFC9457 校验错误 → 同样归一化并保留错误码', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(
          {
            type: 'framework.VALIDATION_ERROR',
            title: '请求体校验失败',
            status: 422,
            request_id: 'req-2',
          },
          422,
        ),
      ),
    )
    await expect(login({ username: '', password: '' })).rejects.toMatchObject({
      code: 'framework.VALIDATION_ERROR',
      status: 422,
    })
  })
})

describe('logout', () => {
  it('有 refresh → 请求体携带 refresh_token，最终 clearTokens', async () => {
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    const bodies: string[] = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const req = input instanceof Request ? input : new Request(String(input), init)
      bodies.push(await req.clone().text())
      return new Response(null, { status: 204 })
    })
    vi.stubGlobal('fetch', fetchMock)
    await logout()
    expect(bodies).toHaveLength(1)
    expect(bodies[0]).toContain('"refresh_token":"r1"')
    expect(hasRefresh()).toBe(false)
  })

  it('请求失败（500）→ 仍然 clearTokens 且不抛出', async () => {
    setTokens({ accessToken: 'a1', refreshToken: 'r1' })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 500 })))
    await expect(logout()).resolves.toBeUndefined()
    expect(hasRefresh()).toBe(false)
  })

  it('无 refresh → 跳过请求，直接 clearTokens', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await logout()
    expect(fetchMock).not.toHaveBeenCalled()
    expect(hasRefresh()).toBe(false)
  })
})

describe('getCaptcha', () => {
  it('返回算术题 question', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({ captcha_id: 'c1', question: '3 + 5 = ?', expires_in: 120 }),
      ),
    )
    const res = await getCaptcha()
    expect(res.captcha_id).toBe('c1')
    expect(res.question).toBe('3 + 5 = ?')
  })
})

describe('fetchUserInfo / fetchRouters', () => {
  it('fetchUserInfo 返回 user/roles/permissions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse({
          user: {
            id: 1,
            username: 'admin',
            nickname: '管理员',
            dept_id: null,
            status: 'active',
            is_super_admin: true,
          },
          roles: ['superadmin'],
          permissions: ['*:*:*'],
        }),
      ),
    )
    const info = await fetchUserInfo()
    expect(info.user.username).toBe('admin')
    expect(info.permissions).toEqual(['*:*:*'])
  })

  it('fetchRouters 返回 RouterVO 树（camelCase 字段）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse([
          {
            name: 'System',
            path: '/system',
            component: 'Layout',
            redirect: 'noRedirect',
            hidden: false,
            alwaysShow: true,
            meta: { title: '系统管理', icon: 'system', noCache: false, link: null },
            children: [],
          },
        ]),
      ),
    )
    const routers = await fetchRouters()
    expect(routers).toHaveLength(1)
    expect(routers[0]!.alwaysShow).toBe(true)
  })
})
