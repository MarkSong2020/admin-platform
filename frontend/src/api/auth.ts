/**
 * 认证 API 类型化封装（全部经 client.ts 的 openapi-fetch 实例，类型来自 generated/）。
 * refresh 不在此处——single-flight 刷新归 session.ts（spec §3.1）。
 * login/captcha/logout 在 client 的 AUTH_PATHS 内，401 不会触发自动 refresh：
 * 业务错误（验证码错/限流/CAPTCHA_REQUIRED）经 normalizeProblemBody 归一化抛出，供登录页分支处理。
 */
import { apiClient } from './client'
import { unwrap } from './transport'
import { setTokens, clearTokens, getRefreshToken } from './session'
import type { components } from './generated/types'

export type CaptchaResponse = components['schemas']['CaptchaResponse']
export type LoginRequest = components['schemas']['LoginRequest']
export type LoginResponse = components['schemas']['LoginResponse']
export type UserInfoResponse = components['schemas']['UserInfoResponse']
export type UserInfoUser = components['schemas']['UserInfoUser']
export type RouterVO = components['schemas']['RouterVO']

/**
 * 登录成功但响应缺 refresh_token = 环境配置错误（fail fast，spec §6）。
 * 与「验证码失败/限流/账号停用」等正常登录错误分支区分，不走常规错误提示。
 */
export class MissingRefreshTokenError extends Error {
  constructor() {
    super('登录响应缺少 refresh_token：后端未配置 APP_AUTH_REFRESH_TOKEN_PEPPER，请检查环境配置')
    this.name = 'MissingRefreshTokenError'
  }
}

/** 获取算术验证码（登录失败 N 次后强制）。 */
export async function getCaptcha(): Promise<CaptchaResponse> {
  return unwrap(await apiClient.GET('/api/v1/auth/captcha'))
}

/**
 * 登录：成功 → setTokens 并返回响应；缺 refresh_token → 抛 MissingRefreshTokenError（不 setTokens）。
 * 业务错误（401/422 RFC9457）抛归一化 ApiError，错误码在 code（即 ProblemDetail.type）。
 */
export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const data = unwrap(await apiClient.POST('/api/v1/auth/login', { body: payload }))
  if (!data.refresh_token) throw new MissingRefreshTokenError()
  setTokens({ accessToken: data.access_token, refreshToken: data.refresh_token })
  return data
}

/**
 * 登出：有 refresh 则带请求体调后端撤销（失败容忍，best-effort）；最终必 clearTokens。
 * redirect/清 Pinia 不在此处——归 session 失效统一出口或调用方（spec §3.1）。
 */
export async function logout(): Promise<void> {
  const refreshToken = getRefreshToken()
  try {
    if (refreshToken) {
      await apiClient.POST('/api/v1/auth/logout', { body: { refresh_token: refreshToken } })
    }
  } catch {
    // 后端撤销失败不阻断本地登出（network/5xx 均容忍）
  } finally {
    clearTokens()
  }
}

/** getInfo：当前用户身份 + 角色 code + 权限码集合。 */
export async function fetchUserInfo(): Promise<UserInfoResponse> {
  return unwrap(await apiClient.GET('/api/v1/auth/user-info'))
}

/** getRouters：用户可见菜单树（若依 RouterVO，camelCase）。 */
export async function fetchRouters(): Promise<RouterVO[]> {
  return unwrap(await apiClient.GET('/api/v1/menus/routers'))
}
