import { test, expect } from '@playwright/test'

// 未登录访问根路径 → 守卫重定向登录页（深链 redirect 回跳参数）
test('未登录访问根路径重定向到登录页', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/login\?redirect=/)
  await expect(page.locator('.login-shell')).toContainText('登录')
})
