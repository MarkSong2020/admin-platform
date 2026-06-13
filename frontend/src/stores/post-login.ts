/**
 * 登录后装配入口（同 session-expiry/logout 注入模式：stores 持回调，main.ts 装配）。
 * setupAfterLogin（getInfo → getRouters → addRoute）实现归 router composition root；
 * views 禁 import src/router，登录页只调 runPostLoginSetup()。
 */
let setupImpl: (() => Promise<void>) | null = null

export function registerPostLoginSetup(impl: () => Promise<void>): void {
  setupImpl = impl
}

/** 登录成功后调用：执行 main.ts 注入的 setupAfterLogin；未装配视为装配缺陷，fail fast。 */
export async function runPostLoginSetup(): Promise<void> {
  if (!setupImpl) {
    throw new Error('post-login setup 未注册：main.ts 应先 registerPostLoginSetup(setupAfterLogin)')
  }
  await setupImpl()
}

/** 仅供单测重置注入。 */
export function __resetPostLoginForTest(): void {
  setupImpl = null
}
