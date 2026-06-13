import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import LoginPage from './index.vue'
import { getCaptcha, login, MissingRefreshTokenError } from '@/api/auth'
import { registerPostLoginSetup, __resetPostLoginForTest } from '@/stores/post-login'

vi.mock('@/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/auth')>()
  return {
    ...actual,
    getCaptcha: vi.fn(),
    login: vi.fn(),
  }
})

const CAPTCHA = { captcha_id: 'cap-1', question: '3 + 5 = ?', expires_in: 300 }

function makeRouter(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'login', component: LoginPage },
      // 回跳目标桩路由（catchAll，避免依赖动态路由装配）
      {
        path: '/:pathMatch(.*)*',
        name: 'stub',
        component: { render: () => null },
      },
    ],
  })
}

async function mountLogin(redirect?: string): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = makeRouter()
  await router.push(redirect ? `/login?redirect=${encodeURIComponent(redirect)}` : '/login')
  await router.isReady()
  const wrapper = mount(LoginPage, {
    global: { plugins: [router, ElementPlus, createPinia()] },
  })
  await flushPromises()
  return { wrapper, router }
}

/** 填表单（用户名/密码/验证码答案）并提交。 */
async function fillAndSubmit(wrapper: VueWrapper): Promise<void> {
  await wrapper.find('input[placeholder="用户名"]').setValue('admin')
  await wrapper.find('input[placeholder="密码"]').setValue('secret-pass')
  const answer = wrapper.find('input[placeholder="计算结果"]')
  if (answer.exists()) await answer.setValue('8')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
}

const postLoginSetup = vi.fn(async () => {})

beforeEach(() => {
  vi.mocked(getCaptcha).mockReset()
  vi.mocked(login).mockReset()
  vi.mocked(getCaptcha).mockResolvedValue(CAPTCHA)
  postLoginSetup.mockClear()
  __resetPostLoginForTest()
  registerPostLoginSetup(postLoginSetup)
  document.body.innerHTML = ''
})

describe('登录页', () => {
  it('进入页面即拉验证码并展示算术题', async () => {
    const { wrapper } = await mountLogin()
    expect(getCaptcha).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('3 + 5 = ?')
  })

  it('成功路径：login 带验证码字段 → runPostLoginSetup → replace 到 redirect query', async () => {
    vi.mocked(login).mockResolvedValue({
      access_token: 'at',
      token_type: 'bearer',
      expires_in: 900,
      refresh_token: 'rt',
      refresh_expires_in: 86400,
    })
    const { wrapper, router } = await mountLogin('/system/user')
    const replaceSpy = vi.spyOn(router, 'replace')

    await fillAndSubmit(wrapper)

    expect(login).toHaveBeenCalledWith({
      username: 'admin',
      password: 'secret-pass',
      captcha_id: 'cap-1',
      captcha_answer: '8',
    })
    expect(postLoginSetup).toHaveBeenCalledTimes(1)
    expect(replaceSpy).toHaveBeenCalledWith('/system/user')
  })

  it('无 redirect query → 成功后 replace 到 /', async () => {
    vi.mocked(login).mockResolvedValue({
      access_token: 'at',
      token_type: 'bearer',
      expires_in: 900,
      refresh_token: 'rt',
      refresh_expires_in: 86400,
    })
    const { wrapper, router } = await mountLogin()
    const replaceSpy = vi.spyOn(router, 'replace')

    await fillAndSubmit(wrapper)

    expect(replaceSpy).toHaveBeenCalledWith('/')
  })

  it('CAPTCHA_REQUIRED 错误 → 重新拉验证码，不跳转', async () => {
    vi.mocked(login).mockRejectedValue({
      code: 'auth.CAPTCHA_REQUIRED',
      status: 401,
      message: '需要验证码',
    })
    const { wrapper, router } = await mountLogin()
    const replaceSpy = vi.spyOn(router, 'replace')

    await fillAndSubmit(wrapper)

    // 进页 1 次 + 出错后刷新 1 次
    expect(getCaptcha).toHaveBeenCalledTimes(2)
    expect(postLoginSetup).not.toHaveBeenCalled()
    expect(replaceSpy).not.toHaveBeenCalled()
  })

  it('验证码服务不可用（getCaptcha 失败）→ 显示提示，不隐藏整页无反馈', async () => {
    vi.mocked(getCaptcha).mockRejectedValue(new Error('503 redis down'))
    const { wrapper } = await mountLogin()

    // 无算术题输入框，但有「暂不可用」提示（避免死循环无反馈）
    expect(wrapper.find('input[placeholder="计算结果"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('验证码服务暂不可用')
  })

  it('MissingRefreshTokenError → 显示环境配置错误 alert（fail fast）', async () => {
    vi.mocked(login).mockRejectedValue(new MissingRefreshTokenError())
    const { wrapper } = await mountLogin()

    await fillAndSubmit(wrapper)

    const alert = wrapper.find('.el-alert')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('APP_AUTH_REFRESH_TOKEN_PEPPER')
    expect(postLoginSetup).not.toHaveBeenCalled()
  })
})
